"""The page a person sees when a page load fails. Scripts and the app's own
API calls never see it: wanted() keeps them on the plain answers they already
get. Go's twin is server/errorpage.

The server renders it rather than the browser app, for two reasons. The app
needs /api/language to find any words at all, and that call is rate limited,
so it cannot be relied on while answering a 429. And it has nothing to
bootstrap: a broken app can still show this.

The CSP allows no inline styles or scripts, so the page only links the files
the app already serves, which the rate limiter exempts. theme.js applies a
saved dark theme; with none saved the page is light.
"""
from __future__ import annotations

from collections.abc import Mapping
from html import escape

from starlette.requests import Request
from starlette.responses import HTMLResponse

from app.core.language import Language

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>%TITLE%</title>
  <link rel="icon" href="/favicon.ico" />
  <script src="/js/theme.js"></script>
  <link rel="stylesheet" href="/vendor/bootstrap.min.css" />
  <link rel="stylesheet" href="/css/style.css" />
</head>
<body>
  <main class="container py-5 text-center">
    <h1 class="h3">%TITLE%</h1>
    <p class="text-body-secondary">%MESSAGE%</p>%REFERENCE%
    <a class="btn btn-primary" href="/">%HOME%</a>
  </main>
</body>
</html>
"""


def wanted(request: Request) -> bool:
    """Whether this request should get the page: a browser loading a page,
    rather than a script, a fetch from the app, or a stylesheet."""
    if request.method not in ("GET", "HEAD"):
        return False
    path = request.url.path
    if path == "/api" or path.startswith("/api/") or path in ("/mcp", "/metrics"):
        return False
    return "text/html" in request.headers.get("accept", "")


def _section(status: int) -> str:
    """The language.yaml prefix for a status."""
    if status == 404:
        return "not_found"
    if status == 405:
        return "method_not_allowed"
    if status == 429:
        return "rate_limited"
    if status == 503:
        return "maintenance"
    if status >= 500:
        return "server_error"
    return "other"


def render(language: Language, status: int, reference: str = "") -> str:
    """The page for a status. reference is the request id, shown on a 5xx so
    a person has something to quote; empty leaves the line out."""
    name = _section(status)
    reference_line = ""
    if reference and status >= 500:
        text = language.get("error_page.reference").replace("{reference}", reference)
        reference_line = f'\n    <p class="small text-body-secondary">{escape(text)}</p>'
    return (
        TEMPLATE.replace("%TITLE%", escape(language.get(f"error_page.{name}_title")))
        .replace("%MESSAGE%", escape(language.get(f"error_page.{name}_message")))
        .replace("%REFERENCE%", reference_line)
        .replace("%HOME%", escape(language.get("error_page.home")))
    )


def response(request: Request, status: int, reference: str = "", headers: Mapping[str, str] | None = None) -> HTMLResponse:
    """The page as a response. Never cached: the same URL may work next time."""
    body = render(request.app.state.language, status, reference)
    return HTMLResponse(body, status_code=status, headers={**(headers or {}), "cache-control": "no-store"})
