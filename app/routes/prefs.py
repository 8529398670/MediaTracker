"""Per-person settings (card layout, last query per screen) and saved
views. Both take ?user= so an admin acting for someone sees their setup."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.security import actor_from
from app.models import RestoreError, prefs, views
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_store, parse_id, restore_refusal, run
from app.routes.subject import subject_from
from app.routes.titles import _body, answer


async def get_prefs(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(prefs.get_prefs, get_store(request), subject))


def save_prefs_checked(store: Store, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/prefs, shared with MCP."""
    changes = {section: body[section] for section in prefs.SECTIONS if section in body}
    try:
        return prefs.save_prefs(store, subject_id, changes)
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def save_prefs(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, save_prefs_checked, get_store(request), subject, body)


async def list_views(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(views.list_views, get_store(request), subject))


def create_view_checked(store: Store, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/views, shared with MCP."""
    try:
        return views.create_view(store, subject_id, body)
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def create_view(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, create_view_checked, get_store(request), subject, body, status=201)


def view_action_checked(store: Store, subject_id: int, actor_id: int, actor_is_admin: bool, raw_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/views/{view_id}/update|delete|restore, shared with MCP."""
    view_id = parse_id(raw_id)
    if view_id is None:
        raise Refused(404, "no such view")
    try:
        if action == "update":
            record, previous = views.update_view(store, subject_id, view_id, body)
            return {"view": record, "previous": previous}
        if action == "delete":
            views.delete_view(store, subject_id, view_id, actor_id)
            return {"deleted": True}
        return {"view": views.restore_view(store, subject_id, view_id, actor_id, actor_is_admin)}
    except NotFoundError:
        raise Refused(404, "no such view") from None
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def _view_call(request: Request, action: str) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    actor = actor_from(request)
    return await answer(request, view_action_checked, get_store(request), subject, actor.user.id, actor.is_admin, request.path_params["view_id"], action, body)


async def update_view(request: Request) -> Response:
    return await _view_call(request, "update")


async def delete_view(request: Request) -> Response:
    return await _view_call(request, "delete")


async def restore_view(request: Request) -> Response:
    return await _view_call(request, "restore")


def reorder_views_checked(store: Store, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/views/reorder, shared with MCP."""
    ids = [ident for ident in body.get("ids") or [] if isinstance(ident, int)]
    views.reorder_views(store, subject_id, ids)
    return {"ok": True}


async def reorder_views(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, reorder_views_checked, get_store(request), subject, body)
