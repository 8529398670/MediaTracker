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
from app.routes.helpers import Refused, bad_request, forbidden, get_config, get_store, read_json, restore_refusal, run
from app.routes.subject import subject_from

MAX_BULK = 2000


async def _body(request: Request) -> dict[str, Any] | Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    return body


async def answer(request: Request, helper: Any, *args: Any, status: int = 200) -> Response:
    """Run a helper an MCP tool shares, in a worker thread, and send what it
    returns, or the Refused it raised, the same way every time. Only
    Refused.internal (500) is logged as a server error; a deliberate 503 such
    as lookups_off is answered as itself."""
    try:
        return JSONResponse(await run(helper, *args), status_code=status)
    except Refused as refused:
        return refused.response(request if refused.status == 500 else None)


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


def create_checked(store: Store, cfg: Config, actor_id: int, subject_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/titles, shared with MCP."""
    try:
        result = add_title(store, cfg, actor_id, subject_id, body.get("title") or {}, body.get("state") or {}, bool(body.get("force")))
    except (ValueError, titles.TooManyTitlesError) as error:
        raise Refused(400, str(error)) from None
    if not result["created"]:
        raise Refused(409, "possible_duplicate", dupes=result["dupes"])
    return result


async def create(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    subject = await subject_from(request)
    if isinstance(subject, Response):
        return subject
    return await answer(request, create_checked, get_store(request), get_config(request), actor_from(request).user.id, subject, body, status=201)


def get_one_checked(store: Store, title_id: str) -> dict[str, Any]:
    record = titles.get_title(store, title_id)
    if record is None:
        raise Refused(404, "no such title")
    return record


async def get_one(request: Request) -> Response:
    return await answer(request, get_one_checked, get_store(request), request.path_params["title_id"])


def update_checked(store: Store, title_id: str, body: dict[str, Any], actor_id: int) -> dict[str, Any]:
    """POST /api/titles/{title_id}/update, shared with MCP."""
    changes = normalize.clean_title_fields(body.get("set") or {})
    if not changes:
        raise Refused(400, "nothing to change")
    try:
        record, previous = titles.update_title(store, title_id, changes, body.get("expect"), actor_id)
    except NotFoundError:
        raise Refused(404, "no such title") from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    except ValueError as error:
        raise Refused(400, str(error)) from None
    return {"title": record, "previous": previous}


async def update(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, update_checked, get_store(request), request.path_params["title_id"], body, actor_from(request).user.id)


def delete_checked(store: Store, title_id: str, actor_id: int) -> dict[str, Any]:
    try:
        return {"title": titles.delete_title(store, title_id, actor_id)}
    except NotFoundError:
        raise Refused(404, "no such title") from None


async def delete(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, delete_checked, get_store(request), request.path_params["title_id"], actor_from(request).user.id)


def restore_checked(store: Store, title_id: str, restore_days: int) -> dict[str, Any]:
    try:
        return {"title": titles.restore_title(store, title_id, restore_days)}
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None


async def restore(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, restore_checked, get_store(request), request.path_params["title_id"], get_config(request).library.restore_days)


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


def bulk_checked(store: Store, actor_id: int, body: dict[str, Any], restore_days: int) -> dict[str, Any]:
    """POST /api/titles/bulk, shared with MCP."""
    ids = [ident for ident in body.get("ids") or [] if normalize.valid_title_id(ident)][:MAX_BULK]
    if not ids:
        raise Refused(400, "no titles given")
    try:
        return bulk_titles(store, actor_id, ids, str(body.get("op") or ""), body.get("value"), restore_days)
    except ValueError as error:
        raise Refused(400, str(error)) from None


async def bulk(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, bulk_checked, get_store(request), actor_from(request).user.id, body, get_config(request).library.restore_days)


def check_checked(store: Store, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/titles/check, shared with MCP: {matches: [...]}, nothing written."""
    fields = normalize.clean_title_fields(body.get("title") or {})
    if not fields.get("title"):
        raise Refused(400, "a title needs a name")
    return {"matches": check_dupes(store, fields)}


async def check(request: Request) -> Response:
    """Would adding this make a duplicate? {matches: [...]}, nothing written."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await answer(request, check_checked, get_store(request), body)
