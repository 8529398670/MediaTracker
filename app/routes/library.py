"""The library as one read: every title, the subject's own state for each,
who else in the family has watched or loved what, the types, the family's
names, and IMDb scores -- everything a library screen needs to filter, sort
and draw without asking again.

Scores are joined in here rather than fetched afterwards, so a list sorted
by IMDb never reshuffles itself a second after it appears.

?since=<rev> answers with only what changed after that revision (and
"full": false); a browser polls with it when the tab regains focus.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.media.genres import GENRE_ALIASES
from app.media.normalize import LOOKUP_KINDS, STATUSES
from app.models import library_cache, revision, users
from app.reference import imdb
from app.reference.images import CACHE as IMAGES
from app.routes.helpers import get_store, run
from app.routes.subject import subject_from

STATE_PUBLIC = ("status", "rating", "heart", "note", "watched_at", "rev", "updated_at")


def state_row(state: dict[str, Any]) -> dict[str, Any]:
    return {field: state.get(field) for field in STATE_PUBLIC}


def library_payload(store: Store, subject_id: int, since: int | None) -> dict[str, Any]:
    """Shared with the MCP library tools."""
    snapshot = library_cache.get(store)
    full = since is None or since < revision.purged_rev(store) or since > snapshot.rev
    titles = list(snapshot.titles.values())
    mine = snapshot.states_for(subject_id)
    if not full:
        titles = [title for title in titles if title.get("rev", 0) > since]
        states = {title_id: state_row(state) for title_id, state in mine.items() if state.get("rev", 0) > since}
    else:
        titles = [title for title in titles if title.get("deleted_at") is None or not title.get("merged_into")]
        states = {title_id: state_row(state) for title_id, state in mine.items()}
    return {
        "rev": snapshot.rev,
        "full": full,
        "subject": subject_id,
        "titles": [{**title, "poster": IMAGES.path_for(title.get("poster_url") or "")} for title in titles],
        "states": states,
        "social": snapshot.social,
        "types": snapshot.types,
        "people": [{"id": user.id, "display_name": user.display_name} for user in users.list_users(store) if not user.disabled],
        "scores": imdb.scores_for(title.get("imdb_id") for title in titles),
    }


async def get_library(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    raw = request.query_params.get("since", "")
    since = int(raw) if raw.isdigit() else None
    return JSONResponse(await run(library_payload, get_store(request), subject, since))


async def get_vocab(request: Request) -> Response:
    """The fixed words the client builds menus from: statuses, lookup kinds,
    and the canonical genre names the vocabulary folds onto."""
    canonical = sorted({name for names in GENRE_ALIASES.values() for name in names})
    return JSONResponse({"statuses": list(STATUSES), "lookup_kinds": list(LOOKUP_KINDS), "canonical_genres": canonical})
