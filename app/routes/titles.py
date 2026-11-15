"""Titles: add, edit, delete, restore, and bulk changes to the shared
library. Any signed-in person may do all of it -- the library is the
family's -- and every change says who made it (updated_by).

Adding checks for duplicates first and answers 409 {dupes} rather than
creating a second copy, unless the caller says force.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable, Literal

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import PATH, Reply, route
from app.apidocs import Request as RequestType
from app.core.config import Config
from app.core.db import BUCKET_TITLES, Store
from app.core.security import actor_from
from app.mcp.registry import Call
from app.media import dupes, normalize
from app.models import RestoreError, library_cache, titles, user_state
from app.models.revision import ConflictError, NotFoundError, bump
from app.routes.helpers import Refused, get_config, get_store, restore_refusal
from app.routes.subject import User, subject_of

MAX_BULK = 2000

TAG = "Library"

TitleID = Annotated[str, PATH, Meta(description="A title's id, from GET /api/library (search_library over MCP).")]
TitleFields = Annotated[dict[str, Any], Meta(description="Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored.")]
StateFields = Annotated[dict[str, Any], Meta(description="A person's state: status (queue, watching, watched, dropped, or null), rating 1-10 or null, heart, note, watched_at.")]
Expect = Annotated[Any, Meta(description="Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value.")]
Record = dict[str, Any]


def check_dupes(store: Store, fields: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = library_cache.get(store)
    matches = dupes.find_matches(fields, snapshot.live_titles(), minimum=dupes.REMAKE, limit=4)
    return [{**match, "title": snapshot.titles[match["id"]]} for match in matches]


def dupe_rows(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Possible duplicates as an agent wants them: id, name, year, score."""
    return [{"id": dupe["id"], "title": dupe["title"]["title"], "year": dupe["title"].get("year"), "score": dupe["score"]} for dupe in found]


def add_title(store: Store, cfg: Config, actor_id: int, subject_id: int, raw: dict[str, Any], state: dict[str, Any], force: bool) -> dict[str, Any]:
    """Shared with Discover's add and the importer."""
    fields = normalize.clean_title_fields(raw)
    if not fields.get("title"):
        raise ValueError("a title needs a name")
    if not force:
        found = check_dupes(store, fields)
        if any(match["score"] >= dupes.SIMILAR for match in found):
            return {"created": False, "dupes": found}
    record = titles.create_title(store, fields, actor_id, cfg.library.max_titles)
    changes = normalize.clean_state_fields(state) or {"status": "queue"}
    saved, _previous = user_state.set_state(store, subject_id, record["id"], changes, None, actor_id)
    if cfg.jobs.enrich_on_add:
        from app.jobs import enrich_job

        enrich_job.queue_titles([record["id"]])
    return {"created": True, "title": record, "state": saved}


def when_created(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of a tool that adds a title: a possible duplicate is an
    answer, not an error, so the agent can use the existing title or try
    again with force."""
    try:
        result = serve(call.request, body)
    except Refused as refused:
        if refused.status != 409 or "dupes" not in refused.extra:
            raise
        return {"created": False, "possible_duplicates": dupe_rows(refused.extra["dupes"]), "hint": "Use the existing title, or call again with force: true."}
    return {"created": True, "title": result.title, "state": result.state}


class CreateTitle(RequestType, kw_only=True):
    title: TitleFields
    state: StateFields = {}
    force: Annotated[bool, Meta(description="Add it even if it looks like a title the library has.")] = False
    user: User = None


class TitleCreated(Reply, kw_only=True):
    created: bool
    title: Record
    state: Record


@route(
    "POST /api/titles", summary="Add a title",
    tag=TAG, status=201, errors=(404, 409),
    description="Add a title to the family library and put it on a person's list (state.status: queue by "
    "default). Refused with 409 possible_duplicate and the dupes it resembles unless force is true. Details "
    "are filled in in the background.",
    mcp_note="A possible duplicate answers created: false with possible_duplicates instead.",
    mcp="add_title", call=when_created,
)
def create(request: Request, body: CreateTitle) -> TitleCreated:
    subject = subject_of(request, body.user)
    try:
        result = add_title(get_store(request), get_config(request), actor_from(request).user.id, subject, body.title, body.state, body.force)
    except (ValueError, titles.TooManyTitlesError) as error:
        raise Refused(400, str(error)) from None
    if not result["created"]:
        raise Refused(409, "possible_duplicate", dupes=result["dupes"])
    return TitleCreated(created=True, title=result["title"], state=result["state"])


def check_checked(store: Store, raw: dict[str, Any]) -> dict[str, Any]:
    """Would adding this make a duplicate? {matches: [...]}, nothing written."""
    fields = normalize.clean_title_fields(raw)
    if not fields.get("title"):
        raise Refused(400, "a title needs a name")
    return {"matches": check_dupes(store, fields)}


def compact_matches(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    return {"matches": dupe_rows(serve(call.request, body).matches)}


class CheckTitle(RequestType, kw_only=True):
    title: TitleFields


class CheckReply(Reply, kw_only=True):
    matches: Annotated[list[Record], Meta(description="Library titles it resembles, each with its score and the title.")]


@route(
    "POST /api/titles/check", summary="Check for a duplicate",
    tag=TAG,
    description="Would adding this title make a duplicate? The library titles it resembles, with a score. "
    "Writes nothing.",
    mcp="check_title", read_only=True, call=compact_matches,
)
def check(request: Request, body: CheckTitle) -> CheckReply:
    return CheckReply(**check_checked(get_store(request), body.title))


class TitlePath(RequestType, kw_only=True):
    title_id: TitleID


class GetTitle(TitlePath, kw_only=True):
    user: User = None


@route(
    "GET /api/titles/{title_id}", summary="Get a title",
    tag=TAG, errors=(404,),
    description="Everything about one title, with the person's state on it (my_state) and who in the family "
    "has watched or loved it (family).",
    mcp="get_title", read_only=True,
)
def get_one(request: Request, body: GetTitle) -> dict[str, Any]:
    from app.routes.library import state_row

    store = get_store(request)
    subject = subject_of(request, body.user)
    record = titles.get_title(store, body.title_id)
    if record is None:
        raise Refused(404, "no such title")
    snapshot = library_cache.get(store)
    mine = snapshot.states_for(subject)
    state = mine.get(body.title_id)
    return {**record, "my_state": state_row(state) if state else None, "family": snapshot.social.get(body.title_id)}


class UpdateTitle(TitlePath, kw_only=True):
    set: TitleFields
    expect: Expect = None


class TitleChange(Reply, kw_only=True):
    title: Record
    previous: Annotated[Record, Meta(description="What the changed fields were before: send them back to undo.")]


@route(
    "POST /api/titles/{title_id}/update", summary="Edit a title",
    tag=TAG, errors=(404, 409),
    description="Change shared details of a title (title, year, type, tags, notes, links, genres, cast, "
    "creator, runtime, certification, imdb_id, wiki_url, poster_url). Returns the previous values.",
    mcp="update_title",
    bulk=True,
)
def update(request: Request, body: UpdateTitle) -> TitleChange:
    changes = normalize.clean_title_fields(body.set)
    if not changes:
        raise Refused(400, "nothing to change")
    try:
        record, previous = titles.update_title(get_store(request), body.title_id, changes, body.expect, actor_from(request).user.id)
    except NotFoundError:
        raise Refused(404, "no such title") from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    except ValueError as error:
        raise Refused(400, str(error)) from None
    return TitleChange(title=record, previous=previous)


class TitleReply(Reply, kw_only=True):
    title: Record


@route(
    "POST /api/titles/{title_id}/delete", summary="Delete a title",
    tag=TAG, errors=(404,),
    description="Take a title out of the library for everyone. Soft: restoring it brings it back within the "
    "undo window.",
    mcp="delete_title", destructive=True,
)
def delete(request: Request, body: TitlePath) -> TitleReply:
    try:
        return TitleReply(title=titles.delete_title(get_store(request), body.title_id, actor_from(request).user.id))
    except NotFoundError:
        raise Refused(404, "no such title") from None


@route(
    "POST /api/titles/{title_id}/restore", summary="Restore a title",
    tag=TAG, errors=(403, 404, 409),
    description="Bring back a deleted title, within the undo window.",
    mcp="restore_title",
)
def restore(request: Request, body: TitlePath) -> TitleReply:
    try:
        return TitleReply(title=titles.restore_title(get_store(request), body.title_id, get_config(request).library.restore_days))
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None


def bulk_titles(store: Store, actor_id: int, ids: list[str], op: str, value: Any, restore_days: int) -> dict[str, Any]:
    """One change to many titles in one transaction. Returns what each title
    had before, so the client's undo can put exactly that back."""
    previous: dict[str, Any] = {}
    with store.transaction() as tx:
        rev = bump(tx)
        for title_id in ids:
            if op == "delete":
                record = tx.get(BUCKET_TITLES, title_id)
                if record is not None and record.get("deleted_at") is None:
                    titles.delete_title_tx(tx, title_id, actor_id, rev)
                    previous[title_id] = True
                continue
            if op == "restore":
                try:
                    titles.restore_title_tx(tx, title_id, restore_days, rev)
                    previous[title_id] = True
                except RestoreError:
                    pass
                continue
            record = tx.get(BUCKET_TITLES, title_id)
            if record is None or record.get("deleted_at") is not None:
                continue
            before = {"type": record.get("type"), "tags": list(record.get("tags") or [])}
            if op == "set_type":
                record["type"] = normalize.type_id(value)
            elif op == "add_tags":
                record["tags"] = normalize.tags([*record.get("tags", []), *normalize.tags(value)])
            elif op == "remove_tags":
                gone = set(normalize.tags(value))
                record["tags"] = [tag for tag in record.get("tags", []) if tag not in gone]
            elif op == "set_fields":
                # The undo of a bulk change: each title's own previous values.
                record.update(normalize.clean_title_fields((value or {}).get(title_id) or {}))
            else:
                raise ValueError(f"unknown bulk operation {op!r}")
            if record.get("type") != before["type"] or record.get("tags") != before["tags"]:
                record["rev"] = rev
                record["updated_by"] = actor_id
                tx.put(BUCKET_TITLES, title_id, record)
                previous[title_id] = before
    return {"previous": previous}


class BulkTitles(RequestType, kw_only=True):
    ids: Annotated[list[str], Meta(description="Title ids, at most 2000.")]
    op: Annotated[Literal["set_type", "add_tags", "remove_tags", "delete", "restore", "set_fields"], Meta(description="The change.")]
    value: Annotated[Any, Meta(description="set_type: a type id. add_tags, remove_tags: a list of tags. set_fields: {title id: fields}, the undo.")] = None


class BulkReply(Reply, kw_only=True):
    previous: Annotated[Record, Meta(description="Each changed title's previous values, by id: sent back with set_fields, the undo.")]


@route(
    "POST /api/titles/bulk", summary="Change many titles",
    tag=TAG,
    description="One change to many titles at once. op: set_type (value: a type id), add_tags or remove_tags "
    "(value: a list of tags), delete, restore, or set_fields (value: {title id: fields}, the undo). Returns "
    "each title's previous values; send them back with set_fields to undo. Deletes are soft and restorable.",
    mcp="bulk_edit_titles", destructive=True,
)
def bulk(request: Request, body: BulkTitles) -> BulkReply:
    ids = [ident for ident in body.ids if normalize.valid_title_id(ident)][:MAX_BULK]
    if not ids:
        raise Refused(400, "no titles given")
    try:
        result = bulk_titles(get_store(request), actor_from(request).user.id, ids, body.op, body.value, get_config(request).library.restore_days)
    except ValueError as error:
        raise Refused(400, str(error)) from None
    return BulkReply(**result)

