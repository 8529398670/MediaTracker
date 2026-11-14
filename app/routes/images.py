"""GET /api/img/<key>: a poster from the cache, fetched once if it is not
there yet. See app/reference/images.py for why the page sends a key and
never a URL."""
from __future__ import annotations

from typing import Annotated

from msgspec import Meta
from starlette.requests import Request
from starlette.responses import Response

from app.apidocs import PATH, route
from app.apidocs import Request as RequestType
from app.models import library_cache
from app.providers import net
from app.reference.images import CACHE, KEY
from app.routes.helpers import Refused, get_store, run

HEADERS = {"cache-control": "private, max-age=31536000, immutable"}


def _register_library(store) -> None:  # type: ignore[no-untyped-def]
    for title in library_cache.get(store).titles.values():
        CACHE.path_for(title.get("poster_url") or "")


class ImageKey(RequestType, kw_only=True):
    key: Annotated[str, PATH, Meta(description="A poster's key, from a title's poster path in GET /api/library.")]


@route(
    "GET /api/img/{key}", summary="A poster",
    tag="Library", errors=(404,), reply_type="image/*",
    description="A title's poster from the server's cache, fetched once if it is not there yet. Answers 304 "
    "to If-None-Match with its key.",
    mcp_http="image bytes",
)
async def get_image(request: Request, body: ImageKey) -> Response:
    key = body.key
    if not KEY.match(key):
        raise Refused(404, "no such image")
    if request.headers.get("if-none-match") == f'"{key}"':
        return Response(status_code=304, headers=HEADERS)
    if CACHE.cached(key) is None and key not in CACHE.known:
        # After a restart the registry is empty until the library is read;
        # a page that kept its HTML asks for posters before that.
        await run(_register_library, get_store(request))
    found = await run(CACHE.fetch, key, net.fetch_bytes)
    if found is None:
        raise Refused(404, "no such image")
    data, kind = found
    return Response(data, media_type=kind, headers={**HEADERS, "etag": f'"{key}"'})
