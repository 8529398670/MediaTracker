"""One person's state for titles: status, rating, heart, note.

Every route here takes ?user=<id>; see subject.py. An admin acting for
someone changes *their* state, and the record notes the admin did it.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import actor_from
from app.media import normalize
from app.models import user_state
from app.models.revision import ConflictError, NotFoundError
from app.routes.helpers import bad_request, conflict, get_store, not_found, run
from app.routes.library import state_row
from app.routes.subject import subject_from
from app.routes.titles import MAX_BULK, _body


async def set_one(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    changes = normalize.clean_state_fields(body.get("set") or {})
    if not changes:
        return bad_request("nothing to change")
    try:
        state, previous = await run(
            user_state.set_state, get_store(request), subject, request.path_params["title_id"], changes, body.get("expect"), actor_from(request).user.id
        )
    except NotFoundError:
        return not_found("no such title")
    except ConflictError as error:
        return conflict("changed_elsewhere", current=error.current)
    return JSONResponse({"state": state_row(state), "previous": previous})


async def set_many(request: Request) -> Response:
    """{changes: {title id: {field: value}}} -- a bulk action sends the same
    change for every id; its undo sends each title's own previous values."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    raw = body.get("changes")
    if not isinstance(raw, dict) or not raw:
        return bad_request("no changes given")
    changes = {
        title_id: normalize.clean_state_fields(fields)
        for title_id, fields in list(raw.items())[:MAX_BULK]
        if normalize.valid_title_id(title_id)
    }
    previous = await run(user_state.set_many, get_store(request), subject, {k: v for k, v in changes.items() if v}, actor_from(request).user.id)
    return JSONResponse({"previous": previous})
