"""The URL map. Every API route is declared beside its handler, in its
module's @route("METHOD /path", ...), and build_routes mounts each one in
MODULES, the most specific path first, behind the guards its declaration
implies:

- Anyone signed in, by a browser session or an API key, is the default.
  role=ADMIN is the admins, and role=OWNER the owner from a browser session;
  everyone else gets the 404 an unknown route gets.
- access=SESSION_ONLY turns an API key away. It guards what a key must not
  reach: minting and managing API keys, your own password, PIN and
  two-factor, other people's files. A key that could do those could turn
  itself into a session or carry off every account's files.
- An admin-scoped key may manage accounts and hand out login and invite links.
  Every link records the key that made it, and revoking or deleting that key
  voids the links it made that can still be used, so revoking a leaked key
  still ends what it could hand out. Who may delete or demote whom is in the
  models.
- access=PUBLIC needs no sign-in: logging in, the UI's text, health.
- A feature that can be switched off while the server runs has a switch in
  FEATURE_GUARDS: its routes answer 404 while it is off, before anything else
  is asked.

The Go template's server/routes/routes_generated.go is the same table, written
by its generator from the same rules. Only the pages a link opens and the
catch-alls are written out here.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Route

from app.apidocs import ADMIN, KEY_ONLY, OWNER, PUBLIC, SESSION_ONLY
from app.apidocs.route import Declared, declared_of
from app.core.security import RequireAdmin, RequireLogin, RequireSession
from app.core.security import Guard
from app.core.security import RequireAPIKey
from app.core.security import RequireOwner
from app.core.static_files import StaticServer
from app.routes import (
    account,
    admin,
    api_keys,
    auth,
    invite_links,
    join,
    logs,
    mcp_manifest,
    meta,
    openapi,
    passwords,
    sessions,
    settings,
    team,
    themes,
    two_factor,
)
from app.routes import discover, dupes, images, jobs, library, lookup, media_types, playlists, porting, prefs, state, suggestions, titles
from app.routes.api_keys import RequireAPIKeys
from app.routes.helpers import get_config
from app.routes.helpers import not_found


class RequireMCP(Guard):
    """Makes /mcp answer 404 while server.mcp or auth.api_keys is off --
    exactly what an unregistered route would say. Checked per request rather
    than by registering /mcp or not, because both can be switched while the
    server runs."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        cfg = get_config(request)
        if not cfg.mcp_enabled or not cfg.api_keys_enabled:
            return not_found("not found")
        return None


class RequirePasswords(Guard):
    """Makes every password route answer 404 while auth.passwords is off.
    Per request, for the same reason as RequireMCP."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).passwords_enabled else not_found("not found")


class RequireTwoFactor(Guard):
    """The same for setting up 2FA while auth.two_factor is off. Finishing a
    sign-in is not behind this: one already under way may as well end."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).two_factor_enabled else not_found("not found")


class RequireInviteLinks(Guard):
    """Makes every invite route answer 404 while auth.invite_links is off. Per
    request, for the same reason as RequireMCP. The /join page itself is
    StaticServer.serve_join_page, so a person gets the styled 404 instead."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).invite_links_enabled else not_found("not found")


class RequireLogs(Guard):
    """Makes the activity log's routes answer 404 while the log is off
    (logs.enabled). Per request, like RequireWebhooks."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        logger = getattr(request.app.state, "logs", None)
        return None if logger is not None and logger.enabled else not_found("not found")


# Every module with declared routes, in the order the docs list ties.
MODULES = [
    account,
    admin,
    api_keys,
    auth,
    invite_links,
    join,
    logs,
    mcp_manifest,
    meta,
    openapi,
    passwords,
    sessions,
    settings,
    team,
    themes,
    two_factor,
    # MediaTracker's own.
    library,
    images,
    titles,
    state,
    lookup,
    dupes,
    porting,
    discover,
    jobs,
    prefs,
    suggestions,
    playlists,
    media_types,
]

# The switches of the features that can be off while the server runs, by
# feature name: a route whose op says feature=x answers 404 while x is off,
# exactly what an unregistered route would say. It goes in front of every
# other guard. Go's featureGuards (server/routes/routes.go) is the same map.
FEATURE_GUARDS: dict[str, type[Guard]] = {
    "invite_links": RequireInviteLinks,
    "passwords": RequirePasswords,
    "two_factor": RequireTwoFactor,
    "api_keys": RequireAPIKeys,
    "mcp": RequireMCP,
    "logs": RequireLogs,
}


def guards_of(declared: Declared) -> tuple[type, ...]:
    """The guards in front of a route, in order: its feature's switch, who may
    call it, a session for SESSION_ONLY, then its own use=[...]."""
    op = declared.op
    guards: list[type] = []
    if op.feature in FEATURE_GUARDS and not declared.no_switch:
        guards.append(FEATURE_GUARDS[op.feature])
    if op.access == KEY_ONLY:
        guards.append(RequireAPIKey)
        if op.role == ADMIN:
            guards.append(RequireAdmin)
    elif op.access != PUBLIC:
        guards.append(RequireAdmin if op.role == ADMIN else RequireOwner if op.role == OWNER else RequireLogin)
    if op.access == SESSION_ONLY and op.role != OWNER:
        guards.append(RequireSession)
    guards.extend(declared.use)
    return tuple(guards)


def errors_of(declared: Declared) -> tuple[int, ...]:
    """Every error status the docs list for a route: its guards', the
    request checks' (400 for a request with fields, and 400 and 403 for a
    csrf token to check), and the handler's own errors=(...)."""
    op = declared.op
    statuses = set(op.errors)
    for guard in declared.guards:
        statuses.update(getattr(guard, "statuses", ()))
    if declared.method != "GET" and op.access != PUBLIC and not op.no_csrf and op.raw_body is None:
        statuses.update((400, 403))
    if declared.input.fields:
        statuses.add(400)
    return tuple(sorted(statuses))


PARAMETER = re.compile(r"^\{\w+\}$")


def _segments(path: str) -> list[str]:
    return [part for part in path.strip("/").split("/") if part]


def _order(declared: Declared) -> Any:
    """Most specific first: at the first segment where two differ, a literal
    before a {param}, then literals in order; a shorter path before a longer
    one it starts; then by method. Go's generator sorts the same way."""
    return ([(1, "") if PARAMETER.match(part) else (0, part) for part in _segments(declared.path)], declared.path, declared.method)


def _ambiguous(a: Declared, b: Declared) -> bool:
    """One URL could match both, with neither the more specific."""
    left, right = _segments(a.path), _segments(b.path)
    if a.method != b.method or len(left) != len(right):
        return False
    left_wins = right_wins = False
    for one, other in zip(left, right):
        one_param, other_param = bool(PARAMETER.match(one)), bool(PARAMETER.match(other))
        if not one_param and not other_param and one != other:
            return False
        left_wins |= not one_param and other_param
        right_wins |= one_param and not other_param
    return left_wins == right_wins


def declared_routes() -> list[Declared]:
    """Every route declared in MODULES, in the order they are mounted, with
    their guards and error statuses filled in. A clash is a mistake to fix,
    not something to resolve by order."""
    found: list[Declared] = []
    for module in MODULES:
        for value in vars(module).values():
            declared = declared_of(value)
            if declared is not None and declared.endpoint is value and declared not in found:
                found.append(declared)
                if declared.bulk is not None:
                    found.append(declared.bulk)
    ordered = sorted(found, key=_order)
    for index, one in enumerate(ordered):
        for other in ordered[index + 1:]:
            if _ambiguous(one, other):
                raise TypeError(f"{one.method} {one.path} and {other.method} {other.path} can match the same request")
    for declared in ordered:
        declared.guards = guards_of(declared)
        declared.errors = errors_of(declared)
    return ordered


def build_routes(static_server: StaticServer) -> list[BaseRoute]:
    routes: list[BaseRoute] = [
        # The pages a login link and an invite link open. Opening one only
        # shows a page; the link is spent by the POST that page sends when the
        # person confirms. See auth.py and join.py.
        Route("/login/{credential:path}", static_server.serve_login_page),
        Route("/join/{credential:path}", static_server.serve_join_page),
    ]
    for declared in declared_routes():
        middleware = [Middleware(guard) for guard in declared.guards]
        routes.append(Route(declared.path, declared.endpoint, methods=[declared.method], middleware=middleware))
    return routes + [
        # Any other /api/ path is a JSON 404, not the index.html fallback.
        Route("/api/{rest:path}", meta.unknown_api),
        # Catch-all static serving. Must stay last -- it matches every
        # remaining path, so anything added after this line never runs.
        Route("/{path:path}", static_server.endpoint),
    ]
