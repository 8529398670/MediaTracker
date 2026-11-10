"""Hands out config/mcp.json: every tool /mcp has, its arguments, the route it
stands for, and the routes that stay HTTP only. scripts/mcp_json.sh writes it
from the registered tools (app/mcp/manifest.py), and
app/tests/test_mcp_parity.py fails while it is out of date. Signed-in callers
only, like openapi.json."""
from __future__ import annotations

from functools import cache

from starlette.requests import Request
from starlette.responses import Response

from app.core import assets
from app.routes.helpers import not_found


@cache
def manifest() -> bytes | None:
    try:
        return assets.MCP_MANIFEST.read_bytes()
    except FileNotFoundError:
        return None


async def get_mcp_manifest(request: Request) -> Response:
    raw = manifest()
    if raw is None:
        return not_found("not found")
    return Response(raw, media_type="application/json")
