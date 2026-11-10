"""The library over /mcp: an agent with an API key can search the family
library, read a title, add one (with the same duplicate check as the Add
screen), fix its details, delete, restore, merge or fill one in, set
someone's status, rating or heart, import a list, look titles up, browse and
add from Discover, and see or (admin) start and stop the background jobs.
Playlists, saved views, prefs, types and sources are in
mcp_tools_lists.py. Each tool is the door to one HTTP route (route=) and calls
the helper that route uses, so both doors keep one set of rules.

Personal tools take an optional user_id -- whose state -- which, like ?user=
on the routes, only an admin (or someone given Showing) may point at someone
else. Deletes here are the same soft deletes the routes make, restorable for
the undo window; nothing here erases for good or creates a credential.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.mcp.registry import Call, InvalidArguments, Refusal, Registry, Tool
from app.media import genres, normalize
from app.models import library_cache, titles as titles_model, users
from app.routes import discover as discover_route
from app.routes import dupes as dupes_route
from app.routes import jobs as jobs_route
from app.routes import lookup as lookup_route
from app.routes import porting as porting_route
from app.routes import state as state_route
from app.routes import titles as titles_route
from app.routes.helpers import Refused
from app.routes.library import state_row, vocab

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
    """subject_from for a tool: whose lists a personal tool acts on."""
    locked = users.locked_subject(call.actor.user)
    if locked is not None:
        if locked != call.actor.user.id and users.get_user(call.store, locked) is None:
            locked = call.actor.user.id
        if given is not None and given != locked:
            raise Refusal("an admin has set whose lists you see")
        return locked
    if given is None or given == call.actor.user.id:
        return call.actor.user.id
    if not (call.actor.is_admin or call.actor.user.can_show_others):
        raise Refusal("only an admin, or someone given Showing, can act for someone else")
    if users.get_user(call.store, given) is None:
        raise Refusal("no such user")
    return given


def _shared(helper: Callable[..., Any], *args: Any) -> Any:
    """A helper its HTTP route shares, refusing in the route's words. What
    the route sends beside the error (the current value of a 409, say)
    follows them as JSON. Only Refused.internal is an internal error: a 503
    such as lookups_off is a refusal like any other."""
    try:
        return helper(*args)
    except Refused as refused:
        raise _refusal(refused) from None


def _refusal(refused: Refused) -> Exception:
    if refused.status == 500:
        return RuntimeError(refused.cause)
    extra = f": {json.dumps(refused.extra, default=str, ensure_ascii=False)}" if refused.extra else ""
    return Refusal(refused.message + extra)


def _body(args: dict[str, Any], *drop: str) -> dict[str, Any]:
    """The tool's arguments as the route's JSON body: everything but user_id
    and the path parameters."""
    return {name: value for name, value in args.items() if name not in ("user_id", *drop)}


def _row(title: dict[str, Any], state: dict[str, Any] | None, social: dict[str, Any] | None) -> dict[str, Any]:
    keep = ("id", "title", "year", "type", "genres", "runtime", "certification", "creator", "tags", "imdb_id", "wiki_url", "notes", "added_at")
    out = {name: title.get(name) for name in keep}
    out["my_state"] = state_row(state) if state else None
    if social:
        out["family"] = {"watched": social["watched"], "loved": social["loved"]}
    return out


def _dupe_rows(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": dupe["id"], "title": dupe["title"]["title"], "year": dupe["title"].get("year"), "score": dupe["score"]} for dupe in found]


# --- the library and titles ---


def search_library(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"text": str, "type": str, "status": str, "limit": int, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    snapshot = library_cache.get(call.store)
    states = snapshot.states_for(subject)
    words = normalize.text(args.get("text"), 200).lower().split()
    status = args.get("status")
    up_next = status == "up_next"
    out = []
    for title in snapshot.live_titles():
        if args.get("type") and title.get("type") != args["type"]:
            continue
        state = states.get(title["id"])
        mine = (state or {}).get("status") or "none"
        if up_next:
            if mine not in ("queue", "watching"):
                continue
        elif status and mine != status:
            continue
        hay = " ".join(str(title.get(field) or "") if not isinstance(title.get(field), list) else " ".join(title[field]) for field in SEARCHABLE).lower()
        hay += " " + " ".join(genres.terms(title.get("genres") or [])).lower()
        if words and not all(word in hay for word in words):
            continue
        out.append(_row(title, state, snapshot.social.get(title["id"])))
    if up_next:
        # Newest first, like the Up next screen.
        out.sort(key=lambda row: row.get("added_at") or "", reverse=True)
    limit = max(1, min(args.get("limit", 50), 500))
    return {"total": len(out), "titles": out[:limit]}


def get_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    snapshot = library_cache.get(call.store)
    title = snapshot.titles.get(args["title_id"])
    if title is None or title.get("deleted_at"):
        raise Refusal("no such title")
    mine = snapshot.states_for(subject)
    return {**title, "my_state": state_row(mine[args["title_id"]]) if args["title_id"] in mine else None, "family": snapshot.social.get(title["id"])}


def add_title_tool(call: Call) -> dict[str, Any]:
    args = _args(call, {"title": str}, {"year": int, "type": str, "status": str, "force": bool, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    fields = {"title": args["title"], "year": args.get("year"), "type": args.get("type") or "movie"}
    status = args.get("status", "queue")
    if status not in (*normalize.STATUSES, "none"):
        raise Refusal("status must be queue, watching, watched, dropped or none")
    try:
        result = titles_route.add_title(call.store, call.config, call.actor.user.id, subject, fields, {"status": None if status == "none" else status}, args.get("force", False))
    except (ValueError, titles_model.TooManyTitlesError) as error:
        raise Refusal(str(error)) from None
    if not result["created"]:
        return {"created": False, "possible_duplicates": _dupe_rows(result["dupes"]), "hint": "Use the existing title, or call again with force: true."}
    return {"created": True, "title": result["title"]}


def check_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title": str}, {"year": int, "type": str})
    found = _shared(titles_route.check_checked, call.store, {"title": args})
    return {"matches": _dupe_rows(found["matches"])}


def update_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str, "set": dict}, {"expect": object})
    if not normalize.clean_title_fields(args["set"]):
        raise Refusal("nothing to change (fields: " + ", ".join(normalize.TITLE_FIELDS) + ")")
    return _shared(titles_route.update_checked, call.store, args["title_id"], _body(args, "title_id"), call.actor.user.id)


def delete_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str}, {})
    return _shared(titles_route.delete_checked, call.store, args["title_id"], call.actor.user.id)


def restore_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str}, {})
    return _shared(titles_route.restore_checked, call.store, args["title_id"], call.config.library.restore_days)


def bulk_edit_titles(call: Call) -> dict[str, Any]:
    args = _args(call, {"ids": list, "op": str}, {"value": object})
    return _shared(titles_route.bulk_checked, call.store, call.actor.user.id, args, call.config.library.restore_days)


def enrich_title(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str}, {"refresh": bool})
    return _shared(lookup_route.enrich_checked, call.store, call.config, args["title_id"], _body(args, "title_id"))


def merge_titles(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str, "drop_ids": list}, {})
    return _shared(dupes_route.merge_checked, call.store, args["title_id"], _body(args, "title_id"), call.actor.user.id)


def undo_merge(call: Call) -> dict[str, Any]:
    args = _args(call, {"merge_id": str}, {})
    return _shared(dupes_route.undo_merge_checked, call.store, args["merge_id"])


def list_duplicates(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return {"groups": dupes_route.groups(call.store)}


def dismiss_duplicates(call: Call) -> dict[str, Any]:
    args = _args(call, {"ids": list}, {})
    return _shared(dupes_route.dismiss_checked, call.store, args, call.actor.user.id)


def undismiss_duplicates(call: Call) -> dict[str, Any]:
    args = _args(call, {"pairs": list}, {})
    return _shared(dupes_route.undismiss_checked, call.store, args)


def get_vocab(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return vocab()


# --- state ---


def set_state(call: Call) -> dict[str, Any]:
    args = _args(call, {"title_id": str, "set": dict}, {"expect": object, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    if not normalize.clean_state_fields(args["set"]):
        raise Refusal("nothing to change (fields: status, rating, heart, note, watched_at)")
    return _shared(state_route.set_one_checked, call.store, subject, args["title_id"], _body(args, "title_id"), call.actor.user.id)


def set_states(call: Call) -> dict[str, Any]:
    args = _args(call, {"changes": dict}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(state_route.set_many_checked, call.store, subject, _body(args), call.actor.user.id)


# --- lookups and import ---


def lookup(call: Call) -> dict[str, Any]:
    args = _args(call, {"text": str}, {"kind": str})
    found = _shared(lookup_route.resolve_checked, call.store, call.config, call.actor.user.id, {"lines": [args["text"]], "kind": args.get("kind", "any")})
    result = found["results"][0]
    return {
        "confident": result["confident"],
        "note": result["note"],
        "candidates": [candidate["fields"] for candidate in result["candidates"]],
        "already_in_library": [{"id": dupe["id"], "title": dupe["title"]["title"], "score": dupe["score"]} for dupe in result["dupes"]],
    }


def import_parse(call: Call) -> dict[str, Any]:
    args = _args(call, {"text": str}, {"format": str, "type": str, "status": str})
    return _shared(porting_route.parse_checked, call.store, args)


def import_items(call: Call) -> dict[str, Any]:
    args = _args(call, {"rows": list}, {"batch_id": str, "skip_dupes": bool, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(porting_route.import_checked, call.store, call.config, call.actor.user.id, subject, _body(args))


def undo_import(call: Call) -> dict[str, Any]:
    args = _args(call, {"batch_id": str}, {})
    return _shared(porting_route.undo_import_checked, call.store, args["batch_id"], call.actor.user.id)


# --- Discover ---


def discover_search(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"text": str, "year_from": int, "year_to": int, "genres": str, "sort": str, "limit": int, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    params = {"q": args.get("text", ""), "from": str(args.get("year_from", "")), "to": str(args.get("year_to", "")), "genre": args.get("genres", ""), "sort": args.get("sort", "notable"), "limit": str(min(args.get("limit", 20), 100))}
    result = discover_route.search(call.store, subject, params)
    keep = ("key", "title", "year", "director", "genres", "rating", "imdbScore", "url", "title_id", "my_status")
    return {"total": result["total"], "films": [{name: film.get(name) for name in keep} for film in result["films"]]}


def discover_meta(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return discover_route.meta_payload()


def discover_facts(call: Call) -> dict[str, Any]:
    args = _args(call, {"articles": list}, {})
    articles = [str(article) for article in args["articles"] if article][:60]
    return {"facts": discover_route.facts_for(articles)}


def set_verdict(call: Call) -> dict[str, Any]:
    args = _args(call, {"key": str}, {"verdict": str, "expect": object, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(discover_route.verdict_checked, call.store, subject, _body(args))


def discover_add(call: Call) -> dict[str, Any]:
    args = _args(call, {"film": dict}, {"status": str, "force": bool, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    try:
        result = discover_route.add_checked(call.store, call.config, call.actor.user.id, subject, _body(args))
    except Refused as refused:
        if refused.status == 409:
            return {"created": False, "possible_duplicates": _dupe_rows(refused.extra.get("dupes") or []), "hint": "Use the existing title, or call again with force: true."}
        raise _refusal(refused) from None
    return {"created": True, "title": result["title"], "state": state_row(result["state"])}


# --- background jobs ---


def jobs_status(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return jobs_route.jobs_payload(call.config)


def admin_start_job(call: Call) -> dict[str, Any]:
    args = _args(call, {"name": str}, {"options": dict})
    return _shared(jobs_route.start_job_checked, call.config, args["name"], _body(args, "name"))


def admin_stop_job(call: Call) -> dict[str, Any]:
    args = _args(call, {"name": str}, {})
    return _shared(jobs_route.stop_job_checked, args["name"])


USER = {"type": "integer", "minimum": 1, "description": "Whose state (an admin's key, or one given Showing); defaults to the key's own account."}
TITLE_ID = {"type": "string", "description": "A title id from search_library."}
TITLE_IDS = {"type": "array", "items": {"type": "string"}, "description": "Title ids from search_library."}
EXPECT = {"description": "Optional: the value you think it has now (the rev from your last read); if it changed meanwhile the call is refused with the current one."}


def schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def register(registry: Registry) -> None:
    def add(name: str, route: str, title: str, description: str, call: Callable[[Call], dict[str, Any]], input_schema: dict[str, Any] | None = None, **flags: Any) -> None:
        registry.register(Tool(name=name, route=route, title=title, description=description, call=call, input_schema=input_schema, **flags))

    # The library and titles.
    add(
        "search_library", "GET /api/library", "Search the library",
        "Titles in the family library, with your own state on each (status, rating, heart) and who else has watched or loved it. All arguments optional: text matches title, director, cast, genres, tags and notes; status is queue, watching, watched, dropped or none, or up_next for the Up next list (queue and watching, newest first).",
        search_library,
        schema({"text": {"type": "string"}, "type": {"type": "string", "description": "A type id such as movie or tv."}, "status": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}, "user_id": USER}),
        read_only=True,
    )
    add("get_vocab", "GET /api/vocab", "Library vocabulary", "The fixed words: statuses, lookup kinds, and the canonical genre names.", get_vocab, read_only=True)
    add("get_title", "GET /api/titles/{title_id}", "Get a title", "Everything about one title, your state on it and the family's.", get_title, schema({"title_id": TITLE_ID, "user_id": USER}, ("title_id",)), read_only=True)
    add(
        "add_title", "POST /api/titles", "Add a title",
        "Add a title to the family library and put it on a list (status: queue by default, or watched, watching, dropped, none). Refuses with possible duplicates unless force is true. Details are filled in in the background.",
        add_title_tool,
        schema({"title": {"type": "string"}, "year": {"type": "integer"}, "type": {"type": "string"}, "status": {"type": "string"}, "force": {"type": "boolean"}, "user_id": USER}, ("title",)),
    )
    add(
        "check_title", "POST /api/titles/check", "Check for a duplicate",
        "Would adding this title make a duplicate? The library titles it resembles, with a score. Writes nothing.",
        check_title, schema({"title": {"type": "string"}, "year": {"type": "integer"}, "type": {"type": "string"}}, ("title",)), read_only=True,
    )
    add(
        "bulk_edit_titles", "POST /api/titles/bulk", "Change many titles",
        "One change to many titles at once. op: set_type (value: a type id), add_tags or remove_tags (value: a list of tags), delete, restore, or set_fields (value: {title id: fields}, the undo). Returns each title's previous values -- send them back with set_fields to undo. Deletes are soft and restorable.",
        bulk_edit_titles,
        schema({"ids": TITLE_IDS, "op": {"type": "string", "enum": ["set_type", "add_tags", "remove_tags", "delete", "restore", "set_fields"]}, "value": {}}, ("ids", "op")),
        destructive=True,
    )
    add(
        "update_title", "POST /api/titles/{title_id}/update", "Edit a title",
        "Change shared details of a title (title, year, type, tags, notes, links, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url). Returns the previous values.",
        update_title, schema({"title_id": TITLE_ID, "set": {"type": "object"}, "expect": EXPECT}, ("title_id", "set")),
    )
    add(
        "delete_title", "POST /api/titles/{title_id}/delete", "Delete a title",
        "Take a title out of the library for everyone. Soft: restore_title brings it back within the undo window.",
        delete_title, schema({"title_id": TITLE_ID}, ("title_id",)), destructive=True,
    )
    add("restore_title", "POST /api/titles/{title_id}/restore", "Restore a title", "Bring back a deleted title, within the undo window.", restore_title, schema({"title_id": TITLE_ID}, ("title_id",)))
    add(
        "enrich_title", "POST /api/titles/{title_id}/enrich", "Fill a title in",
        "Look the title up with the configured providers now and fill in missing details (refresh: true overwrites what is there). Returns the previous values.",
        enrich_title, schema({"title_id": TITLE_ID, "refresh": {"type": "boolean"}}, ("title_id",)),
    )
    add(
        "merge_titles", "POST /api/titles/{title_id}/merge", "Merge duplicates",
        "Keep title_id and fold the drop_ids into it: everyone's state, playlists and details move over and the others are deleted. One undo step: undo_merge with the merge_id returned.",
        merge_titles, schema({"title_id": {"type": "string", "description": "The title to keep."}, "drop_ids": TITLE_IDS}, ("title_id", "drop_ids")), destructive=True,
    )
    add("list_duplicates", "GET /api/dupes", "Possible duplicates", "Groups of library titles that look like the same work, minus pairs marked as different.", list_duplicates, read_only=True)
    add("dismiss_duplicates", "POST /api/dupes/dismiss", "Not duplicates", "Mark two or more titles as not the same, for the whole family. Returns the pairs, which undismiss_duplicates takes back.", dismiss_duplicates, schema({"ids": TITLE_IDS}, ("ids",)))
    add("undismiss_duplicates", "POST /api/dupes/undismiss", "Undo not duplicates", "Forget pairs dismiss_duplicates recorded.", undismiss_duplicates, schema({"pairs": {"type": "array", "items": {"type": "string"}}}, ("pairs",)))
    add("undo_merge", "POST /api/merges/{merge_id}/undo", "Undo a merge", "Put a merge back as it was: the dropped titles, and everyone's state and playlists.", undo_merge, schema({"merge_id": {"type": "string", "description": "From merge_titles."}}, ("merge_id",)))

    # State.
    add(
        "set_state", "POST /api/state/{title_id}", "Set status, rating or heart",
        "Change one person's state on a title: status (queue, watching, watched, dropped, or null for off the list), rating 1-10 or null, heart true/false, note, watched_at. Returns the previous values.",
        set_state, schema({"title_id": TITLE_ID, "set": {"type": "object"}, "expect": EXPECT, "user_id": USER}, ("title_id", "set")),
    )
    add(
        "set_states", "POST /api/state/bulk", "Set state on many titles",
        "changes is {title id: {status, rating, heart, note, watched_at}}, up to 2000 titles. Returns each title's previous values, which sent back are the undo.",
        set_states, schema({"changes": {"type": "object"}, "user_id": USER}, ("changes",)),
    )

    # Lookups and import.
    add(
        "lookup", "POST /api/resolve", "Look a title up",
        "Identify a name, name and year, or link (IMDb, Wikipedia, TMDB, TVmaze...) with the configured providers, and say whether the library already has it. Writes nothing. Counts against the same per-person lookup allowance as the Add screen.",
        lookup, schema({"text": {"type": "string"}, "kind": {"type": "string", "description": "movie, tv, book, ... or any."}}, ("text",)), read_only=True,
    )
    add(
        "import_parse", "POST /api/import/parse", "Read an import",
        "Read a pasted list or file's text (format auto, outline, csv or json) into rows of title fields, each with its likeliest duplicate. Writes nothing: send the rows you want to import_items.",
        import_parse, schema({"text": {"type": "string"}, "format": {"type": "string"}, "type": {"type": "string"}, "status": {"type": "string"}}, ("text",)), read_only=True,
    )
    add(
        "import_items", "POST /api/import/items", "Import titles",
        "Create titles from rows ({fields, state}, at most 200 per call), skipping any the library certainly has unless skip_dupes is false, and put them on the person's lists. Send the same batch_id for every call of one import; undo_import takes the whole batch back.",
        import_items, schema({"rows": {"type": "array", "items": {"type": "object"}}, "batch_id": {"type": "string"}, "skip_dupes": {"type": "boolean"}, "user_id": USER}, ("rows",)),
    )
    add(
        "undo_import", "POST /api/import/{batch_id}/undo", "Undo an import",
        "Delete the titles one import created, and the importer's state on them.",
        undo_import, schema({"batch_id": {"type": "string", "description": "From import_items."}}, ("batch_id",)), destructive=True,
    )

    # Discover.
    add(
        "discover_search", "GET /api/discover", "Search Discover",
        "The Wikipedia film catalogue, minus films you skipped. genres is comma-separated; sort is notable, imdb, year, year-asc or title. Each film says whether it is already in the library (title_id) and your status on it.",
        discover_search,
        schema({"text": {"type": "string"}, "year_from": {"type": "integer"}, "year_to": {"type": "integer"}, "genres": {"type": "string"}, "sort": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "user_id": USER}),
        read_only=True,
    )
    add("discover_meta", "GET /api/discover/meta", "Discover catalogue", "What the Discover catalogue holds: its source lists and topics, coverage, and rating counts.", discover_meta, read_only=True)
    add(
        "discover_facts", "GET /api/discover/facts", "Discover film details",
        "Plot, cast and poster for up to 60 catalogue films, by Wikipedia article name (the film's url ends in it).",
        discover_facts, schema({"articles": {"type": "array", "items": {"type": "string"}, "maxItems": 60}}, ("articles",)), read_only=True,
    )
    add("set_verdict", "POST /api/discover/verdict", "Skip a Discover film", "verdict: skip (hide it from you), seen, or leave it out to clear.", set_verdict, schema({"key": {"type": "string"}, "verdict": {"type": "string"}, "expect": EXPECT, "user_id": USER}, ("key",)))
    add(
        "discover_add", "POST /api/discover/add", "Add a Discover film",
        "Add a film from discover_search (pass the film object as returned) to the library, with its Wikipedia details. status: watched for Seen it, or leave out for no list. Refuses with possible duplicates unless force is true.",
        discover_add, schema({"film": {"type": "object"}, "status": {"type": "string"}, "force": {"type": "boolean"}, "user_id": USER}, ("film",)),
    )

    # Background jobs.
    add("jobs_status", "GET /api/jobs", "Background jobs", "What the server is doing in the background (filling in titles, IMDb ratings, the catalogue), the poster cache, and whether lookups are on.", jobs_status, read_only=True)
    add(
        "admin_start_job", "POST /api/jobs/{name}/start", "Start a job (admin)",
        "Start a background job by its name from jobs_status (one marked manual). options are the job's own settings. Each job can make thousands of outbound calls.",
        admin_start_job, schema({"name": {"type": "string"}, "options": {"type": "object"}}, ("name",)), admin_only=True,
    )
    add("admin_stop_job", "POST /api/jobs/{name}/stop", "Stop a job (admin)", "Ask a running background job to stop.", admin_stop_job, schema({"name": {"type": "string"}}, ("name",)), admin_only=True)

