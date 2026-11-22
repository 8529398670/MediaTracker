"""A person's suggestion lists: like playlists, but an item can be a Discover
film not in the library yet, and carries a note saying why it was suggested.
Agents fill them over MCP for the person to import from. Every route takes
?user= (see subject.py).

Item changes answer {suggestion_list, previous_items}; previous_items is what the undo
sends back to /set.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import PATH, QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.db import Store
from app.core.security import actor_from
from app.discover import catalogue
from app.mcp.registry import Call
from app.media import dupes
from app.models import RestoreError, library_cache, suggestions, verdicts
from app.models.revision import NotFoundError
from app.routes.discover import attach_known_facts, catalogue_key_for, library_index
from app.routes.helpers import Refused, get_store, restore_refusal
from app.routes.library import state_row
from app.routes.prefs import Deleted, OkReply, Reorder
from app.routes.subject import User, subject_of

TAG = "Suggestions"
Record = dict[str, Any]
TitleIDs = Annotated[list[str], Meta(description="Library title ids, from GET /api/library (search_library over MCP).")]
FilmKeys = Annotated[list[str], Meta(description="Discover film keys, from GET /api/discover (discover_search over MCP).")]
Note = Annotated[str, Meta(max_length=200, description="Why it is suggested, in a line: shown under the card.")]
Position = Annotated[Annotated[int, Meta(ge=1)] | None, Meta(description="1-based; the end by default.")]
Ref = Annotated[str, Meta(description="An item's ref: a title id, or cat:<film key>.")]


# -- reading a list, with each item found ----------------------------------------


class Finder:
    """Which library title an item is, and its Discover film: built once per
    request, for every list it reads."""

    def __init__(self, store: Store, subject_id: int) -> None:
        self.cache = library_cache.get(store)
        self.states = self.cache.states_for(subject_id)
        self.by_key, self.by_wiki, self.by_name = library_index(store)
        self.verdicts = verdicts.get_verdicts(store, subject_id)
        self.films: dict[str, dict[str, Any]] = {}

    def load_films(self, records: list[Record]) -> None:
        keys = {suggestions.catalogue_key(item["ref"]) for record in records for item in record["items"]} - {""}
        films = catalogue.films_by_keys(keys)
        attach_known_facts(list(films.values()))
        self.films.update(films)

    def title_for_film(self, film: dict[str, Any] | None, key: str) -> str | None:
        found = self.by_key.get(key)
        if found or not film:
            return found
        return self.by_wiki.get(dupes.wiki_key(film.get("url") or "")) or self.by_name.get(f"{dupes.norm_key(film.get('title'))}|{film.get('year') or ''}")

    def live(self, title_id: str | None) -> str | None:
        title = self.cache.titles.get(title_id) if title_id else None
        return title_id if title and not title.get("deleted_at") else None

    def resolve(self, item: dict[str, Any]) -> dict[str, Any]:
        key = suggestions.catalogue_key(item["ref"])
        film = self.films.get(key) if key else None
        title_id = self.live(self.title_for_film(film, key) if key else item["ref"])
        if film is not None:
            film = {**film, "title_id": title_id, "my_status": (self.states.get(title_id) or {}).get("status") if title_id else None,
                    "verdict": (self.verdicts.get(key) or {}).get("v")}
        return {**item, "title_id": title_id, "film": film}

    def same(self, ref: str) -> set[str]:
        """The other refs that are this film: a library title's catalogue
        key, or a catalogue film's library title."""
        key = suggestions.catalogue_key(ref)
        if key:
            title_id = self.title_for_film(self.films.get(key), key)
            return {title_id} if title_id else set()
        title = self.cache.titles.get(ref)
        return {suggestions.film_ref(catalogue_key_for(title))} if title else set()


def resolved(store: Store, subject_id: int, records: list[Record]) -> list[Record]:
    finder = Finder(store, subject_id)
    finder.load_films(records)
    return [{**record, "items": [finder.resolve(item) for item in record["items"]]} for record in records]


def resolved_one(request: Request, subject_id: int, record: Record) -> Record:
    return resolved(get_store(request), subject_id, [record])[0]


class ListSuggestions(RequestType, kw_only=True):
    list_id: Annotated[Annotated[int, Meta(ge=1)] | None, QUERY, Meta(description="Over MCP only: that one list's items, numbered in its order, instead of the lists.")] = None
    user: User = None


def compact_rows(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of list_suggestions: id, name and count for each list, or
    with list_id that list's items, numbered."""
    mine = serve(call.request, body)
    if body.list_id is None:
        return {"lists": [{"id": record["id"], "name": record["name"], "count": len(record["items"])} for record in mine]}
    found = next((record for record in mine if record["id"] == body.list_id), None)
    if found is None:
        raise Refused(404, "no such suggestion list")
    cache = library_cache.get(call.store)
    states = cache.states_for(subject_of(call.request, body.user))
    rows = []
    for number, item in enumerate(found["items"], start=1):
        film = item.get("film") or {}
        title = cache.titles.get(item["title_id"]) if item.get("title_id") else None
        state = states.get(item["title_id"]) if item.get("title_id") else None
        rows.append({
            "number": number,
            "ref": item["ref"],
            "note": item.get("note") or "",
            "title": (title or film).get("title"),
            "year": (title or film).get("year"),
            # Stored as tenths (81 for 8.1), as the cards read it.
            "imdb_score": film["imdbScore"][0] / 10 if film.get("imdbScore") else None,
            "in_library": bool(item.get("title_id")),
            "title_id": item.get("title_id"),
            "my_state": state_row(state) if state else None,
        })
    return {"id": found["id"], "name": found["name"], "items": rows}


@route(
    "GET /api/suggestions", summary="Suggestion lists",
    tag=TAG,
    description="A person's suggestion lists, in their order. Each item has its ref, note and added_at, the "
    "library title it is (title_id, or null for a Discover film not imported yet) and, for a Discover film, "
    "the film as GET /api/discover gives it.",
    mcp_description="A person's suggestion lists: id, name and how many items each holds. With list_id, that "
    "one list's items, numbered, each with its note, IMDb score and whether it is in the library yet.",
    mcp="list_suggestions", read_only=True, call=compact_rows,
)
def list_lists(request: Request, body: ListSuggestions) -> list[Record]:
    subject = subject_of(request, body.user)
    store = get_store(request)
    return resolved(store, subject, suggestions.list_lists(store, subject))


class CreateList(RequestType, kw_only=True):
    name: Annotated[str, Meta(description="Up to 80 characters.")]
    user: User = None


@route(
    "POST /api/suggestions", summary="Create a suggestion list",
    tag=TAG, status=201,
    description="A new, empty suggestion list. Fill it with add.",
    mcp="create_suggestion_list",
)
def create_list(request: Request, body: CreateList) -> Record:
    subject = subject_of(request, body.user)
    try:
        return resolved_one(request, subject, suggestions.create_list(get_store(request), subject, body.name))
    except ValueError as error:
        raise Refused(400, str(error)) from None


@route(
    "POST /api/suggestions/reorder", summary="Order suggestion lists",
    tag=TAG,
    description="Put the suggestion lists in this order (ids: every list id, first to last).",
    mcp="reorder_suggestion_lists",
)
def reorder_lists(request: Request, body: Reorder) -> OkReply:
    suggestions.reorder_lists(get_store(request), subject_of(request, body.user), body.ids)
    return OkReply(ok=True)


class ListPath(RequestType, kw_only=True):
    list_id: Annotated[int, PATH, Meta(ge=1, description="A suggestion list's id, from GET /api/suggestions.", extra={"error": "no such suggestion list"})]
    user: User = None


def _refusal(error: Exception) -> Refused:
    if isinstance(error, NotFoundError):
        return Refused(404, str(error))
    if isinstance(error, RestoreError):
        return restore_refusal(error)
    return Refused(400, str(error))


class Rename(ListPath, kw_only=True):
    name: Annotated[str, Meta(description="Up to 80 characters.")]


class Renamed(Reply, kw_only=True):
    suggestion_list: Record
    previous_name: str


@route(
    "POST /api/suggestions/{list_id}/update", summary="Rename a suggestion list",
    tag=TAG, errors=(404,),
    description="Give a suggestion list a new name. Returns the previous one.",
    mcp="rename_suggestion_list",
)
def update_list(request: Request, body: Rename) -> Renamed:
    subject = subject_of(request, body.user)
    try:
        record, old_name = suggestions.rename_list(get_store(request), subject, body.list_id, body.name)
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return Renamed(suggestion_list=resolved_one(request, subject, record), previous_name=old_name)


@route(
    "POST /api/suggestions/{list_id}/delete", summary="Delete a suggestion list",
    tag=TAG, errors=(404,),
    description="Delete a suggestion list. Soft: restoring it brings it back within the undo window.",
    mcp="delete_suggestion_list", destructive=True,
    bulk=True,
)
def delete_list(request: Request, body: ListPath) -> Deleted:
    try:
        suggestions.delete_list(get_store(request), subject_of(request, body.user), body.list_id, actor_from(request).user.id)
    except NotFoundError as error:
        raise _refusal(error) from None
    return Deleted(deleted=True)


class ListReply(Reply, kw_only=True):
    suggestion_list: Record


@route(
    "POST /api/suggestions/{list_id}/restore", summary="Restore a suggestion list",
    tag=TAG, errors=(403, 404, 409),
    description="Bring back a deleted suggestion list, within the undo window.",
    mcp="restore_suggestion_list",
    bulk=True,
)
def restore_list(request: Request, body: ListPath) -> ListReply:
    actor = actor_from(request)
    subject = subject_of(request, body.user)
    try:
        record = suggestions.restore_list(get_store(request), subject, body.list_id, actor.user.id, actor.is_admin)
    except (NotFoundError, RestoreError) as error:
        raise _refusal(error) from None
    return ListReply(suggestion_list=resolved_one(request, subject, record))


class ItemsChange(Reply, kw_only=True):
    suggestion_list: Record
    previous_items: Annotated[list[dict[str, Any]], Meta(description="The items before: what setting the items takes back.")]


def _changed(request: Request, subject: int, work: Callable[[], tuple[Record, list[dict[str, Any]]]]) -> ItemsChange:
    try:
        record, before = work()
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return ItemsChange(suggestion_list=resolved_one(request, subject, record), previous_items=before)


class AddItems(ListPath, kw_only=True):
    title_ids: TitleIDs = []
    film_keys: FilmKeys = []
    note: Note = ""
    position: Position = None


@route(
    "POST /api/suggestions/{list_id}/add", summary="Add suggestions",
    tag=TAG, errors=(404,),
    description="Suggest Discover films (film_keys) and/or library titles (title_ids) at position (the end by "
    "default), each with the note given. One already in the list stays where it is, and takes the new note. "
    "A Discover film the library already has counts as that title. Returns the items before.",
    mcp_description="Suggest films for the person to import or watch: Discover films by key (film_keys, from "
    "discover_search) and/or library titles (title_ids, from search_library), with a one-line note saying why "
    "(\"same director as Heat\"). Call once per note. One already in the list keeps its place and takes the new "
    "note. Returns the items before.",
    mcp="add_suggestions",
)
def add_items(request: Request, body: AddItems) -> ItemsChange:
    subject = subject_of(request, body.user)
    store = get_store(request)
    keys = list(dict.fromkeys(key for key in body.film_keys if key))
    known = catalogue.films_by_keys(keys)
    missing = [key for key in keys if key not in known]
    if missing:
        raise Refused(400, "no such Discover film", keys=missing[:10])
    cache = library_cache.get(store)
    gone = [ident for ident in body.title_ids if not (cache.titles.get(ident) and not cache.titles[ident].get("deleted_at"))]
    if gone:
        raise Refused(400, "no such title", title_ids=gone[:10])
    finder = Finder(store, subject)
    finder.films.update(known)
    refs = [suggestions.film_ref(key) for key in keys] + list(body.title_ids)
    return _changed(request, subject, lambda: suggestions.add_items(store, subject, body.list_id, refs, body.note, body.position, finder.same))


class RemoveItems(ListPath, kw_only=True):
    refs: Annotated[list[Ref], Meta(description="Item refs, as GET /api/suggestions gives them.")]


@route(
    "POST /api/suggestions/{list_id}/remove", summary="Remove suggestions",
    tag=TAG, errors=(404,),
    description="Take items off a suggestion list, by ref. Returns the items before.",
    mcp="remove_suggestions",
)
def remove_items(request: Request, body: RemoveItems) -> ItemsChange:
    subject = subject_of(request, body.user)
    return _changed(request, subject, lambda: suggestions.remove_items(get_store(request), subject, body.list_id, body.refs))


class MoveItem(ListPath, kw_only=True):
    ref: Ref
    position: Annotated[int, Meta(ge=1, description="1-based.")]


@route(
    "POST /api/suggestions/{list_id}/move", summary="Move a suggestion",
    tag=TAG, errors=(404,),
    description="Move one item to position; the rest renumber. Returns the items before.",
    mcp="move_suggestion",
)
def move_item(request: Request, body: MoveItem) -> ItemsChange:
    subject = subject_of(request, body.user)
    return _changed(request, subject, lambda: suggestions.move_item(get_store(request), subject, body.list_id, body.ref, body.position))


class SetNote(ListPath, kw_only=True):
    ref: Ref
    note: Note


@route(
    "POST /api/suggestions/{list_id}/note", summary="Change a suggestion's note",
    tag=TAG, errors=(404,),
    description="Replace one item's note (empty clears it). Returns the items before.",
    mcp="set_suggestion_note",
)
def set_note(request: Request, body: SetNote) -> ItemsChange:
    subject = subject_of(request, body.user)
    return _changed(request, subject, lambda: suggestions.set_note(get_store(request), subject, body.list_id, body.ref, body.note))


class SetItems(ListPath, kw_only=True):
    items: Annotated[list[dict[str, Any]], Meta(description="Every item ({ref, note, added_at}), in order.")]


@route(
    "POST /api/suggestions/{list_id}/set", summary="Set a suggestion list's items",
    tag=TAG, errors=(404,),
    description="Replace a list's items, in order: the undo of add, remove, move and note. Returns the items before.",
    mcp="set_suggestion_items",
)
def set_items(request: Request, body: SetItems) -> ItemsChange:
    subject = subject_of(request, body.user)
    return _changed(request, subject, lambda: suggestions.set_items(get_store(request), subject, body.list_id, body.items))
