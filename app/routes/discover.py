"""Discover: the catalogue of films from Wikipedia's lists (box-office
number ones, awards, every American film of a year, topics like Pre-Code),
filtered and sorted on the server, with each film marked if it is already in
the library. "Skip" is a personal verdict that hides a film from you only;
"Add" puts it in the family library and on your list."""
from __future__ import annotations

import urllib.parse
from typing import Annotated, Any, Callable

import msgspec
from msgspec import UNSET, Meta
from starlette.requests import Request

from app.apidocs import QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.db import Store
from app.core.security import actor_from
from app.discover import catalogue, certs
from app.mcp.registry import Call
from app.media import dupes, normalize
from app.models import library_cache, verdicts
from app.models.revision import ConflictError
from app.reference.images import CACHE
from app.routes.helpers import Refused, get_config, get_store
from app.routes.library import state_row
from app.routes.subject import User, subject_of
from app.routes.titles import Expect, Record, add_title, dupe_rows

TAG = "Discover"


def _int(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 0


def _float(value: str | None) -> float:
    try:
        number = float(value or 0)
    except ValueError:
        return 0.0
    return number if 0 <= number <= 10 else 0.0


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
    owned: set[str] = set()
    for title in cache.live_titles():
        owned.add(catalogue_key_for(title))
        status = (states.get(title["id"]) or {}).get("status")
        if status == "watched":
            seen.add(catalogue_key_for(title))
        elif status == "dropped":
            passed.add(catalogue_key_for(title))
    watched = params.get("watched") if params.get("watched") in ("hide", "only", "all") else "hide"
    sort = params.get("sort") or "notable"
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
        no_ratings=[r for r in params.get("norating", "").split(",") if r],
        imdb_from=_float(params.get("imdbfrom")),
        imdb_to=_float(params.get("imdbto")),
        votes_from=_int(params.get("votesfrom")),
        votes_to=_int(params.get("votesto")),
        runtime_from=_int(params.get("runtimefrom")),
        runtime_to=_int(params.get("runtimeto")),
        sort=sort,
        limit=min(_int(params.get("limit")) or 60, 200),
        offset=_int(params.get("offset")),
        passed=passed,
        watched=watched,
        seen=seen,
        library="hide" if params.get("library") == "hide" else "all",
        owned=owned,
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
    attach_known_facts(result["films"])
    # A library title whose key did not line up with the catalogue's (an old
    # import under a slightly different name) still found its film above:
    # keep it off the page if it is hidden.
    hidden = set()
    if watched == "hide":
        hidden.add("watched")
    if query["skipped"] == "hide":
        hidden.add("dropped")
    result["films"] = [film for film in result["films"] if film["my_status"] not in hidden
                       and not (query["library"] == "hide" and film["title_id"])]
    return result


class DiscoverQuery(RequestType, kw_only=True):
    q: Annotated[str, QUERY, Meta(description="Words to find in the title, director or cast.")] = ""
    year_from: Annotated[str, QUERY, Meta(description="Earliest year.")] = msgspec.field(default="", name="from")
    year_to: Annotated[str, QUERY, Meta(description="Latest year.")] = msgspec.field(default="", name="to")
    topic: Annotated[str, QUERY, Meta(description="A topic id from GET /api/discover/meta.")] = ""
    genre: Annotated[str, QUERY, Meta(description="Genres, comma-separated.")] = ""
    genremode: Annotated[str, QUERY, Meta(description="all: every genre given. Default any.")] = ""
    actor: Annotated[str, QUERY, Meta(description="A cast member's name.")] = ""
    only: Annotated[str, QUERY, Meta(description="A source list id from GET /api/discover/meta.")] = ""
    skipped: Annotated[str, QUERY, Meta(description="hide, only or all: films skipped, here or as dropped in the library. Default hide.")] = ""
    watched: Annotated[str, QUERY, Meta(description="hide, only or all: films watched. Default hide.")] = ""
    library: Annotated[str, QUERY, Meta(description="hide: leave out films already in the library. Default all.")] = ""
    rating: Annotated[str, QUERY, Meta(description="Certifications to keep, comma-separated.")] = ""
    norating: Annotated[str, QUERY, Meta(description="Certifications to leave out, comma-separated.")] = ""
    imdbfrom: Annotated[str, QUERY, Meta(description="Lowest IMDb score, 0-10.")] = ""
    imdbto: Annotated[str, QUERY, Meta(description="Highest IMDb score, 0-10.")] = ""
    votesfrom: Annotated[str, QUERY, Meta(description="Fewest IMDb votes.")] = ""
    votesto: Annotated[str, QUERY, Meta(description="Most IMDb votes.")] = ""
    runtimefrom: Annotated[str, QUERY, Meta(description="Shortest running time, in minutes.")] = ""
    runtimeto: Annotated[str, QUERY, Meta(description="Longest running time, in minutes.")] = ""
    sort: Annotated[str, QUERY, Meta(description="notable, imdb, year, year-asc or title. Default notable.")] = ""
    limit: Annotated[str, QUERY, Meta(description="Films to return, at most 200. Default 60.")] = ""
    offset: Annotated[str, QUERY, Meta(description="Films to skip.")] = ""
    user: User = None


def compact_films(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of discover_search: each film's main facts, not everything
    the grid draws."""
    result = serve(call.request, body)
    keep = ("key", "article", "title", "year", "director", "genres", "rating", "imdbScore", "runtime", "url", "title_id", "my_status", "verdict")
    return {"total": result["total"], "films": [{name: film.get(name) for name in keep} for film in result["films"]]}


@route(
    "GET /api/discover", summary="Search Discover",
    tag=TAG,
    description="The Wikipedia film catalogue, minus films the person skipped or watched unless asked for. "
    "Each film says whether it is already in the library (title_id) and the person's status on it. "
    "Answers total, films and, when nothing matched the exact words, fuzzy: true.",
    mcp="discover_search", read_only=True, call=compact_films,
)
def query(request: Request, body: DiscoverQuery) -> dict[str, Any]:
    subject = subject_of(request, body.user)
    params = {name: value for name, value in msgspec.to_builtins(body).items() if name != "user"}
    return search(get_store(request), subject, params)


@route(
    "GET /api/discover/meta", summary="Discover catalogue",
    tag=TAG,
    description="What the Discover catalogue holds: its source lists and topics, coverage, and rating counts.",
    mcp="discover_meta", read_only=True,
)
def meta(request: Request) -> dict[str, Any]:
    data = {**catalogue.source_catalogue(), "coverage": catalogue.coverage(), "rating_counts": certs.STORE.counts()}
    data["coverage"].pop("pages", None)
    return data


def attach_known_facts(films: list[dict[str, Any]]) -> None:
    """Posters, IMDb ids and ratings already learned go out with the first
    response, so a page seen before draws whole at once and only the films
    never asked about wait for /api/discover/facts. Such a film is marked
    "facts": true and is not asked about again."""
    known = catalogue.known_facts([film.get("article") or "" for film in films])
    for film in films:
        fact = known.get(film.get("article") or "")
        if not fact:
            continue
        film["facts"] = True
        film["poster"] = CACHE.path_for(fact.get("thumb") or "") or film.get("poster") or ""
        film["thumb"] = fact.get("thumb") or film.get("thumb") or ""
        film["imdb"] = film.get("imdb") or fact.get("imdb") or ""
        if not film.get("imdbScore") and fact.get("imdbScore"):
            film["imdbScore"] = fact["imdbScore"]
        if not film.get("rating") and fact.get("rating"):
            film["rating"] = fact["rating"]
        if not film.get("runtime") and fact.get("runtime"):
            film["runtime"] = fact["runtime"]


def facts_for(articles: list[str]) -> dict[str, Any]:
    found = catalogue.facts(articles)
    for fact in found.values():
        fact["poster"] = CACHE.path_for(fact.get("thumb") or "")
    return found


class Facts(RequestType, kw_only=True):
    articles: Annotated[str, QUERY, Meta(description="Wikipedia article names (a film's article), separated by |. At most 60.")] = ""


@route(
    "GET /api/discover/facts", summary="Discover film details",
    tag=TAG,
    description="Plot, cast and poster for up to 60 catalogue films, by article name (a film's url ends in "
    "it), keyed by article.",
    mcp="discover_facts", read_only=True,
)
def facts(request: Request, body: Facts) -> dict[str, Any]:
    return facts_for([article for article in body.articles.split("|") if article][:60])


class SetVerdict(RequestType, kw_only=True):
    key: Annotated[str, Meta(description="The film's key, from GET /api/discover.")]
    verdict: Annotated[str | None, Meta(description="skip (hide it from you), seen, or null to clear.")] = None
    expect: Expect = UNSET
    user: User = None


class VerdictReply(Reply, kw_only=True):
    previous: Annotated[str | None, Meta(description="The verdict it replaced.")]


@route(
    "POST /api/discover/verdict", summary="Skip a Discover film",
    tag=TAG, errors=(409,),
    description="Set the person's verdict on a film: skip hides it from them only, seen marks it seen, null "
    "clears it.",
    mcp="set_verdict",
)
def set_verdict(request: Request, body: SetVerdict) -> VerdictReply:
    subject = subject_of(request, body.user)
    kwargs = {"expect": body.expect} if body.expect is not UNSET else {}
    try:
        previous = verdicts.set_verdict(get_store(request), subject, body.key, body.verdict, **kwargs)
    except ValueError as error:
        raise Refused(400, str(error)) from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    return VerdictReply(previous=previous)


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


def when_added(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of discover_add: a possible duplicate is an answer."""
    try:
        result = serve(call.request, body)
    except Refused as refused:
        if refused.status != 409 or "dupes" not in refused.extra:
            raise
        return {"created": False, "possible_duplicates": dupe_rows(refused.extra["dupes"]), "hint": "Use the existing title, or call again with force: true."}
    return {"created": True, "title": result.title, "state": state_row(result.state)}


class AddFilm(RequestType, kw_only=True):
    film: Annotated[Record, Meta(description="A film as GET /api/discover gives it.")]
    status: Annotated[str | None, Meta(description="watched for Seen it; leave out for no list.")] = None
    force: Annotated[bool, Meta(description="Add it even if it looks like a title the library has.")] = False
    user: User = None


class FilmAdded(Reply, kw_only=True):
    created: bool
    title: Record
    state: Record


@route(
    "POST /api/discover/add", summary="Add a Discover film",
    tag=TAG, status=201, errors=(409,),
    description="Add a film from Discover (the film object as it was given) to the library, with its "
    "Wikipedia details. status: watched for Seen it, or leave it out for no list. Refused with 409 "
    "possible_duplicate and the dupes unless force is true.",
    mcp_note="A possible duplicate answers created: false with possible_duplicates instead.",
    mcp="discover_add", call=when_added,
)
def add(request: Request, body: AddFilm) -> FilmAdded:
    subject = subject_of(request, body.user)
    if not body.film.get("title"):
        raise Refused(400, "no film given")
    # Add puts it in the library with no status; Seen it sends "watched".
    status = body.status if body.status in normalize.STATUSES else None
    try:
        result = add_title(get_store(request), get_config(request), actor_from(request).user.id, subject, film_fields(body.film), {"status": status}, body.force)
    except ValueError as error:
        raise Refused(400, str(error)) from None
    if not result["created"]:
        raise Refused(409, "possible_duplicate", dupes=result["dupes"])
    return FilmAdded(created=True, title=result["title"], state=result["state"])
