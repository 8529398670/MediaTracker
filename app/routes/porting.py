"""Import and export. An import creates titles (skipping any the library
certainly has already), puts them on the importer's own list with the status
the file gave them, remembers which titles it created so the whole import is
one undo, and queues them for filling in. An export is the library plus one
person's state, as JSON, CSV or a Markdown outline."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.core.db import Store
from app.core.security import actor_from
from app.media import dupes, normalize, porting
from app.models import import_batches, library_cache, titles, user_state, users
from app.models.revision import NotFoundError
from app.routes.helpers import bad_request, get_config, get_store, not_found, run
from app.routes.subject import subject_from
from app.routes.titles import _body

MAX_ROWS = 200


async def parse(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    text = str(body.get("text") or "")
    fmt = body.get("format") if body.get("format") in porting.FORMATS else "auto"
    try:
        parsed = porting.parse(text, fmt, normalize.type_id(body.get("type") or "movie"), body.get("status") if body.get("status") in normalize.STATUSES else "queue")
    except ValueError as error:
        return bad_request(str(error))
    snapshot = await run(library_cache.get, get_store(request))
    live = snapshot.live_titles()
    for entry in parsed["rows"]:
        found = dupes.find_matches(entry["fields"], live, minimum=dupes.SIMILAR, limit=1)
        entry["dupe"] = {**found[0], "title": snapshot.titles[found[0]["id"]]["title"]} if found else None
    return JSONResponse(parsed)


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


async def import_items(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    rows = [entry for entry in body.get("rows") or [] if isinstance(entry, dict)]
    if not rows:
        return bad_request("nothing to import")
    if len(rows) > MAX_ROWS:
        return bad_request(f"at most {MAX_ROWS} rows per request")
    batch_id = str(body.get("batch_id") or "") or import_batches.new_batch_id()
    try:
        result = await run(import_rows, get_store(request), get_config(request), actor_from(request).user.id, subject, rows, batch_id, body.get("skip_dupes", True) is not False)
    except titles.TooManyTitlesError as error:
        return bad_request(str(error))
    return JSONResponse(result)


async def undo_import(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        removed = await run(import_batches.undo_batch, get_store(request), request.path_params["batch_id"], actor_from(request).user.id)
    except NotFoundError:
        return not_found("no such import")
    return JSONResponse({"removed": removed})


def export_body(store: Store, subject_id: int, fmt: str) -> tuple[bytes, str, str]:
    snapshot = library_cache.get(store)
    person = users.get_user(store, subject_id)
    return porting.export(list(snapshot.titles.values()), snapshot.states_for(subject_id), snapshot.types, fmt, person.display_name if person else str(subject_id))


async def export(request: Request) -> Response:
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    fmt = request.query_params.get("format", "json")
    if fmt not in ("json", "csv", "md"):
        return bad_request("format must be json, csv or md")
    data, media_type, ext = await run(export_body, get_store(request), subject, fmt)
    return Response(data, media_type=media_type, headers={"content-disposition": f'attachment; filename="media-tracker.{ext}"'})
