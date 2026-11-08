"""Public endpoints that are about the app rather than about anyone in it."""
from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import db, graceful
from app.models import users

READY_TIMEOUT_SECONDS = 2.0


async def get_language(request: Request) -> Response:
    """The whole language.yaml tree as JSON. Deliberately public: the
    signed-out page has text too, and none of it is secret. Do not put
    anything sensitive in language.yaml -- it is, by design, readable by
    anyone who can reach the server."""
    return Response(
        request.app.state.language.json,
        media_type="application/json",
        headers={"cache-control": "no-store"},
    )


async def get_health(request: Request) -> Response:
    """What the Dockerfile HEALTHCHECK hits. Trivial on purpose -- if it
    touched the database, a slow query would get the container killed and
    restarted, turning a small problem into an outage."""
    return JSONResponse({"ok": True})


def ready_now(store: db.Store) -> bool:
    """The database is at the schema this code expects and the owner's marker
    reads back, which proves the file opens and the key decrypts it."""
    return store.schema_version() == db.latest_schema_version() and users.get_owner_id(store) is not None


async def _probe(store: db.Store) -> bool:
    try:
        return await graceful.run_abandonable(ready_now, store)
    except Exception as error:  # noqa: BLE001 -- not ready is the whole answer
        print(f"[ready] {error!r}", flush=True)
        return False


async def get_ready(request: Request) -> Response:
    """Whether this instance can serve: what a load balancer or an orchestrator
    asks, as against /api/health, which only says the process is up. Public,
    so it says yes or no and nothing else.

    A probe already running is shared, so a slow disk and a busy prober cannot
    stack up threads. asyncio.wait rather than wait_for: the timeout must not
    cancel the probe, because a thread cannot be interrupted, and waiting for
    the cancel to land would be waiting for the very thing that is slow."""
    state = request.app.state
    probe: asyncio.Task[bool] | None = getattr(state, "ready_probe", None)
    if probe is None or probe.done():
        probe = state.ready_probe = asyncio.create_task(_probe(state.store))
    done, _ = await asyncio.wait({probe}, timeout=READY_TIMEOUT_SECONDS)
    ok = bool(done) and probe.result()
    return JSONResponse({"ok": ok}, status_code=200 if ok else 503)


async def unknown_api(request: Request) -> Response:
    """An /api/ path nothing claims. Without this the static catch-all would
    answer with index.html and a 200, which is a confusing reply to a script
    that mistyped an endpoint."""
    return JSONResponse({"error": "not found"}, status_code=404)
