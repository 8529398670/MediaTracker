"""A person's playlists: named, numbered lists of titles. Every route takes
?user= (see subject.py), so an admin acting for someone edits theirs.

Item changes answer {playlist, previous_items}; previous_items is what the
undo sends back to /set.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.security import actor_from
from app.models import RestoreError, playlists
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_store, parse_id, restore_refusal, run
from app.routes.subject import subject_from
from app.routes.titles import _body, answer


async def list_playlists(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(playlists.list_playlists, get_store(request), subject))


def create_checked(store: Store, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/playlists, shared with MCP."""
    try:
        return playlists.create_playlist(store, subject_id, body.get("name"), body.get("items"))
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def create_playlist(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, create_checked, get_store(request), subject, body, status=201)


def reorder_checked(store: Store, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/playlists/reorder, shared with MCP."""
    ids = [ident for ident in body.get("ids") or [] if isinstance(ident, int)]
    playlists.reorder_playlists(store, subject_id, ids)
    return {"ok": True}


async def reorder_playlists(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, reorder_checked, get_store(request), subject, body)


def action_checked(store: Store, subject_id: int, actor_id: int, actor_is_admin: bool, raw_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/playlists/{playlist_id}/<action>, shared with MCP."""
    playlist_id = parse_id(raw_id)
    if playlist_id is None:
        raise Refused(404, "no such playlist")
    try:
        if action == "update":
            record, old_name = playlists.rename_playlist(store, subject_id, playlist_id, body.get("name"))
            return {"playlist": record, "previous_name": old_name}
        if action == "delete":
            playlists.delete_playlist(store, subject_id, playlist_id, actor_id)
            return {"deleted": True}
        if action == "restore":
            return {"playlist": playlists.restore_playlist(store, subject_id, playlist_id, actor_id, actor_is_admin)}
        if action == "add":
            record, before = playlists.add_items(store, subject_id, playlist_id, body.get("title_ids"), body.get("position"))
        elif action == "remove":
            record, before = playlists.remove_items(store, subject_id, playlist_id, body.get("title_ids"))
        elif action == "move":
            record, before = playlists.move_item(store, subject_id, playlist_id, body.get("title_id"), body.get("position"))
        else:
            record, before = playlists.set_items(store, subject_id, playlist_id, body.get("items"))
        return {"playlist": record, "previous_items": before}
    except NotFoundError as missing:
        raise Refused(404, str(missing)) from None
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def _call(request: Request, action: str) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    actor = actor_from(request)
    return await answer(request, action_checked, get_store(request), subject, actor.user.id, actor.is_admin, request.path_params["playlist_id"], action, body)


async def update_playlist(request: Request) -> Response:
    return await _call(request, "update")


async def delete_playlist(request: Request) -> Response:
    return await _call(request, "delete")


async def restore_playlist(request: Request) -> Response:
    return await _call(request, "restore")


async def add_items(request: Request) -> Response:
    return await _call(request, "add")


async def remove_items(request: Request) -> Response:
    return await _call(request, "remove")


async def move_item(request: Request) -> Response:
    return await _call(request, "move")


async def set_items(request: Request) -> Response:
    return await _call(request, "set")
