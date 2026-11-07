"""The library over /mcp: an agent with an API key can search the family
library, read a title, add one (with the same duplicate check as the Add
screen), fix its details, set someone's status, rating or heart, read a
queue, look titles up, and browse Discover. Each tool calls the helper its
HTTP route uses, so both doors keep one set of rules.

Personal tools take an optional user_id -- whose state -- which, like ?user=
on the routes, only an admin-scoped key may point at someone else. Nothing
here deletes, merges or creates a credential: those stay with a browser.
"""
from __future__ import annotations

from typing import Any

from app.jobs import runner
from app.mcp.registry import Call, InvalidArguments, Refusal, Registry, Tool
from app.media import genres, normalize
from app.models import library_cache, playlists, user_state, users, verdicts
from app.models import titles as titles_model
from app.models.revision import ConflictError, NotFoundError
from app.routes import discover as discover_route
from app.routes import lookup as lookup_route
from app.routes.library import state_row
from app.routes.titles import add_title

SEARCHABLE = ("title", "creator", "cast", "tags", "notes")


def _args(call: Call, required: dict[str, type], optional: dict[str, type]) -> dict[str, Any]:
    """Like call.bind, but some arguments may be left out."""
    unknown = sorted(set(call.args) - set(required) - set(optional))
    if unknown:
        raise InvalidArguments(f"invalid arguments: unknown field {unknown[0]!r}")
    out: dict[str, Any] = {}
    for name, kind in {**required, **optional}.items():
        if name not in call.args:
            if name in required:
                raise InvalidArguments(f"invalid arguments: {name} is required")
            continue
        value = call.args[name]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise InvalidArguments(f"invalid arguments: {name} must be {kind.__name__}")
        out[name] = value
    return out


def _subject(call: Call, given: int | None) -> int:
    if given is None or given == call.actor.user.id:
        return call.actor.user.id
    if not call.actor.is_admin:
        raise Refusal("only an admin can act for someone else")
    if users.get_user(call.store, given) is None:
        raise Refusal("no such user")
    return given


def _row(title: dict[str, Any], state: dict[str, Any] | None, social: dict[str, Any] | None) -> dict[str, Any]:
    keep = ("id", "title", "year", "type", "genres", "runtime", "certification", "creator", "tags", "imdb_id", "wiki_url", "notes", "added_at")
    out = {name: title.get(name) for name in keep}
    out["my_state"] = state_row(state) if state else None
    if social:
        out["family"] = {"watched": social["watched"], "loved": social["loved"]}
    return out


def search_library(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"text": str, "type": str, "status": str, "limit": int, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    snapshot = library_cache.get(call.store)
    states = snapshot.states_for(subject)
    words = normalize.text(args.get("text"), 200).lower().split()
    status = args.get("status")
    out = []
    for title in snapshot.live_titles():
        if args.get("type") and title.get("type") != args["type"]:
            continue
        state = states.get(title["id"])
        mine = (state or {}).get("status") or "none"
        if status and mine != status:
            continue
        hay = " ".join(str(title.get(field) or "") if not isinstance(title.get(field), list) else " ".join(title[field]) for field in SEARCHABLE).lower()
        hay += " " + " ".join(genres.terms(title.get("genres") or [])).lower()
        if words and not all(word in hay for word in words):
            continue
        out.append(_row(title, state, snapshot.social.get(title["id"])))
    limit = max(1, min(args.get("limit", 50), 500))
    return {"total": len(out), "titles": out[:limit]}


def get_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    snapshot = library_cache.get(call.store)
    title = snapshot.titles.get(args["title_id"])
    if title is None or title.get("deleted_at"):
        raise Refusal("no such title")
    return {**title, "my_state": state_row(snapshot.states_for(subject)[args["title_id"]]) if args["title_id"] in snapshot.states_for(subject) else None, "family": snapshot.social.get(title["id"])}


def add_title_tool(call: Call) -> dict[str, Any]:
    args = _args(call, {"title": str}, {"year": int, "type": str, "status": str, "force": bool, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    fields = {"title": args["title"], "year": args.get("year"), "type": args.get("type") or "movie"}
    status = args.get("status", "queue")
    if status not in (*normalize.STATUSES, "none"):
        raise Refusal("status must be queue, watching, watched, dropped or none")
    try:
        result = add_title(call.store, call.config, call.actor.user.id, subject, fields, {"status": None if status == "none" else status}, args.get("force", False))
    except ValueError as error:
        raise Refusal(str(error)) from None
    if not result["created"]:
        return {"created": False, "possible_duplicates": [{"id": dupe["id"], "title": dupe["title"]["title"], "year": dupe["title"].get("year"), "score": dupe["score"]} for dupe in result["dupes"]], "hint": "Use the existing title, or call again with force: true."}
    return {"created": True, "title": result["title"]}


def update_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str, "set": dict}, {})
    changes = normalize.clean_title_fields(args["set"])
    if not changes:
        raise Refusal("nothing to change (fields: " + ", ".join(normalize.TITLE_FIELDS) + ")")
    try:
        record, previous = titles_model.update_title(call.store, args["title_id"], changes, None, call.actor.user.id)
    except NotFoundError:
        raise Refusal("no such title") from None
    except ValueError as error:
        raise Refusal(str(error)) from None
    return {"title": record, "previous": previous}


def set_state(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str, "set": dict}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    changes = normalize.clean_state_fields(args["set"])
    if not changes:
        raise Refusal("nothing to change (fields: status, rating, heart, note, watched_at)")
    try:
        state, previous = user_state.set_state(call.store, subject, args["title_id"], changes, None, call.actor.user.id)
    except NotFoundError:
        raise Refusal("no such title") from None
    except ConflictError:
        raise Refusal("it was changed somewhere else in the meantime") from None
    return {"state": state_row(state), "previous": previous}


def list_queue(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"user_id": int, "limit": int})
    subject = _subject(call, args.get("user_id"))
    snapshot = library_cache.get(call.store)
    mine = snapshot.states_for(subject)
    queued = [
        title
        for title_id, state in mine.items()
        if state.get("status") in ("queue", "watching")
        and (title := snapshot.titles.get(title_id)) is not None
        and not title.get("deleted_at")
    ]
    # Newest first, like the Up next screen.
    queued.sort(key=lambda title: title.get("added_at") or "", reverse=True)
    return {"queue": [_row(title, mine.get(title["id"]), None) for title in queued[: max(1, min(args.get("limit", 100), 1000))]]}


def list_playlists(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    return {"playlists": [{"id": record["id"], "name": record["name"], "count": len(record["items"])} for record in playlists.list_playlists(call.store, subject)]}


def get_playlist(call: Call) -> dict[str, Any]:
    args = _args(call, {"playlist_id": int}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    found = next((record for record in playlists.list_playlists(call.store, subject) if record["id"] == args["playlist_id"]), None)
    if found is None:
        raise Refusal("no such playlist")
    snapshot = library_cache.get(call.store)
    mine = snapshot.states_for(subject)
    rows = []
    for number, title_id in enumerate(found["items"], start=1):
        title = snapshot.titles.get(title_id)
        if title and not title.get("deleted_at"):
            rows.append({"number": number, **_row(title, mine.get(title_id), None)})
    return {"id": found["id"], "name": found["name"], "titles": rows}


def change_playlist(call: Call) -> dict[str, Any]:
    args = _args(call, {"playlist_id": int, "title_ids": list}, {"action": str, "position": int, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    action = args.get("action", "add")
    try:
        if action == "add":
            record, before = playlists.add_items(call.store, subject, args["playlist_id"], args["title_ids"], args.get("position"))
        elif action == "remove":
            record, before = playlists.remove_items(call.store, subject, args["playlist_id"], args["title_ids"])
        elif action == "move" and len(args["title_ids"]) == 1 and "position" in args:
            record, before = playlists.move_item(call.store, subject, args["playlist_id"], args["title_ids"][0], args["position"])
        else:
            raise Refusal("action is add, remove, or move (one title id and a position)")
    except NotFoundError as missing:
        raise Refusal(str(missing)) from None
    except ValueError as error:
        raise Refusal(str(error)) from None
    return {"items": record["items"], "previous_items": before}


def lookup(call: Call) -> dict[str, Any]:
    args = _args(call, {"text": str}, {"kind": str})
    if not call.config.providers.network:
        raise Refusal("lookups are switched off on this server")
    found = lookup_route.resolve_line(call.store, args["text"], args.get("kind", "any"))
    return {
        "confident": found["confident"],
        "note": found["note"],
        "candidates": [candidate["fields"] for candidate in found["candidates"]],
        "already_in_library": [{"id": dupe["id"], "title": dupe["title"]["title"], "score": dupe["score"]} for dupe in found["dupes"]],
    }


def discover_search(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"text": str, "year_from": int, "year_to": int, "genres": str, "sort": str, "limit": int, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    params = {"q": args.get("text", ""), "from": str(args.get("year_from", "")), "to": str(args.get("year_to", "")), "genre": args.get("genres", ""), "sort": args.get("sort", "notable"), "limit": str(min(args.get("limit", 20), 100))}
    result = discover_route.search(call.store, subject, params)
    keep = ("key", "title", "year", "director", "genres", "rating", "imdbScore", "url", "title_id", "my_status")
    return {"total": result["total"], "films": [{name: film.get(name) for name in keep} for film in result["films"]]}


def set_verdict(call: Call) -> dict[str, Any]:
    args = _args(call, {"key": str}, {"verdict": str, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    try:
        previous = verdicts.set_verdict(call.store, subject, args["key"], args.get("verdict"))
    except ValueError as error:
        raise Refusal(str(error)) from None
    return {"previous": previous}


def jobs_status(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return {"jobs": runner.statuses()}


USER = {"type": "integer", "minimum": 1, "description": "Whose state (admin keys only); defaults to the key's own account."}
TITLE_ID = {"type": "string", "description": "A title id from search_library."}


def _schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def register(registry: Registry) -> None:
    registry.register(Tool(
        name="search_library",
        title="Search the library",
        description="Titles in the family library, with your own state on each (status, rating, heart) and who else has watched or loved it. All arguments optional: text matches title, director, cast, genres, tags and notes; status is queue, watching, watched, dropped or none.",
        call=search_library,
        input_schema=_schema({"text": {"type": "string"}, "type": {"type": "string", "description": "A type id such as movie or tv."}, "status": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}, "user_id": USER}),
        read_only=True,
    ))
    registry.register(Tool(name="get_title", title="Get a title", description="Everything about one title, your state on it and the family's.", call=get_title, input_schema=_schema({"title_id": TITLE_ID, "user_id": USER}, ("title_id",)), read_only=True))
    registry.register(Tool(
        name="add_title",
        title="Add a title",
        description="Add a title to the family library and put it on a list (status: queue by default, or watched, watching, dropped, none). Refuses with possible duplicates unless force is true. Details are filled in in the background.",
        call=add_title_tool,
        input_schema=_schema({"title": {"type": "string"}, "year": {"type": "integer"}, "type": {"type": "string"}, "status": {"type": "string"}, "force": {"type": "boolean"}, "user_id": USER}, ("title",)),
    ))
    registry.register(Tool(
        name="update_title",
        title="Edit a title",
        description="Change shared details of a title (title, year, type, tags, notes, links, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url). Returns the previous values.",
        call=update_title,
        input_schema=_schema({"title_id": TITLE_ID, "set": {"type": "object"}}, ("title_id", "set")),
    ))
    registry.register(Tool(
        name="set_state",
        title="Set status, rating or heart",
        description="Change one person's state on a title: status (queue, watching, watched, dropped, or null for off the list), rating 1-10 or null, heart true/false, note, watched_at. Returns the previous values.",
        call=set_state,
        input_schema=_schema({"title_id": TITLE_ID, "set": {"type": "object"}, "user_id": USER}, ("title_id", "set")),
    ))
    registry.register(Tool(name="list_queue", title="Up next", description="A person's Up next list, newest first.", call=list_queue, input_schema=_schema({"user_id": USER, "limit": {"type": "integer", "minimum": 1}}), read_only=True))
    registry.register(Tool(name="list_playlists", title="Playlists", description="A person's playlists: id, name and how many titles each holds.", call=list_playlists, input_schema=_schema({"user_id": USER}), read_only=True))
    registry.register(Tool(name="get_playlist", title="Get a playlist", description="One playlist's titles, numbered in its order.", call=get_playlist, input_schema=_schema({"playlist_id": {"type": "integer"}, "user_id": USER}, ("playlist_id",)), read_only=True))
    registry.register(Tool(
        name="change_playlist",
        title="Change a playlist",
        description="action add (at position, 1-based; the end by default), remove, or move (one title id to position; the rest renumber). Returns the items before, which is the undo.",
        call=change_playlist,
        input_schema=_schema({"playlist_id": {"type": "integer"}, "title_ids": {"type": "array", "items": {"type": "string"}}, "action": {"type": "string", "enum": ["add", "remove", "move"]}, "position": {"type": "integer"}, "user_id": USER}, ("playlist_id", "title_ids")),
    ))
    registry.register(Tool(
        name="lookup",
        title="Look a title up",
        description="Identify a name, name and year, or link (IMDb, Wikipedia, TMDB, TVmaze...) with the configured providers, and say whether the library already has it. Writes nothing.",
        call=lookup,
        input_schema=_schema({"text": {"type": "string"}, "kind": {"type": "string", "description": "movie, tv, book, ... or any."}}, ("text",)),
        read_only=True,
    ))
    registry.register(Tool(
        name="discover_search",
        title="Search Discover",
        description="The Wikipedia film catalogue, minus films you skipped. genres is comma-separated; sort is notable, imdb, year, year-asc or title. Each film says whether it is already in the library (title_id) and your status on it.",
        call=discover_search,
        input_schema=_schema({"text": {"type": "string"}, "year_from": {"type": "integer"}, "year_to": {"type": "integer"}, "genres": {"type": "string"}, "sort": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "user_id": USER}),
        read_only=True,
    ))
    registry.register(Tool(name="set_verdict", title="Skip a Discover film", description="verdict: skip (hide it from you), seen, or leave it out to clear.", call=set_verdict, input_schema=_schema({"key": {"type": "string"}, "verdict": {"type": "string"}, "user_id": USER}, ("key",))))
    registry.register(Tool(name="jobs_status", title="Background jobs", description="What the server is doing in the background (filling in titles, IMDb ratings, the catalogue).", call=jobs_status, read_only=True))
