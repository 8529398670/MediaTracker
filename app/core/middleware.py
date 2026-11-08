"""The cross-cutting protections that apply to every request no matter which
route answers it. Keeping them here means a route handler never has to
remember a header or a throttle -- if it is served by the app, it is covered.

These are plain ASGI middleware rather than Starlette's BaseHTTPMiddleware:
they only add headers or answer early, which needs no request body handling,
and plain ASGI avoids BaseHTTPMiddleware's known problems with streaming
responses and context variables.

The request body limit is Starlette's own RequestBodyLimitMiddleware (wired in
app/main.py), so it is not repeated here.
"""
from __future__ import annotations

import ipaddress
import posixpath
import sys
import time
from collections import deque
from typing import Mapping, Sequence, Union

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import error_page, logs, request_id
from app.core.config import Config, trusted_proxy_networks
from app.core.config_live import Holder

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# Everything the page needs is same-origin, which is true for this template on
# purpose: libraries are downloaded once and served from static/vendor/ rather
# than pulled from a CDN at runtime. That is what lets the CSP stay this
# tight, and it is why adding a <script src> pointing at some other origin
# will visibly break -- the fix is to vendor the file, not to loosen the
# policy.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


PLAIN_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "permissions-policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-dns-prefetch-control": "off",
    # Every app built from this template is private, and robots.txt only
    # asks: this covers a crawler that reaches a page anyway.
    "x-robots-tag": "noindex, nofollow",
}
# Only claim HTTPS-only when the deployment actually is. Sending HSTS from a
# local http:// run would pin the browser to https for localhost and break
# every other project on that port.
SECURE_HEADERS = dict(PLAIN_HEADERS, **{"strict-transport-security": "max-age=63072000; includeSubDomains"})


class SecurityHeaders:
    """server.secure_cookies decides HSTS and can change while the server
    runs, so the current setting picks a header set per request."""

    def __init__(self, app: ASGIApp, settings: Holder) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        chosen = SECURE_HEADERS if self.settings.get().secure_cookies else PLAIN_HEADERS

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # setdefault, so a route that needs a stricter value (the
                # login page's Referrer-Policy: no-referrer) keeps it.
                for name, value in chosen.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def client_ip(scope: Scope, cfg: Config, trusted: Sequence[IPNetwork]) -> str:
    """The address a request is counted against.

    The socket's peer address, unless server.trust_proxy is on *and* that
    peer is one of server.trusted_proxies. Only then is server.proxy_header
    read -- right to left, skipping addresses that are themselves trusted
    proxies, and stopping at the first one that is not. That is the address
    your outermost trusted proxy saw; anything to its left came from the
    client and can say whatever the client likes. An entry that is not an IP
    address ends the walk at the last trusted hop rather than becoming a
    rate-limit key a client chose.

    Checking the peer is what makes the header safe to read at all: without
    it, any client that reaches the server directly could name its own IP and
    walk past the limiter."""
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if not cfg.trust_proxy or not _is_trusted(peer, trusted):
        return peer
    value = Headers(scope=scope).get(cfg.proxy_header, "")
    hop = peer
    for entry in reversed([entry.strip() for entry in value.split(",") if entry.strip()]):
        try:
            address = str(ipaddress.ip_address(entry))
        except ValueError:
            return hop
        if not _is_trusted(address, trusted):
            return address
        hop = address
    return hop


# server.trusted_proxies parsed, for the Config it was parsed from. The list
# can change while the server runs, so it is worked out per request -- but
# only once per Config, not once per request.
_trusted_cache: tuple[Config | None, list[IPNetwork]] = (None, [])


def trusted_for(cfg: Config) -> list[IPNetwork]:
    global _trusted_cache
    cached_cfg, networks = _trusted_cache
    if cached_cfg is not cfg:
        networks = trusted_proxy_networks(cfg)
        _trusted_cache = (cfg, networks)
    return networks


def _is_trusted(address: str, trusted: Sequence[IPNetwork]) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in trusted)


def static_asset(method: str, path: str) -> bool:
    """A file the page loads (/js/app.js, /vendor/...), as opposed to the page
    itself, an API call, or a login or invite link -- whose credential can
    contain a dot, which is why those are ruled out first."""
    if method not in ("GET", "HEAD"):
        return False
    if path.startswith(("/api/", "/login/", "/join/", "/mcp")):
        return False
    return posixpath.splitext(path)[1] != ""


# The exact POSTs that try a credential. Joining through an invite link counts:
# each of those calls takes a PIN or mints an account.
SIGN_IN_PATHS = frozenset({
    "/api/login",
    "/api/login/two-factor",
    "/api/login/password",
    "/api/join/info",
    "/api/join/match",
    "/api/join/claim",
    "/api/join/create",
})

BUDGET_GENERAL = "general"
BUDGET_SIGN_IN = "sign-in"
# MediaTracker: posters (/api/img/...) get a budget of their own
# (images.rate_limit_max). One library page asks for hundreds at once, and
# counting those against the API budget would refuse the page's own data
# calls. They are cheap reads of files already on disk.
BUDGET_ASSET = "asset"
BUDGET_NONE = "none"


def budget_for(method: str, path: str) -> str:
    """Which limit a request counts against.

    The path is lowercased and loses a trailing slash first. Starlette's own
    routes are exact, so today that changes nothing, but the Go template's
    router ignores both and the two templates should agree; a route added with
    looser matching must not be how a caller skips the sign-in budget.

    Static files are exempt because index.html alone pulls in more than
    twenty, all no-store, so counting them meant about five reloads a minute
    hit a 429. Serving one touches no database and no credential. The page
    itself is not exempt, and neither is anything under /api."""
    normalised = path.lower()
    if len(normalised) > 1:
        normalised = normalised.rstrip("/")
    if method == "POST" and normalised in SIGN_IN_PATHS:
        return BUDGET_SIGN_IN
    if method in ("GET", "HEAD") and normalised.startswith("/api/img/"):
        return BUDGET_ASSET
    if static_asset(method, normalised):
        return BUDGET_NONE
    return BUDGET_GENERAL


class RateLimit:
    """A per-process, in-memory sliding-window limiter, keyed by client IP.
    That is exactly right for the single uvicorn process this template runs.
    Run more than one worker or replica and the counters stop being shared, so
    each would allow the full budget -- move to a shared store at that point
    rather than assuming the limit still holds.

    Each address has three budgets over the same window: one for signing in,
    one for the pieces of an upload, and one for everything else. Keeping them apart means a page full of API calls
    cannot lock someone out of signing in, and guessing at sign-in does not
    get the budget the rest of the app has.

    It runs before the request is authenticated, which is what keeps an
    unauthenticated flood cheap to refuse.

    The budgets, the window and who counts as a proxy are read per request,
    so an edit to server.rate_limit_max, rate_limit_signin_max,
    rate_limit_upload_max, rate_limit_window_seconds or the proxy settings
    applies at once."""

    def __init__(self, app: ASGIApp, settings: Holder) -> None:
        self.app = app
        self.settings = settings
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float, window: float) -> None:
        # Forget clients with nothing inside the window, so the table does not
        # grow forever with every address that ever made one request.
        if now - self._last_sweep < window:
            return
        self._last_sweep = now
        for key in [key for key, hits in self._hits.items() if not hits or now - hits[-1] > window]:
            del self._hits[key]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        budget = budget_for(scope.get("method", ""), scope.get("path", ""))
        if budget == BUDGET_NONE:
            await self.app(scope, receive, send)
            return
        cfg = self.settings.get()
        limits = {BUDGET_SIGN_IN: cfg.rate_limit_signin_max}
        limit = limits.get(budget, cfg.rate_limit_max)
        if budget == BUDGET_ASSET:
            limit = cfg.images.rate_limit_max
        window = float(cfg.rate_limit_window_seconds)
        now = time.monotonic()
        self._sweep(now, window)
        hits = self._hits.setdefault((budget, client_ip(scope, cfg, trusted_for(cfg))), deque())
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            headers = {"retry-after": str(int(window))}
            request = Request(scope)
            response: Response = (
                error_page.response(request, 429, headers=headers)
                if error_page.wanted(request)
                else JSONResponse({"error": "too many requests"}, status_code=429, headers=headers)
            )
            await response(scope, receive, send)
            return
        hits.append(now)
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# error responses
#
# Never hand an internal error message to a client. Every error body has one
# shape, {"error": "..."}, and the detail of a crash goes to the log, where
# the operator can see it (uvicorn prints the traceback). A 5xx body adds
# request_id: the reference a person can quote, which finds the log line.
# ---------------------------------------------------------------------------


def status_text(code: int) -> str:
    if code == 404:
        return "not found"
    if code == 401:
        return "not authenticated"
    if code == 403:
        return "forbidden"
    if code == 405:
        return "method not allowed"
    if code == 413:
        return "request body too large"
    if code == 429:
        return "too many requests"
    if code >= 500:
        return "internal error"
    return "bad request"


def internal_error(request: Request, cause: object, status: int = 500, headers: Mapping[str, str] | None = None) -> Response:
    """The one answer for something going wrong on our side. cause never
    reaches the client: it goes to stdout, and is left on the request for
    RequestLog, so the line the reference finds says what happened.

    It sets X-Request-ID and the security headers itself because
    server_error's response is sent by Starlette's ServerErrorMiddleware,
    outside every middleware in main.build_app, RequestID and SecurityHeaders
    included. Inside them, those set the same values again."""
    reference = request_id.of(request.scope)
    print(
        f"[error] {reference} {request.method} {logs.redact(request.url.path)}: {cause}",
        file=sys.stderr,
        flush=True,
    )
    request.state.error_cause = str(cause)
    security = SECURE_HEADERS if request.app.state.settings.get().secure_cookies else PLAIN_HEADERS
    all_headers = {**security, **(headers or {}), request_id.HEADER: reference}
    if error_page.wanted(request):
        return error_page.response(request, status, reference, all_headers)
    return JSONResponse({"error": "internal error", "request_id": reference}, status_code=status, headers=all_headers)


async def http_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    if exc.status_code >= 500:
        return internal_error(request, exc.detail, exc.status_code, exc.headers)
    if error_page.wanted(request):
        return error_page.response(request, exc.status_code, headers=exc.headers)
    return JSONResponse({"error": status_text(exc.status_code)}, status_code=exc.status_code, headers=exc.headers)


async def server_error(request: Request, exc: Exception) -> Response:
    return internal_error(request, repr(exc))


EXCEPTION_HANDLERS = {HTTPException: http_error, 500: server_error}
