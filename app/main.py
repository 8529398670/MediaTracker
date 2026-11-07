"""The web server. This module only wires things together -- load config,
resolve assets, open the database, build the app, start and stop cleanly.
Every decision of substance lives in a module under app/core/, app/models/,
or app/routes/. If you find yourself adding business logic here, it belongs
in a route module or a new core module instead.

Started by `python -m app` (see app/__main__.py), never by pointing uvicorn
at it from the command line: host, port, and every other setting come from
config.yaml, and a second place to pass them would be a second source of
truth.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware

from app.core import assets, bootstrap, config, db, language
from app.core.middleware import EXCEPTION_HANDLERS, RateLimit, SecurityHeaders
from app.core.security import LoadActor
from app.core.static_files import StaticServer
from app.discover import catalogue, certs
from app.jobs import runner as jobs
from app.jobs import scheduler
from app.models import api_keys, invite_links, login_tokens, playlists, sessions, sources, titles, types, views
from app.providers import compat, net
from app.reference import images, imdb, imdb_genres
from app.reference import paths as reference_paths
from app.routes import build_routes

PURGE_INTERVAL_SECONDS = 60 * 60


def purge_once(store: db.Store, cfg: config.Config | None = None) -> None:
    """Drop expired sessions, expired login tokens, and the API keys and
    invite links that have been dead long enough to stop being worth listing.
    None of it is a correctness issue -- every one of those is already refused
    on read -- so this runs quietly in the background purely to keep the file
    from growing forever."""
    removed_sessions = sessions.purge_expired_sessions(store)
    removed_tokens = login_tokens.purge_expired_login_tokens(store)
    removed_keys = api_keys.purge_dead_api_keys(store)
    removed_invites = invite_links.purge_dead_invite_links(store)
    removed_titles = titles.purge_deleted_titles(store, cfg.library.restore_days) if cfg is not None else 0
    views.purge_deleted_views(store)
    playlists.purge_deleted_playlists(store)
    sources.purge_deleted_sources(store)
    if removed_titles:
        print(f"[purge] removed {removed_titles} titles deleted more than {cfg.library.restore_days} days ago", flush=True)
    if removed_sessions or removed_tokens or removed_keys or removed_invites:
        print(
            f"[purge] removed {removed_sessions} expired sessions, {removed_tokens} expired login tokens, "
            f"{removed_keys} dead api keys, {removed_invites} dead invite links",
            flush=True,
        )


async def purge_loop(store: db.Store, cfg: config.Config) -> None:
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        try:
            await run_in_threadpool(purge_once, store, cfg)
        except Exception as error:  # noqa: BLE001 -- housekeeping must never take the server down
            print(f"[purge] failed: {error}", flush=True)


def prepare_media(store: db.Store, cfg: config.Config) -> None:
    net.configure(cfg.providers.network, cfg.providers.user_agent, cfg.providers.timeout_seconds)
    compat.configure(cfg.providers.tmdb_api_key, cfg.providers.omdb_api_key, cfg.providers.network)
    where = reference_paths.configure(cfg.storage_dir)
    imdb.configure(where.imdb)
    imdb_genres.configure(where.imdb)
    images.CACHE.configure(where.images, cfg.images.cache_mb, cfg.images.allow_hosts)
    catalogue.configure(where.lists)
    certs.configure(where.certs)
    certs.STORE.load()
    catalogue.catalogue()
    types.ensure_builtin(store)
    playlists.migrate_queue_order(store)
    titles.refold_genres(store)
    scheduler.prepare(store, cfg)


def build_app(
    cfg: config.Config, store: db.Store, lang: language.Language, static_server: StaticServer, version: str = "dev"
) -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(purge_loop(store, cfg))
        # The media side: reference data read before the first request (so
        # the first library load already has IMDb scores), then the job
        # scheduler that keeps it fresh.
        await run_in_threadpool(prepare_media, store, cfg)
        job_task = asyncio.create_task(scheduler.loop(store, cfg))
        try:
            yield
        finally:
            task.cancel()
            job_task.cancel()
            jobs.stop_all()

    app = Starlette(
        routes=build_routes(static_server, cfg),
        # Outermost first. Headers go on everything; the rate limit runs
        # before anything touches the database, so a flood is cheap to refuse;
        # then the caller is resolved once for every route behind it.
        middleware=[
            Middleware(SecurityHeaders, cfg=cfg),
            # The library feed is a megabyte of JSON; compressed it is a
            # tenth of that. Static files are already gzipped by StaticServer.
            Middleware(GZipMiddleware, minimum_size=2048),
            Middleware(RateLimit, cfg=cfg),
            Middleware(LoadActor, store=store, cfg=cfg),
        ],
        exception_handlers=EXCEPTION_HANDLERS,
        lifespan=lifespan,
        max_body_size=cfg.body_limit_bytes,
    )
    app.state.config = cfg
    app.state.store = store
    app.state.language = lang
    # Reported to MCP clients as serverInfo.version.
    app.state.version = version
    return app


def serve(version: str) -> None:
    cfg = config.load()
    bundle = assets.resolve(cfg.static_dir, cfg.language_file)
    store = db.open_store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
    lang = language.parse(bundle.language_yaml)
    static_server = StaticServer(bundle.static_dir)

    bootstrap.ensure_first_admin(store, cfg, "Admin")

    app = build_app(cfg, store, lang, static_server, version)

    print(f"[start] {cfg.project_name} {version} listening on {cfg.listen_address} (secure cookies: {cfg.secure_cookies})")
    print(f"[url]    {cfg.url}  (from {cfg.url_source})")
    if cfg.config_created:
        print(f"[config] {cfg.config_file} (created, with a new secret key -- back it up)")
    else:
        print(f"[config] {cfg.config_file}")
    if cfg.config_warning:
        print(f"[config] warning: {cfg.config_warning}")
    print(f"[state]  {cfg.app_dir}")
    print(f"[assets] {bundle.source}", flush=True)

    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        # An empty Server header keeps the response from advertising which
        # server and version is running -- free reconnaissance otherwise.
        server_header=False,
        # Proxy trust is server.trust_proxy, applied by the rate limiter's
        # client_ip(); uvicorn's own X-Forwarded-For handling would be a
        # second, differently configured answer to the same question.
        proxy_headers=False,
        # Idle keep-alive connections are dropped rather than held until the
        # process runs out of sockets; in-flight requests get 10s to finish
        # on shutdown so the database is never left mid-write.
        timeout_keep_alive=75,
        timeout_graceful_shutdown=10,
        lifespan="on",
        log_level="info",
    )
