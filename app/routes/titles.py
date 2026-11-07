"""Titles: add, edit, delete, restore, and bulk changes to the shared
library. Any signed-in person may do all of it -- the library is the
family's -- and every change says who made it (updated_by).

Adding checks for duplicates first and answers 409 {dupes} rather than
creating a second copy, unless the caller says force.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.core.db import BUCKET_TITLES, Store
from app.core.security import actor_from, check_csrf
from app.media import dupes, normalize
from app.models import RestoreError, library_cache, titles, user_state
from app.models.revision import ConflictError, NotFoundError, bump
from app.routes.helpers import bad_request, conflict, forbidden, get_config, get_store, not_found, read_json, restore_refused, run
from app.routes.subject import subject_from

MAX_BULK = 2000


async def _body(request: Request) -> dict[str, Any] | Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    return body


def check_dupes(store: Store, fields: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = library_cache.get(store)
    matches = dupes.find_matches(fields, snapshot.live_titles(), minimum=dupes.REMAKE, limit=4)
    return [{**match, "title": snapshot.titles[match["id"]]} for match in matches]


def add_title(store: Store, cfg: Config, actor_id: int, subject_id: int, raw: dict[str, Any], state: dict[str, Any], force: bool) -> dict[str, Any]:
    """Shared with the MCP add_title tool and the importer."""
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


async def create(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    actor = actor_from(request)
    try:
        result = await run(
            add_title, get_store(request), get_config(request), actor.user.id, subject,
            body.get("title") or {}, body.get("state") or {}, bool(body.get("force")),
        )
    except (ValueError, titles.TooManyTitlesError) as error:
        return bad_request(str(error))
    if not result["created"]:
        return conflict("possible_duplicate", dupes=result["dupes"])
    return JSONResponse(result, status_code=201)


async def get_one(request: Request) -> Response:
    record = await run(titles.get_title, get_store(request), request.path_params["title_id"])
    if record is None:
        return not_found("no such title")
    return JSONResponse(record)


async def update(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    changes = normalize.clean_title_fields(body.get("set") or {})
    if not changes:
        return bad_request("nothing to change")
    try:
        record, previous = await run(
            titles.update_title, get_store(request), request.path_params["title_id"], changes, body.get("expect"), actor_from(request).user.id
        )
    except NotFoundError:
        return not_found("no such title")
    except ConflictError as error:
        return conflict("changed_elsewhere", current=error.current)
    except ValueError as error:
        return bad_request(str(error))
    return JSONResponse({"title": record, "previous": previous})


async def delete(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        record = await run(titles.delete_title, get_store(request), request.path_params["title_id"], actor_from(request).user.id)
    except NotFoundError:
        return not_found("no such title")
    return JSONResponse({"title": record})


async def restore(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        record = await run(titles.restore_title, get_store(request), request.path_params["title_id"], get_config(request).library.restore_days)
    except RestoreError as refusal:
        return restore_refused(refusal)
    return JSONResponse({"title": record})


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


async def bulk(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    ids = [ident for ident in body.get("ids") or [] if normalize.valid_title_id(ident)][:MAX_BULK]
    if not ids:
        return bad_request("no titles given")
    try:
        result = await run(
            bulk_titles, get_store(request), actor_from(request).user.id, ids, str(body.get("op") or ""), body.get("value"), get_config(request).library.restore_days
        )
    except ValueError as error:
        return bad_request(str(error))
    return JSONResponse(result)


async def check(request: Request) -> Response:
    """Would adding this make a duplicate? {matches: [...]}, nothing written."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    fields = normalize.clean_title_fields(body.get("title") or {})
    if not fields.get("title"):
        return bad_request("a title needs a name")
    return JSONResponse({"matches": await run(check_dupes, get_store(request), fields)})
