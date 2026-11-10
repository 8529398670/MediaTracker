"""Discover: the catalogue of films from Wikipedia's lists (box-office
number ones, awards, every American film of a year, topics like Pre-Code),
filtered and sorted on the server, with each film marked if it is already in
the library. "Skip" is a personal verdict that hides a film from you only;
"Add" puts it in the family library and on your list."""
from __future__ import annotations

import urllib.parse
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.core.db import Store
from app.core.security import actor_from
from app.discover import catalogue, certs
from app.media import dupes, normalize
from app.models import library_cache, verdicts
from app.models.revision import ConflictError
from app.reference.images import CACHE
from app.routes.helpers import Refused, get_config, get_store, run
from app.routes.subject import subject_from
from app.routes.titles import _body, add_title, answer

SORTS = ("notable", "title", "year", "year-asc", "imdb")


def _int(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 0


def library_index(store: Store) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """How a catalogue film is found in the library: by catalogue key, by
    Wikipedia article, or by folded title and year."""
    by_key: dict[str, str] = {}
    by_wiki: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for title in library_cache.get(store).live_titles():
        if title.get("catalogue_key"):
            by_key[title["catalogue_key"]] = title["id"]
        if title.get("wiki_url"):
            by_wiki[dupes.wiki_key(title["wiki_url"])] = title["id"]
        by_name[f"{dupes.norm_key(title.get('title'))}|{title.get('year') or ''}"] = title["id"]
    return by_key, by_wiki, by_name


def catalogue_key_for(title: dict[str, Any]) -> str:
    """The catalogue key a library title would have: the one it was added
    under, else the same article-or-name-and-year key the merge gives it."""
    if title.get("catalogue_key"):
        return title["catalogue_key"]
    address = str(title.get("wiki_url") or "")
    article = ""
    if "/wiki/" in address:
        article = urllib.parse.unquote(address.split("/wiki/", 1)[1].split("#", 1)[0]).replace("_", " ")
    return catalogue.key_of({"article": article, "title": title.get("title") or "", "year": title.get("year")})


def search(store: Store, subject_id: int, params: dict[str, str]) -> dict[str, Any]:
    """Shared with the MCP discover_search tool."""
    mine = verdicts.get_verdicts(store, subject_id)
    passed = {key for key, entry in mine.items() if entry.get("v") == "skip"}
    # What you have watched, and what you skipped in the library ("not for
    # me"), are hidden here too unless asked for.
    cache = library_cache.get(store)
    states = cache.states_for(subject_id)
    seen: set[str] = set()
    for title in cache.live_titles():
        status = (states.get(title["id"]) or {}).get("status")
        if status == "watched":
            seen.add(catalogue_key_for(title))
        elif status == "dropped":
            passed.add(catalogue_key_for(title))
    watched = params.get("watched") if params.get("watched") in ("hide", "only", "all") else "hide"
    sort = params.get("sort") if params.get("sort") in SORTS else "notable"
    query = dict(
        year_from=_int(params.get("from")),
        year_to=_int(params.get("to")),
        text=params.get("q", ""),
        topic=params.get("topic", ""),
        genres=[g for g in params.get("genre", "").split(",") if g],
        genre_mode="all" if params.get("genremode") == "all" else "any",
        actor=params.get("actor", ""),
        only=params.get("only", ""),
        skipped=params.get("skipped") if params.get("skipped") in ("hide", "only", "all") else "hide",
        ratings=[r for r in params.get("rating", "").split(",") if r],
        sort=sort,
        limit=min(_int(params.get("limit")) or 60, 200),
        offset=_int(params.get("offset")),
        passed=passed,
        watched=watched,
        seen=seen,
    )
    result = catalogue.query(**query)
    # Nothing by those exact words: try them as near-spellings, and say so.
    if query["text"].strip() and not result["total"]:
        result = catalogue.query(**query, fuzzy=True)
        result["fuzzy"] = True
    by_key, by_wiki, by_name = library_index(store)
    for film in result["films"]:
        ident = by_key.get(film["key"]) or by_wiki.get(dupes.wiki_key(film.get("url") or "")) or by_name.get(f"{dupes.norm_key(film.get('title'))}|{film.get('year') or ''}")
        film["title_id"] = ident
        film["my_status"] = (states.get(ident) or {}).get("status") if ident else None
        film["verdict"] = (mine.get(film["key"]) or {}).get("v")
    # A library title whose key did not line up with the catalogue's (an old
    # import under a slightly different name) still found its film above:
    # keep it off the page if it is hidden.
    hidden = set()
    if watched == "hide":
        hidden.add("watched")
    if query["skipped"] == "hide":
        hidden.add("dropped")
    result["films"] = [film for film in result["films"] if film["my_status"] not in hidden]
    return result


async def query(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return JSONResponse(await run(search, get_store(request), subject, dict(request.query_params)))


def meta_payload() -> dict[str, Any]:
    """GET /api/discover/meta, shared with MCP: what the catalogue holds."""
    data = {**catalogue.source_catalogue(), "coverage": catalogue.coverage(), "rating_counts": certs.STORE.counts()}
    data["coverage"].pop("pages", None)
    return data


async def meta(request: Request) -> Response:
    return JSONResponse(await run(meta_payload))


def facts_for(articles: list[str]) -> dict[str, Any]:
    found = catalogue.facts(articles)
    for fact in found.values():
        fact["poster"] = CACHE.path_for(fact.get("thumb") or "")
    return found


async def facts(request: Request) -> Response:
    articles = [a for a in request.query_params.getlist("a") if a][:60]
    return JSONResponse(await run(facts_for, articles))


def verdict_checked(store: Store, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/discover/verdict, shared with MCP."""
    kwargs = {"expect": body["expect"]} if "expect" in body else {}
    try:
        previous = verdicts.set_verdict(store, subject_id, str(body.get("key") or ""), body.get("verdict"), **kwargs)
    except ValueError as error:
        raise Refused(400, str(error)) from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    return {"previous": previous}


async def set_verdict(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, verdict_checked, get_store(request), subject, body)


def film_fields(film: dict[str, Any]) -> dict[str, Any]:
    imdb_id, _ratings = certs.STORE.get(str(film.get("key") or "")) if film.get("key") else ("", [])
    return {
        "title": film.get("title"),
        "year": film.get("year"),
        "type": "movie",
        "wiki_url": film.get("url") or "",
        "creator": film.get("director") or "",
        "cast": film.get("cast") or [],
        "genres": film.get("genres") or [],
        "catalogue_key": film.get("key") or "",
        "imdb_id": imdb_id or film.get("imdb") or "",
        "certification": film.get("rating") or "",
        "poster_url": film.get("thumb") or "",
        "source": "wikipedia",
    }


def add_checked(store: Store, cfg: Config, actor_id: int, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/discover/add, shared with MCP."""
    film = body.get("film") if isinstance(body.get("film"), dict) else None
    if not film or not film.get("title"):
        raise Refused(400, "no film given")
    # Add puts it in the library with no status; Seen it sends "watched".
    status = body.get("status") if body.get("status") in normalize.STATUSES else None
    try:
        result = add_title(store, cfg, actor_id, subject_id, film_fields(film), {"status": status}, bool(body.get("force")))
    except ValueError as error:
        raise Refused(400, str(error)) from None
    if not result["created"]:
        raise Refused(409, "possible_duplicate", dupes=result["dupes"])
    return result


async def add(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, add_checked, get_store(request), get_config(request), actor_from(request).user.id, subject, body, status=201)
