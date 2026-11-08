"""Maintenance mode: server.maintenance, read per request so switching it
applies at once.

"none" rather than "off" is the normal value because YAML 1.1 readers, PyYAML
among them, take a bare off as false.

allows() says what is open to anyone in each mode. Past that, only the owner's
browser session gets through, which is what lets them check the work and turn
the mode off. Their API keys are refused like anyone's, as on every owner
route: see RequireOwner. Go's twin is server/routes/maintenance.go and
server/middleware/maintenance.go.

It sits inside LoadActor because it has to know who is asking, and inside
RequestLog so a refusal is logged like any other answer. `manage` never comes
through here.
"""
from __future__ import annotations

from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import error_page
from app.core.config_live import Holder
from app.core.db import Store
from app.core.middleware import static_asset
from app.models import users

MAINTENANCE_NONE = "none"
MAINTENANCE_READ_ONLY = "read_only"
MAINTENANCE_FULL = "full"

# A refusal's Retry-After: long enough not to invite hammering, short enough
# that a script comes back soon after the end.
RETRY_SECONDS = 300

# Open in every mode: the checks that watch the server, the words the page
# needs, and everything it takes to sign in and out, which is how the owner
# gets back to the switch.
ALWAYS = frozenset({
    "/api/health",
    "/api/ready",
    "/api/language",
    "/api/me",
    "/api/logout",
    "/api/login",
    "/api/login/options",
    "/api/login/two-factor",
    "/api/login/password",
})


def allows(mode: str, method: str, path: str) -> bool:
    """Whether a request gets through for anyone. The path is normalised as in
    budget_for, so the two templates agree.

    read_only trusts a GET not to change anything, so a route that writes on a
    GET must not rely on this. Invite links stay shut in both modes: joining
    makes an account. /mcp is a POST either way, and one that cannot be sorted
    into a read or a write."""
    if mode == MAINTENANCE_NONE:
        return True
    normalised = path.lower()
    if len(normalised) > 1:
        normalised = normalised.rstrip("/")
    if normalised in ALWAYS or normalised == "/login" or normalised.startswith("/login/"):
        return True
    # A file the page loads, but not a page: /index.html is the app itself.
    if static_asset(method, normalised) and not normalised.endswith(".html"):
        return True
    if mode == MAINTENANCE_FULL:
        return False
    if normalised == "/join" or normalised.startswith(("/join/", "/api/join/")):
        return False
    return method in ("GET", "HEAD")


def owner_session(store: Store, actor: Any) -> bool:
    """Fails closed: no session, no exemption."""
    if actor is None or actor.session is None:
        return False
    return actor.user.id == users.get_owner_id(store)


class Maintenance:
    def __init__(self, app: ASGIApp, store: Store, settings: Holder) -> None:
        self.app = app
        self.store = store
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        mode = self.settings.get().maintenance
        request = Request(scope)
        if allows(mode, request.method, request.url.path):
            await self.app(scope, receive, send)
            return
        if await run_in_threadpool(owner_session, self.store, getattr(request.state, "actor", None)):
            await self.app(scope, receive, send)
            return
        headers = {"retry-after": str(RETRY_SECONDS)}
        if error_page.wanted(request):
            response = error_page.response(request, 503, headers=headers)
        else:
            response = JSONResponse({"error": "this app is in maintenance mode", "maintenance": mode}, status_code=503, headers=headers)
        await response(scope, receive, send)
