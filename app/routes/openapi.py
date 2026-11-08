"""Hands out config/openapi.json. It is written by hand, so it can say what a
route takes and returns; app/tests/test_openapi.py fails when it and the route
table disagree. Signed-in callers only: it maps the admin surface, and nobody
who cannot sign in has a use for it."""
from __future__ import annotations

from functools import cache

from starlette.requests import Request
from starlette.responses import Response

from app.core import assets


@cache
def spec() -> bytes:
    return assets.OPENAPI_SPEC.read_bytes()


async def get_openapi(request: Request) -> Response:
    return Response(spec(), media_type="application/json")
