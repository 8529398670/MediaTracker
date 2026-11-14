"""Whose library state a request is about.

Status, rating, heart, playlists, prefs, saved views and Discover verdicts
are per person. Normally that person is whoever is asking. An admin -- or anyone an
admin has given the "Can use Showing" grant (users.may_act_for_others) -- may
add ?user=<id> to read or change someone else's -- the "Acting for Mom" picker --
which the family asked for so one person can keep the household's lists
tidy. Anyone else naming another user gets 403; records still say who
actually made the change (updated_by is always the actor).

A personal route's request has a `user` field (the User type below): the
?user= of the URL, and the same argument to its MCP tool.
"""
from __future__ import annotations

from typing import Annotated, Any

import msgspec
from msgspec import UNSET, Meta
from starlette.requests import Request

from app.apidocs import QUERY
from app.core.security import actor_from
from app.models import users
from app.routes.helpers import Refused, get_store

User = Annotated[
    Annotated[int, Meta(ge=1)] | None, QUERY,
    Meta(description="Whose lists: a user id, for an admin or someone given Showing. Default: your own.", extra={"error": "no such user"}),
]


def subject_of(request: Request, wanted: int | None) -> int:
    """The user id this request acts for, or Refused. Reads SQLite: from a
    worker thread (every plain-function handler runs in one)."""
    actor = actor_from(request)
    store = get_store(request)
    locked = users.locked_subject(actor.user)
    if locked is not None:
        # An admin has fixed whose lists this account sees. No ?user= means
        # that person, so an old tab cannot write to the wrong lists; naming
        # anyone else is refused. If that person's account is gone, it falls
        # back to its own.
        if locked != actor.user.id and users.get_user(store, locked) is None:
            locked = actor.user.id
        if wanted is not None and wanted != locked:
            raise Refused(403, "an admin has set whose lists you see")
        return locked
    if wanted is None or wanted == actor.user.id:
        return actor.user.id
    if not (actor.is_admin or actor.user.can_show_others):
        raise Refused(403, "only an admin, or someone given Showing, can act for someone else")
    if users.get_user(store, wanted) is None:
        raise Refused(404, "no such user")
    return wanted


def given(body: Any, *drop: str) -> dict[str, Any]:
    """A request's body fields that were sent, as the dict the models take:
    fields left out (UNSET), `user` and the names in drop are not in it."""
    return {
        name: value
        for name, value in msgspec.structs.asdict(body).items()
        if value is not UNSET and name not in ("user", *drop)
    }
