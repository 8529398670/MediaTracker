"""Turning what someone typed or pasted into titles: one line at a time
(a name, a name and a year, an IMDb id, a link to a dozen sites), each with
its best match, the other candidates, and anything already in the library it
might duplicate. Nothing is written here -- the Add screen sends what the
person picked to POST /api/titles.

Outbound calls cost the providers' goodwill, so each person gets
providers.lookups_per_minute lines a minute.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import Reply, route
from app.apidocs import Request as RequestType
from app.core.config import Config
from app.core.db import Store
from app.core.security import actor_from
from app.mcp.registry import Call
from app.models import library_cache, titles
from app.models.revision import NotFoundError
from app.providers import enrich, fields, net, resolve
from app.routes.helpers import Refused, get_config, get_store
from app.routes.titles import TAG, Record, TitlePath, check_dupes

MAX_LINES = 25
_limiter: net.RateLimiter | None = None


def limiter(per_minute: int) -> net.RateLimiter:
    global _limiter
    if _limiter is None or _limiter.allowance != per_minute:
        _limiter = net.RateLimiter(per_minute, 60.0)
    return _limiter


def resolve_line(store: Store, line: str, kind: str) -> dict[str, Any]:
    """Shared with the MCP lookup tool."""
    found = resolve.resolve(line, kind)
    candidates = [fields.candidate(row) for row in found.get("candidates") or []][:8]
    best = candidates[0] if candidates else None
    dupes = check_dupes(store, best["fields"]) if best else []
    return {
        "input": found.get("input", line),
        "query": found.get("query", ""),
        "year": found.get("year"),
        "via": found.get("via", ""),
        "note": found.get("note", ""),
        "confident": bool(found.get("confident")),
        "candidates": candidates,
        "dupes": dupes,
    }


def compact_results(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of the lookup tool: each line's answer without the provider
    detail an agent does not need."""
    return {"results": [
        {
            "input": result["input"],
            "confident": result["confident"],
            "note": result["note"],
            "candidates": [candidate["fields"] for candidate in result["candidates"]],
            "already_in_library": [{"id": dupe["id"], "title": dupe["title"]["title"], "score": dupe["score"]} for dupe in result["dupes"]],
        }
        for result in serve(call.request, body).results
    ]}


class Resolve(RequestType, kw_only=True):
    lines: Annotated[list[str], Meta(description="Up to 25 lines, each a name, a name and year, an IMDb id, or a link (IMDb, Wikipedia, TMDB, TVmaze...).")]
    kind: Annotated[str, Meta(description="movie, tv, book, ... or any.")] = "any"


class Resolved(Reply, kw_only=True):
    results: Annotated[list[Record], Meta(description="One per line: the best candidates, whether the match is confident, and library titles it may duplicate.")]


@route(
    "POST /api/resolve", summary="Look titles up",
    tag=TAG, errors=(429, 503),
    description="Identify names, names and years, or links with the configured providers, and say whether "
    "the library already has each. Writes nothing. Counts against the per-person lookup allowance "
    "(providers.lookups_per_minute); 503 lookups_off while the network is off.",
    mcp="lookup", read_only=True, call=compact_results,
)
def resolve_lines(request: Request, body: Resolve) -> Resolved:
    cfg = get_config(request)
    lines = [line.strip() for line in body.lines if line.strip()][:MAX_LINES]
    if not lines:
        raise Refused(400, "nothing to look up")
    if not cfg.providers.network:
        raise Refused(503, "lookups_off")
    gate = limiter(cfg.providers.lookups_per_minute)
    actor_id = actor_from(request).user.id
    if not all(gate.allow(f"user:{actor_id}") for _line in lines):
        raise Refused(429, "lookup_rate_limited")
    store = get_store(request)
    return Resolved(results=[resolve_line(store, line, body.kind or "any") for line in lines])


def enrich_one(store: Store, title_id: str, refresh: bool) -> dict[str, Any]:
    title = library_cache.get(store).titles.get(title_id)
    if title is None or title.get("deleted_at") is not None:
        raise NotFoundError()
    previous = enrich.enrich_and_save(store, title, refresh=refresh)
    return {"title": titles.get_title(store, title_id), "previous": previous}


class Enrich(TitlePath, kw_only=True):
    refresh: Annotated[bool, Meta(description="Overwrite what is there, not just fill in what is missing.")] = False


class Enriched(Reply, kw_only=True):
    title: Record
    previous: Annotated[Record, Meta(description="What the changed fields were before.")]


@route(
    "POST /api/titles/{title_id}/enrich", summary="Fill a title in",
    tag=TAG, errors=(404, 503),
    description="Look the title up with the configured providers now and fill in missing details (refresh: "
    "true overwrites what is there). Returns the previous values.",
    mcp="enrich_title",
)
def enrich_title(request: Request, body: Enrich) -> Enriched:
    if not get_config(request).providers.network:
        raise Refused(503, "lookups_off")
    try:
        return Enriched(**enrich_one(get_store(request), body.title_id, body.refresh))
    except NotFoundError:
        raise Refused(404, "no such title") from None
