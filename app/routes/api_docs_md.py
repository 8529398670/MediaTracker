"""The readable references: config/api.md and config/mcp.md, the same as
api.json and mcp.json but as tables for people. With app.repo set, the cards
on Account link to the repository's own rendering of them; without it, to
this server's /docs/api and /docs/mcp pages (static/docs.html,
StaticServer.serve_docs_page), which fetch the Markdown from the routes below
and render it. Signed-in callers only, like api.json."""
from __future__ import annotations

from functools import cache
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

from app.apidocs import route
from app.core import assets
from app.core.config import Config, repo_file
from app.routes.helpers import not_found


@cache
def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _markdown(path: Path) -> Response:
    body = _read(path)
    if not body:
        return not_found("not found")
    return Response(body, media_type="text/markdown; charset=utf-8")


@route(
    "GET /api/api.md", summary="The API reference as Markdown tables for people",
    tag="Monitoring", feature="openapi", errors=(404,), reply_type="text/markdown",
    mcp_http="The API reference itself, for people; GET /api/api.json is the same as JSON.",
)
async def get_api_doc(request: Request) -> Response:
    return _markdown(assets.API_DOC)


def api_doc_url(cfg: Config) -> str:
    """Where the readable API reference is read: config/api.md in app.repo
    when that is set, so the repository's site renders it, else this
    server's own page."""
    return repo_file(cfg, "config/api.md") or "/docs/api"


@route(
    "GET /api/mcp.md", summary="The MCP tools as Markdown tables for people",
    tag="Monitoring", feature="mcp", errors=(404,), reply_type="text/markdown",
    mcp_http="The MCP reference itself, for people; tools/list gives the same list.",
)
async def get_mcp_doc(request: Request) -> Response:
    return _markdown(assets.MCP_DOC)


def mcp_doc_url(cfg: Config) -> str:
    """The same as api_doc_url, for config/mcp.md."""
    return repo_file(cfg, "config/mcp.md") or "/docs/mcp"


