"""A person's playlists: named, numbered lists of titles. Every route takes
?user= (see subject.py), so an admin acting for someone edits theirs.

Item changes answer {playlist, previous_items}; previous_items is what the
undo sends back to /set.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import actor_from
from app.models import RestoreError, playlists
from app.models.revision import NotFoundError
from app.routes.helpers import bad_request, get_store, not_found, parse_id, restore_refused, run
from app.routes.subject import subject_from
from app.routes.titles import _body


async def list_playlists(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(playlists.list_playlists, get_store(request), subject))


async def create_playlist(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    try:
        return JSONResponse(await run(playlists.create_playlist, get_store(request), subject, body.get("name"), body.get("items")), status_code=201)
    except ValueError as error:
        return bad_request(str(error))


async def reorder_playlists(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    ids = [ident for ident in body.get("ids") or [] if isinstance(ident, int)]
    await run(playlists.reorder_playlists, get_store(request), subject, ids)
    return JSONResponse({"ok": True})


async def _call(request: Request, action: str) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    playlist_id = parse_id(request.path_params["playlist_id"])
    if playlist_id is None:
        return not_found("no such playlist")
    actor = actor_from(request)
    store = get_store(request)
    try:
        if action == "update":
            record, old_name = await run(playlists.rename_playlist, store, subject, playlist_id, body.get("name"))
            return JSONResponse({"playlist": record, "previous_name": old_name})
        if action == "delete":
            await run(playlists.delete_playlist, store, subject, playlist_id, actor.user.id)
            return JSONResponse({"deleted": True})
        if action == "restore":
            record = await run(playlists.restore_playlist, store, subject, playlist_id, actor.user.id, actor.is_admin)
            return JSONResponse({"playlist": record})
        if action == "add":
            record, before = await run(playlists.add_items, store, subject, playlist_id, body.get("title_ids"), body.get("position"))
        elif action == "remove":
            record, before = await run(playlists.remove_items, store, subject, playlist_id, body.get("title_ids"))
        elif action == "move":
            record, before = await run(playlists.move_item, store, subject, playlist_id, body.get("title_id"), body.get("position"))
        else:
            record, before = await run(playlists.set_items, store, subject, playlist_id, body.get("items"))
        return JSONResponse({"playlist": record, "previous_items": before})
    except NotFoundError as missing:
        return not_found(str(missing))
    except RestoreError as refusal:
        return restore_refused(refusal)
    except ValueError as error:
        return bad_request(str(error))


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
