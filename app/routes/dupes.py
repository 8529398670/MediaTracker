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
from app.routes.helpers import Refused, get_store, run
from app.routes.titles import _body, answer


def groups(store: Store) -> list[dict[str, Any]]:
    snapshot = library_cache.get(store)
    found = dupes.duplicate_groups(snapshot.live_titles(), merges.dismissed_pairs(store))
    return [{**group, "titles": [snapshot.titles[ident] for ident in group["ids"]]} for group in found]


async def list_groups(request: Request) -> Response:
    return JSONResponse({"groups": await run(groups, get_store(request))})


def dismiss_checked(store: Store, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/dupes/dismiss, shared with MCP."""
    ids = [ident for ident in body.get("ids") or [] if normalize.valid_title_id(ident)]
    if len(ids) < 2:
        raise Refused(400, "two or more titles")
    return {"pairs": merges.dismiss(store, ids, actor_id)}


async def dismiss(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, dismiss_checked, get_store(request), body, actor_from(request).user.id)


def undismiss_checked(store: Store, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/dupes/undismiss, shared with MCP."""
    merges.undismiss(store, [str(pair) for pair in body.get("pairs") or []])
    return {"ok": True}


async def undismiss(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, undismiss_checked, get_store(request), body)


def merge_checked(store: Store, keep_id: str, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/titles/{title_id}/merge, shared with MCP."""
    drop = [ident for ident in body.get("drop_ids") or [] if normalize.valid_title_id(ident)]
    try:
        return merges.merge(store, keep_id, drop, actor_id)
    except NotFoundError:
        raise Refused(404, "no such title") from None
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def merge(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, merge_checked, get_store(request), request.path_params["title_id"], body, actor_from(request).user.id)


def undo_merge_checked(store: Store, merge_id: str) -> dict[str, Any]:
    """POST /api/merges/{merge_id}/undo, shared with MCP."""
    try:
        merges.undo_merge(store, merge_id)
    except NotFoundError:
        raise Refused(404, "no such merge") from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    return {"ok": True}


async def undo_merge(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, undo_merge_checked, get_store(request), request.path_params["merge_id"])
