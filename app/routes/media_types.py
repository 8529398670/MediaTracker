"""Media types (sections of the library) and sources (the lists titles were
found on). Shared by the family, editable by anyone signed in."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import actor_from
from app.models import RestoreError, sources, types
from app.models.revision import NotFoundError
from app.routes.helpers import bad_request, conflict, get_store, not_found, restore_refused, run
from app.routes.titles import _body


async def list_types(request: Request) -> Response:
    return JSONResponse(await run(types.list_types, get_store(request)))


async def save_type(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        return JSONResponse(await run(types.save_type, get_store(request), body))
    except ValueError as error:
        return bad_request(str(error))


async def delete_type(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        moved = await run(types.delete_type, get_store(request), request.path_params["type_id"], body.get("reassign_to"), actor_from(request).user.id)
    except NotFoundError as error:
        return not_found(str(error))
    except types.TypeInUseError as error:
        return conflict("type_in_use", count=error.count)
    except types.BuiltinTypeError as error:
        return bad_request(str(error))
    return JSONResponse({"moved": moved})


async def restore_type(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    actor = actor_from(request)
    try:
        return JSONResponse(await run(types.restore_type, get_store(request), request.path_params["type_id"], actor.user.id, actor.is_admin))
    except NotFoundError as error:
        return not_found(str(error))
    except RestoreError as refusal:
        return restore_refused(refusal)


async def list_sources(request: Request) -> Response:
    return JSONResponse(await run(sources.list_sources, get_store(request)))


async def create_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        return JSONResponse(await run(sources.create_source, get_store(request), body, actor_from(request).user.id), status_code=201)
    except ValueError as error:
        return bad_request(str(error))


async def update_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        record, previous = await run(sources.update_source, get_store(request), request.path_params["source_id"], body)
    except NotFoundError as error:
        return not_found(str(error))
    except ValueError as error:
        return bad_request(str(error))
    return JSONResponse({"source": record, "previous": previous})


async def delete_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        await run(sources.delete_source, get_store(request), request.path_params["source_id"], actor_from(request).user.id)
    except NotFoundError as error:
        return not_found(str(error))
    return JSONResponse({"deleted": True})


async def restore_source(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    actor = actor_from(request)
    try:
        return JSONResponse(await run(sources.restore_source, get_store(request), request.path_params["source_id"], actor.user.id, actor.is_admin))
    except NotFoundError as error:
        return not_found(str(error))
    except RestoreError as refusal:
        return restore_refused(refusal)
