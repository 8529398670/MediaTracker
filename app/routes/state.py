"""One person's state for titles: status, rating, heart, note.

Every route here takes ?user=<id>; see subject.py. An admin acting for
someone changes *their* state, and the record notes the admin did it.
"""
from __future__ import annotations

from typing import Annotated

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import Reply, route
from app.apidocs import Request as RequestType
from app.core.security import actor_from
from app.media import normalize
from app.models import user_state
from app.models.revision import ConflictError, NotFoundError
from app.routes.helpers import Refused, get_store
from app.routes.library import state_row
from app.routes.subject import User, subject_of
from app.routes.titles import MAX_BULK, TAG, Expect, Record, StateFields, TitlePath


class SetState(TitlePath, kw_only=True):
    set: StateFields
    expect: Expect = None
    user: User = None


class StateChange(Reply, kw_only=True):
    state: Record
    previous: Annotated[Record, Meta(description="What the changed fields were before: send them back to undo.")]


@route(
    "POST /api/state/{title_id}", summary="Set status, rating or heart",
    tag=TAG, errors=(404, 409),
    description="Change one person's state on a title: status (queue, watching, watched, dropped, or null for "
    "off the list), rating 1-10 or null, heart true/false, note, watched_at. Returns the previous values.",
    mcp="set_state",
)
def set_one(request: Request, body: SetState) -> StateChange:
    subject = subject_of(request, body.user)
    changes = normalize.clean_state_fields(body.set)
    if not changes:
        raise Refused(400, "nothing to change")
    try:
        state, previous = user_state.set_state(get_store(request), subject, body.title_id, changes, body.expect, actor_from(request).user.id)
    except NotFoundError:
        raise Refused(404, "no such title") from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    return StateChange(state=state_row(state), previous=previous)


class SetStates(RequestType, kw_only=True):
    changes: Annotated[dict[str, StateFields], Meta(description="{title id: {status, rating, heart, note, watched_at}}, up to 2000 titles.")]
    user: User = None


class StatesChange(Reply, kw_only=True):
    previous: Annotated[Record, Meta(description="Each title's previous values, by id: sent back, the undo.")]


@route(
    "POST /api/state/bulk", summary="Set state on many titles",
    tag=TAG,
    description="changes is {title id: {status, rating, heart, note, watched_at}}, up to 2000 titles: a bulk "
    "action sends the same change for every id. Returns each title's previous values, which sent back are "
    "the undo.",
    mcp="set_states",
)
def set_many(request: Request, body: SetStates) -> StatesChange:
    subject = subject_of(request, body.user)
    if not body.changes:
        raise Refused(400, "no changes given")
    changes = {
        title_id: normalize.clean_state_fields(fields)
        for title_id, fields in list(body.changes.items())[:MAX_BULK]
        if normalize.valid_title_id(title_id)
    }
    return StatesChange(previous=user_state.set_many(get_store(request), subject, {k: v for k, v in changes.items() if v}, actor_from(request).user.id))
