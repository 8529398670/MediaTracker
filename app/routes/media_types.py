"""Media types (sections of the library) and sources (the lists titles were
found on). Shared by the family, editable by anyone signed in."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.security import actor_from
from app.models import RestoreError, sources, types
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_store, restore_refusal, run
from app.routes.titles import _body, answer


async def list_types(request: Request) -> Response:
    return JSONResponse(await run(types.list_types, get_store(request)))


def save_type_checked(store: Store, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/types, shared with MCP."""
    try:
        return types.save_type(store, body)
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def save_type(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, save_type_checked, get_store(request), body)


def delete_type_checked(store: Store, type_id: str, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/types/{type_id}/delete, shared with MCP."""
    try:
        moved = types.delete_type(store, type_id, body.get("reassign_to"), actor_id)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except types.TypeInUseError as error:
        raise Refused(409, "type_in_use", count=error.count) from None
    except types.BuiltinTypeError as error:
        raise Refused(400, str(error)) from None
    return {"moved": moved}


async def delete_type(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, delete_type_checked, get_store(request), request.path_params["type_id"], body, actor_from(request).user.id)


def restore_type_checked(store: Store, type_id: str, actor_id: int, actor_is_admin: bool) -> dict[str, Any]:
    """POST /api/types/{type_id}/restore, shared with MCP."""
    try:
        return types.restore_type(store, type_id, actor_id, actor_is_admin)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None


async def restore_type(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    actor = actor_from(request)
    return await answer(request, restore_type_checked, get_store(request), request.path_params["type_id"], actor.user.id, actor.is_admin)


async def list_sources(request: Request) -> Response:
    return JSONResponse(await run(sources.list_sources, get_store(request)))


def create_source_checked(store: Store, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/sources, shared with MCP."""
    try:
        return sources.create_source(store, body, actor_id)
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def create_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, create_source_checked, get_store(request), body, actor_from(request).user.id, status=201)


def update_source_checked(store: Store, source_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/sources/{source_id}/update, shared with MCP."""
    try:
        record, previous = sources.update_source(store, source_id, body)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except ValueError as error:
        raise Refused(400, str(error)) from None
    return {"source": record, "previous": previous}


async def update_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, update_source_checked, get_store(request), request.path_params["source_id"], body)


def delete_source_checked(store: Store, source_id: str, actor_id: int) -> dict[str, Any]:
    """POST /api/sources/{source_id}/delete, shared with MCP."""
    try:
        sources.delete_source(store, source_id, actor_id)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    return {"deleted": True}


async def delete_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, delete_source_checked, get_store(request), request.path_params["source_id"], actor_from(request).user.id)


def restore_source_checked(store: Store, source_id: str, actor_id: int, actor_is_admin: bool) -> dict[str, Any]:
    """POST /api/sources/{source_id}/restore, shared with MCP."""
    try:
        return sources.restore_source(store, source_id, actor_id, actor_is_admin)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None


async def restore_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    actor = actor_from(request)
    return await answer(request, restore_source_checked, get_store(request), request.path_params["source_id"], actor.user.id, actor.is_admin)
