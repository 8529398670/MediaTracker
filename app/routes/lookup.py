"""Turning what someone typed or pasted into titles: one line at a time
(a name, a name and a year, an IMDb id, a link to a dozen sites), each with
its best match, the other candidates, and anything already in the library it
might duplicate. Nothing is written here -- the Add screen sends what the
person picked to POST /api/titles.

Outbound calls cost the providers' goodwill, so each person gets
providers.lookups_per_minute lines a minute.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.security import actor_from
from app.models import library_cache, titles
from app.models.revision import NotFoundError
from app.providers import enrich, fields, net, resolve
from app.routes.helpers import bad_request, error, get_config, get_store, not_found, run
from app.routes.titles import _body, check_dupes

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


async def resolve_lines(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    lines = [str(line).strip() for line in body.get("lines") or [] if str(line).strip()][:MAX_LINES]
    if not lines:
        return bad_request("nothing to look up")
    cfg = get_config(request)
    if not cfg.providers.network:
        return error(503, "lookups_off")
    actor = actor_from(request)
    gate = limiter(cfg.providers.lookups_per_minute)
    if not all(gate.allow(f"user:{actor.user.id}") for _line in lines):
        return error(429, "lookup_rate_limited")
    kind = str(body.get("kind") or "any")
    store = get_store(request)
    results = []
    for line in lines:
        results.append(await run(resolve_line, store, line, kind))
    return JSONResponse({"results": results})


def enrich_one(store: Store, title_id: str, refresh: bool) -> dict[str, Any]:
    title = library_cache.get(store).titles.get(title_id)
    if title is None or title.get("deleted_at") is not None:
        raise NotFoundError()
    previous = enrich.enrich_and_save(store, title, refresh=refresh)
    return {"title": titles.get_title(store, title_id), "previous": previous}


async def enrich_title(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    if not get_config(request).providers.network:
        return error(503, "lookups_off")
    try:
        return JSONResponse(await run(enrich_one, get_store(request), request.path_params["title_id"], bool(body.get("refresh"))))
    except NotFoundError:
        return not_found("no such title")
