"""Whose library state a request is about.

Status, rating, heart, playlists, prefs, saved views and Discover verdicts
are per person. Normally that person is whoever is asking. An admin may add
?user=<id> to read or change someone else's -- the "Acting for Mom" picker --
which the family asked for so one person can keep the household's lists
tidy. Anyone else naming another user gets 403; records still say who
actually made the change (updated_by is always the actor).
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from app.core.security import actor_from
from app.models import users
from app.routes.helpers import forbidden, get_store, not_found, parse_id, run


async def subject_from(request: Request) -> int | Response:
    """The user id this request acts for, or the refusal to send back."""
    actor = actor_from(request)
    raw = request.query_params.get("user", "")
    if raw == "" or raw == str(actor.user.id):
        return actor.user.id
    wanted = parse_id(raw)
    if wanted is None:
        return not_found("no such user")
    if not actor.is_admin:
        return forbidden("only an admin can act for someone else")
    user = await run(users.get_user, get_store(request), wanted)
    if user is None:
        return not_found("no such user")
    return user.id
