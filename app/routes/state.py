"""One person's state for titles: status, rating, heart, note.

Every route here takes ?user=<id>; see subject.py. An admin acting for
someone changes *their* state, and the record notes the admin did it.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.core.db import Store
from app.core.security import actor_from
from app.media import normalize
from app.models import user_state
from app.models.revision import ConflictError, NotFoundError
from app.routes.helpers import Refused, get_store
from app.routes.library import state_row
from app.routes.subject import subject_from
from app.routes.titles import MAX_BULK, _body, answer


def set_one_checked(store: Store, subject_id: int, title_id: str, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/state/{title_id}, shared with MCP."""
    changes = normalize.clean_state_fields(body.get("set") or {})
    if not changes:
        raise Refused(400, "nothing to change")
    try:
        state, previous = user_state.set_state(store, subject_id, title_id, changes, body.get("expect"), actor_id)
    except NotFoundError:
        raise Refused(404, "no such title") from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    return {"state": state_row(state), "previous": previous}


async def set_one(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, set_one_checked, get_store(request), subject, request.path_params["title_id"], body, actor_from(request).user.id)


def set_many_checked(store: Store, subject_id: int, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/state/bulk, shared with MCP."""
    raw = body.get("changes")
    if not isinstance(raw, dict) or not raw:
        raise Refused(400, "no changes given")
    changes = {
        title_id: normalize.clean_state_fields(fields)
        for title_id, fields in list(raw.items())[:MAX_BULK]
        if normalize.valid_title_id(title_id)
    }
    return {"previous": user_state.set_many(store, subject_id, {k: v for k, v in changes.items() if v}, actor_id)}


async def set_many(request: Request) -> Response:
    """{changes: {title id: {field: value}}} -- a bulk action sends the same
    change for every id; its undo sends each title's own previous values."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, set_many_checked, get_store(request), subject, body, actor_from(request).user.id)
