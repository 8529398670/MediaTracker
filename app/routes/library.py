"""The library as one read: every title, the subject's own state for each,
who else in the family has watched or loved what, the types, the family's
names, and IMDb scores -- everything a library screen needs to filter, sort
and draw without asking again.

Scores are joined in here rather than fetched afterwards, so a list sorted
by IMDb never reshuffles itself a second after it appears.

?since=<rev> answers with only what changed after that revision (and
"full": false); a browser polls with it when the tab regains focus.

GET /api/library/search is the same library filtered on the server, a page
of compact rows: what an agent (search_library over MCP) wants instead.
"""
from __future__ import annotations

from typing import Annotated, Any

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.db import Store
from app.media import genres, normalize
from app.media.normalize import LOOKUP_KINDS, STATUSES
from app.models import library_cache, revision, users
from app.reference import imdb
from app.reference.images import CACHE as IMAGES
from app.routes.helpers import get_store
from app.routes.subject import User, subject_of

TAG = "Library"
STATE_PUBLIC = ("status", "rating", "heart", "note", "watched_at", "rev", "updated_at")
SEARCHABLE = ("title", "creator", "cast", "tags", "notes")


def state_row(state: dict[str, Any]) -> dict[str, Any]:
    return {field: state.get(field) for field in STATE_PUBLIC}


def library_payload(store: Store, subject_id: int, since: int | None) -> dict[str, Any]:
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
        "genre_rules": genres.rules(),
        "people": [{"id": user.id, "display_name": user.display_name} for user in users.list_users(store) if not user.disabled],
        "scores": imdb.scores_for(title.get("imdb_id") for title in titles),
    }


class GetLibrary(RequestType, kw_only=True):
    since: Annotated[Annotated[int, Meta(ge=0)] | None, QUERY, Meta(description="A rev from an earlier answer: only what changed after it.")] = None
    user: User = None


class Library(Reply, kw_only=True):

    rev: Annotated[int, Meta(description="The library's revision: send it back as since.")]
    full: Annotated[bool, Meta(description="false when only what changed since is here.")]
    subject: Annotated[int, Meta(description="Whose states these are.")]
    titles: list[dict[str, Any]]
    states: Annotated[dict[str, dict[str, Any]], Meta(description="The subject's state, by title id.")]
    social: Annotated[dict[str, Any], Meta(description="Who else has watched or loved each title, by title id.")]
    types: list[dict[str, Any]]
    genre_rules: Any
    people: list[dict[str, Any]]
    scores: Annotated[dict[str, Any], Meta(description="IMDb scores, by imdb id.")]


@route(
    "GET /api/library", summary="The whole library",
    tag=TAG,
    description="Every title, the person's own state for each, who else in the family has watched or loved "
    "what, the types, the family's names, and IMDb scores. ?since= answers with only what changed.",
    mcp_http="the whole library for the browser; search_library is the agent's version",
)
def get_library(request: Request, body: GetLibrary) -> Library:
    subject = subject_of(request, body.user)
    return Library(**library_payload(get_store(request), subject, body.since))


def _row(title: dict[str, Any], state: dict[str, Any] | None, social: dict[str, Any] | None) -> dict[str, Any]:
    keep = ("id", "title", "year", "type", "genres", "runtime", "certification", "creator", "tags", "imdb_id", "wiki_url", "notes", "added_at")
    out = {name: title.get(name) for name in keep}
    out["my_state"] = state_row(state) if state else None
    if social:
        out["family"] = {"watched": social["watched"], "loved": social["loved"]}
    return out


class SearchLibrary(RequestType, kw_only=True):
    text: Annotated[str, QUERY, Meta(max_length=200, description="Words that must all appear in the title, director, cast, genres, tags or notes.")] = ""
    type: Annotated[str, QUERY, Meta(description="A type id such as movie or tv.")] = ""
    status: Annotated[str, QUERY, Meta(description="queue, watching, watched, dropped or none, or up_next for the Up next list (queue and watching, newest first).")] = ""
    limit: Annotated[int, QUERY, Meta(ge=1, le=500, description="Rows to return. Default 50.", extra={"error": "limit must be 1-500"})] = 50
    user: User = None


class LibrarySearch(Reply, kw_only=True):
    total: Annotated[int, Meta(description="How many titles matched, before limit.")]
    titles: list[dict[str, Any]]


@route(
    "GET /api/library/search", summary="Search the library",
    tag=TAG,
    description="Titles in the family library, with the person's own state on each (status, rating, heart) "
    "and who else has watched or loved it. Every argument is optional.",
    mcp="search_library", read_only=True,
)
def search_library(request: Request, body: SearchLibrary) -> LibrarySearch:
    subject = subject_of(request, body.user)
    snapshot = library_cache.get(get_store(request))
    states = snapshot.states_for(subject)
    words = normalize.text(body.text, 200).lower().split()
    up_next = body.status == "up_next"
    out = []
    for title in snapshot.live_titles():
        if body.type and title.get("type") != body.type:
            continue
        state = states.get(title["id"])
        mine = (state or {}).get("status") or "none"
        if up_next:
            if mine not in ("queue", "watching"):
                continue
        elif body.status and mine != body.status:
            continue
        hay = " ".join(str(title.get(field) or "") if not isinstance(title.get(field), list) else " ".join(title[field]) for field in SEARCHABLE).lower()
        hay += " " + " ".join(genres.terms(title.get("genres") or [])).lower()
        if words and not all(word in hay for word in words):
            continue
        out.append(_row(title, state, snapshot.social.get(title["id"])))
    if up_next:
        # Newest first, like the Up next screen.
        out.sort(key=lambda row: row.get("added_at") or "", reverse=True)
    return LibrarySearch(total=len(out), titles=out[:body.limit])


class Vocab(Reply, kw_only=True):
    statuses: list[str]
    lookup_kinds: list[str]
    canonical_genres: list[str]


@route(
    "GET /api/vocab", summary="Library vocabulary",
    tag=TAG,
    description="The fixed words: statuses, lookup kinds, and the canonical genre names.",
    mcp="get_vocab", read_only=True,
)
def get_vocab(request: Request) -> Vocab:
    return Vocab(statuses=list(STATUSES), lookup_kinds=list(LOOKUP_KINDS), canonical_genres=list(genres.GENRES))
