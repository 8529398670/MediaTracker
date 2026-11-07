"""Per-person settings (card layout, last query per screen) and saved
views. Both take ?user= so an admin acting for someone sees their setup."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import actor_from
from app.models import RestoreError, prefs, views
from app.models.revision import NotFoundError
from app.routes.helpers import bad_request, get_store, not_found, parse_id, restore_refused, run
from app.routes.subject import subject_from
from app.routes.titles import _body


async def get_prefs(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(prefs.get_prefs, get_store(request), subject))


async def save_prefs(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    changes = {section: body[section] for section in prefs.SECTIONS if section in body}
    try:
        return JSONResponse(await run(prefs.save_prefs, get_store(request), subject, changes))
    except ValueError as error:
        return bad_request(str(error))


async def list_views(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(views.list_views, get_store(request), subject))


async def create_view(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    try:
        return JSONResponse(await run(views.create_view, get_store(request), subject, body), status_code=201)
    except ValueError as error:
        return bad_request(str(error))


async def _view_call(request: Request, action: str) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    view_id = parse_id(request.path_params["view_id"])
    if view_id is None:
        return not_found("no such view")
    actor = actor_from(request)
    store = get_store(request)
    try:
        if action == "update":
            record, previous = await run(views.update_view, store, subject, view_id, body)
            return JSONResponse({"view": record, "previous": previous})
        if action == "delete":
            await run(views.delete_view, store, subject, view_id, actor.user.id)
            return JSONResponse({"deleted": True})
        record = await run(views.restore_view, store, subject, view_id, actor.user.id, actor.is_admin)
        return JSONResponse({"view": record})
    except NotFoundError:
        return not_found("no such view")
    except RestoreError as refusal:
        return restore_refused(refusal)
    except ValueError as error:
        return bad_request(str(error))


async def update_view(request: Request) -> Response:
    return await _view_call(request, "update")


async def delete_view(request: Request) -> Response:
    return await _view_call(request, "delete")


async def restore_view(request: Request) -> Response:
    return await _view_call(request, "restore")


async def reorder_views(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    ids = [ident for ident in body.get("ids") or [] if isinstance(ident, int)]
    await run(views.reorder_views, get_store(request), subject, ids)
    return JSONResponse({"ok": True})
