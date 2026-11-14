"""Hands out config/openapi.json, which scripts/api_docs.sh writes from the
routes as each handler declares them (@route, see app/apidocs);
app/tests/test_api_docs.py fails while it is out of date. Signed-in callers
only: it maps the admin surface, and nobody who cannot sign in has a use for
it."""
from __future__ import annotations

from functools import cache
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.apidocs import route
from app.core import assets


@cache
def spec() -> bytes:
    return assets.OPENAPI_SPEC.read_bytes()


@route(
    "GET /api/openapi.json", summary="This document",
    tag="Monitoring", feature="openapi", errors=(404,),
    mcp_http="The API reference itself; GET /api/mcp.json is the MCP one.",
)
async def get_openapi(request: Request) -> dict[str, Any]:
    return Response(spec(), media_type="application/json")  # type: ignore[return-value]
