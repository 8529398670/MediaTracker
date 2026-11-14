"""The MCP routes: /mcp itself (app/mcp/protocol.py speaks it) and
/api/mcp.json, the MCP reference: every tool /mcp has, its arguments, the
route it stands for, and the routes that stay HTTP only. scripts/api_docs.sh
writes the reference from the registered tools (app/mcp/manifest.py), and
app/tests/test_api_docs.py fails while it is out of date. Signed-in callers
only, like openapi.json."""
from __future__ import annotations

from functools import cache
from typing import Any, ClassVar

from starlette.requests import Request
from starlette.responses import Response

from app.apidocs import KEY_ONLY, PUBLIC, Reply, route
from app.core import assets
from app.mcp.protocol import Server
from app.routes.helpers import not_found


@cache
def manifest() -> bytes | None:
    try:
        return assets.MCP_MANIFEST.read_bytes()
    except FileNotFoundError:
        return None


@route(
    "GET /api/mcp.json", summary="The MCP tools: every tool /mcp has, its arguments, and the route it stands for",
    tag="Monitoring", feature="mcp",
    mcp_http="The MCP reference itself; tools/list gives the same list.",
)
async def get_mcp_manifest(request: Request) -> dict[str, Any]:
    raw = manifest()
    if raw is None:
        return not_found("not found")  # type: ignore[return-value]
    return Response(raw, media_type="application/json")  # type: ignore[return-value]


@cache
def server() -> Server:
    """The one /mcp server. Its tools are fixed at startup, and every route
    table built shares them."""
    from app.routes.mcp_tools import build_registry

    return Server(build_registry())


class JSONRPCRequest(Reply):
    """What POST /mcp takes. protocol.Server reads and checks the message
    itself, as JSON-RPC says, so this only documents it."""

    api_doc: ClassVar[str] = "A JSON-RPC 2.0 request."


@route(
    "POST /mcp", summary="Model Context Protocol, at the key's role",
    tag="Monitoring", access=KEY_ONLY, feature="mcp", errors=(400,), raw_body=JSONRPCRequest,
    mcp_http="The MCP endpoint itself.",
)
async def mcp_endpoint(request: Request) -> dict[str, Any]:
    return await server().endpoint(request)  # type: ignore[return-value]


@route(
    "GET /mcp", summary="Refused: this server has no stream",
    tag="Monitoring", access=PUBLIC, feature="mcp", status=405,
)
async def mcp_no_stream(request: Request) -> None:
    """GET /mcp: how a client asks for a server-to-client SSE stream."""
    return await server().method_not_allowed(request)  # type: ignore[return-value]


@route(
    "DELETE /mcp", summary="Refused: this server keeps no sessions",
    tag="Monitoring", access=PUBLIC, feature="mcp", status=405,
)
async def mcp_no_sessions(request: Request) -> None:
    """DELETE /mcp: how a client ends a session."""
    return await server().method_not_allowed(request)  # type: ignore[return-value]
