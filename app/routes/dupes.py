"""Duplicates: the same work twice under two names. Finding them, merging
them (one undo step for the whole merge), and remembering "these are not the
same" for the whole family."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.security import actor_from
from app.media import dupes, normalize
from app.models import library_cache, merges
from app.models.revision import ConflictError, NotFoundError
from app.routes.helpers import bad_request, conflict, get_store, not_found, run
from app.routes.titles import _body


def groups(store: Store) -> list[dict[str, Any]]:
    snapshot = library_cache.get(store)
    found = dupes.duplicate_groups(snapshot.live_titles(), merges.dismissed_pairs(store))
    return [{**group, "titles": [snapshot.titles[ident] for ident in group["ids"]]} for group in found]


async def list_groups(request: Request) -> Response:
    return JSONResponse({"groups": await run(groups, get_store(request))})


async def dismiss(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    ids = [ident for ident in body.get("ids") or [] if normalize.valid_title_id(ident)]
    if len(ids) < 2:
        return bad_request("two or more titles")
    return JSONResponse({"pairs": await run(merges.dismiss, get_store(request), ids, actor_from(request).user.id)})


async def undismiss(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    await run(merges.undismiss, get_store(request), [str(pair) for pair in body.get("pairs") or []])
    return JSONResponse({"ok": True})


async def merge(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    drop = [ident for ident in body.get("drop_ids") or [] if normalize.valid_title_id(ident)]
    try:
        result = await run(merges.merge, get_store(request), request.path_params["title_id"], drop, actor_from(request).user.id)
    except NotFoundError:
        return not_found("no such title")
    except ValueError as error:
        return bad_request(str(error))
    return JSONResponse(result)


async def undo_merge(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        await run(merges.undo_merge, get_store(request), request.path_params["merge_id"])
    except NotFoundError:
        return not_found("no such merge")
    except ConflictError as error:
        return conflict("changed_elsewhere", current=error.current)
    return JSONResponse({"ok": True})
