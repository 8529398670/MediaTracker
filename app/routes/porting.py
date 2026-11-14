"""Import and export. An import creates titles (skipping any the library
certainly has already), puts them on the importer's own list with the status
the file gave them, remembers which titles it created so the whole import is
one undo, and queues them for filling in. An export is the library plus one
person's state, as JSON, CSV or a Markdown outline."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from msgspec import Meta
from starlette.requests import Request
from starlette.responses import Response

from app.apidocs import PATH, QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.config import Config
from app.core.db import Store
from app.core.security import actor_from
from app.media import dupes, normalize, porting
from app.models import import_batches, library_cache, titles, user_state, users
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_config, get_store, run
from app.routes.subject import User, subject_of
from app.routes.titles import TAG, Record

MAX_ROWS = 200


class ParseImport(RequestType, kw_only=True):
    text: Annotated[str, Meta(description="A pasted list, or a file's text.")]
    format: Annotated[str, Meta(description="auto, outline, csv or json. Default auto.")] = "auto"
    type: Annotated[str, Meta(description="The type id titles without one get. Default movie.")] = "movie"
    status: Annotated[str, Meta(description="The status rows without one get: queue, watching, watched or dropped. Default queue.")] = "queue"


@route(
    "POST /api/import/parse", summary="Read an import",
    tag=TAG,
    description="Read a pasted list or a file's text (format auto, outline, csv or json) into rows of title "
    "fields, each with its likeliest duplicate (dupe). Writes nothing: send the rows wanted to "
    "POST /api/import/items.",
    mcp="import_parse", read_only=True,
)
def parse(request: Request, body: ParseImport) -> dict[str, Any]:
    fmt = body.format if body.format in porting.FORMATS else "auto"
    status = body.status if body.status in normalize.STATUSES else "queue"
    try:
        parsed = porting.parse(body.text, fmt, normalize.type_id(body.type or "movie"), status)
    except ValueError as error:
        raise Refused(400, str(error)) from None
    snapshot = library_cache.get(get_store(request))
    live = snapshot.live_titles()
    for entry in parsed["rows"]:
        found = dupes.find_matches(entry["fields"], live, minimum=dupes.SIMILAR, limit=1)
        entry["dupe"] = {**found[0], "title": snapshot.titles[found[0]["id"]]["title"]} if found else None
    return parsed


def import_rows(store: Store, cfg: Config, actor_id: int, subject_id: int, rows: list[dict[str, Any]], batch_id: str, skip_dupes: bool) -> dict[str, Any]:
    created: list[str] = []
    skipped = 0
    live = library_cache.get(store).live_titles()
    for entry in rows:
        fields = normalize.clean_title_fields(entry.get("fields") or {})
        if not fields.get("title"):
            skipped += 1
            continue
        if skip_dupes and dupes.find_matches(fields, live, minimum=dupes.CERTAIN, limit=1):
            skipped += 1
            continue
        record = titles.create_title(store, fields, actor_id, cfg.library.max_titles)
        state = {key: value for key, value in normalize.clean_state_fields(entry.get("state") or {}).items() if not normalize.is_empty(value)}
        if state:
            user_state.set_state(store, subject_id, record["id"], state, None, actor_id)
        created.append(record["id"])
        live.append(record)
    import_batches.record_created(store, batch_id, subject_id, created, actor_id)
    if created and cfg.jobs.enrich_on_add:
        from app.jobs import enrich_job

        enrich_job.queue_titles(created)
    return {"batch_id": batch_id, "created": len(created), "skipped": skipped}


class ImportItems(RequestType, kw_only=True):
    rows: Annotated[list[Record], Meta(description="Up to 200 rows, each {fields, state}, as POST /api/import/parse gives them.")]
    batch_id: Annotated[str, Meta(description="The same for every call of one import, so it is undone as one. Default: a new one.")] = ""
    skip_dupes: Annotated[bool, Meta(description="Skip rows the library certainly has. Default true.")] = True
    user: User = None


class Imported(Reply, kw_only=True):
    batch_id: str
    created: int
    skipped: int


@route(
    "POST /api/import/items", summary="Import titles",
    tag=TAG,
    description="Create titles from rows ({fields, state}, at most 200 per call), skipping any the library "
    "certainly has unless skip_dupes is false, and put them on the person's lists. Send the same batch_id "
    "for every call of one import; undoing the import takes the whole batch back.",
    mcp="import_items",
)
def import_items(request: Request, body: ImportItems) -> Imported:
    subject = subject_of(request, body.user)
    rows = [entry for entry in body.rows if isinstance(entry, dict)]
    if not rows:
        raise Refused(400, "nothing to import")
    if len(rows) > MAX_ROWS:
        raise Refused(400, f"at most {MAX_ROWS} rows per request")
    store = get_store(request)
    batch_id = body.batch_id or import_batches.new_batch_id()
    try:
        return Imported(**import_rows(store, get_config(request), actor_from(request).user.id, subject, rows, batch_id, body.skip_dupes))
    except titles.TooManyTitlesError as error:
        raise Refused(400, str(error)) from None


class BatchPath(RequestType, kw_only=True):
    batch_id: Annotated[str, PATH, Meta(description="From POST /api/import/items.")]


class ImportUndone(Reply, kw_only=True):
    removed: Annotated[int, Meta(description="Titles taken back out.")]


@route(
    "POST /api/import/{batch_id}/undo", summary="Undo an import",
    tag=TAG, errors=(404,),
    description="Delete the titles one import created, and the importer's state on them.",
    mcp="undo_import", destructive=True,
)
def undo_import(request: Request, body: BatchPath) -> ImportUndone:
    try:
        return ImportUndone(removed=import_batches.undo_batch(get_store(request), body.batch_id, actor_from(request).user.id))
    except NotFoundError:
        raise Refused(404, "no such import") from None


def export_body(store: Store, subject_id: int, fmt: str) -> tuple[bytes, str, str]:
    snapshot = library_cache.get(store)
    person = users.get_user(store, subject_id)
    return porting.export(list(snapshot.titles.values()), snapshot.states_for(subject_id), snapshot.types, fmt, person.display_name if person else str(subject_id))


class Export(RequestType, kw_only=True):
    format: Annotated[Literal["json", "csv", "md"], QUERY, Meta(description="Default json.", extra={"error": "format must be json, csv or md"})] = "json"
    user: User = None


@route(
    "GET /api/export", summary="Export the library",
    tag=TAG, reply_type="application/octet-stream",
    description="The library with one person's state, as a JSON, CSV or Markdown outline download.",
    mcp_http="a file download",
)
async def export(request: Request, body: Export) -> Response:
    subject = await run(subject_of, request, body.user)
    data, media_type, ext = await run(export_body, get_store(request), subject, body.format)
    return Response(data, media_type=media_type, headers={"content-disposition": f'attachment; filename="media-tracker.{ext}"'})
