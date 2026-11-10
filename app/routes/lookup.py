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
from starlette.responses import Response

from app.core.config import Config
from app.core.db import Store
from app.core.security import actor_from
from app.models import library_cache, titles
from app.models.revision import NotFoundError
from app.providers import enrich, fields, net, resolve
from app.routes.helpers import Refused, get_config, get_store
from app.routes.titles import _body, answer, check_dupes

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


def resolve_checked(store: Store, cfg: Config, actor_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/resolve, shared with the MCP lookup tool."""
    lines = [str(line).strip() for line in body.get("lines") or [] if str(line).strip()][:MAX_LINES]
    if not lines:
        raise Refused(400, "nothing to look up")
    if not cfg.providers.network:
        raise Refused(503, "lookups_off")
    gate = limiter(cfg.providers.lookups_per_minute)
    if not all(gate.allow(f"user:{actor_id}") for _line in lines):
        raise Refused(429, "lookup_rate_limited")
    kind = str(body.get("kind") or "any")
    return {"results": [resolve_line(store, line, kind) for line in lines]}


async def resolve_lines(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, resolve_checked, get_store(request), get_config(request), actor_from(request).user.id, body)


def enrich_one(store: Store, title_id: str, refresh: bool) -> dict[str, Any]:
    title = library_cache.get(store).titles.get(title_id)
    if title is None or title.get("deleted_at") is not None:
        raise NotFoundError()
    previous = enrich.enrich_and_save(store, title, refresh=refresh)
    return {"title": titles.get_title(store, title_id), "previous": previous}


def enrich_checked(store: Store, cfg: Config, title_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/titles/{title_id}/enrich, shared with MCP."""
    if not cfg.providers.network:
        raise Refused(503, "lookups_off")
    try:
        return enrich_one(store, title_id, bool(body.get("refresh")))
    except NotFoundError:
        raise Refused(404, "no such title") from None


async def enrich_title(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, enrich_checked, get_store(request), get_config(request), request.path_params["title_id"], body)
