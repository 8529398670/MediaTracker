"""A person's own sessions: which devices are signed in, and signing them out
(app/models/sessions.py). A session is required, so an API key gets 403, and
every id is checked against the account asking: someone else's session and one
that does not exist get the same 404. Ending the session in use is what signing
out is for.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.logs import KIND_ADMIN, KIND_AUTH
from app.core.security import actor_from, check_csrf
from app.models import sessions, to_iso, users
from app.routes.helpers import bad_request, conflict, error, forbidden, get_store, not_found, parse_id, read_json, run, send_page
from app.routes.logs import audit


def session_row(session: sessions.Session, current_id: str) -> dict[str, Any]:
    """Field by field on purpose: secret_hash and csrf_token must not reach a
    response because something later adds a loop over the record."""
    row: dict[str, Any] = {
        "id": session.id,
        "current": session.id == current_id,
        "created_at": to_iso(session.created_at),
        "expires_at": to_iso(session.expires_at),
    }
    if session.last_seen_at is not None:
        row["last_seen_at"] = to_iso(session.last_seen_at)
    if session.ip:
        row["ip"] = session.ip
    if session.user_agent:
        row["user_agent"] = session.user_agent
    if session.label:
        row["label"] = session.label
    return row


async def list_my_sessions(request: Request) -> Response:
    store, actor = get_store(request), actor_from(request)
    found = await run(sessions.list_sessions, store, actor.user.id)
    rows = [session_row(session, actor.session.id) for session in found]
    return send_page(request, "sessions", rows)


def _target_of(store: Store, self_id: int, raw_id: str) -> tuple[int, bool] | Response:
    """Whose sessions an admin route is asking about, and whether the owner is
    asking. Nobody but the owner reaches the owner's, the same rule as revoking
    the owner's access."""
    user_id = parse_id(raw_id)
    if user_id is None:
        return bad_request("invalid user id")
    if users.get_user(store, user_id) is None:
        return error(404, "no such user")
    owner_id = users.get_owner_id(store)
    by_owner = self_id == owner_id
    if user_id == owner_id and not by_owner:
        return error(403, "the owner account's sessions are the owner's own")
    return user_id, by_owner


async def list_user_sessions(request: Request) -> Response:
    """Where an account is signed in, for ending one device rather than
    everything with revoke-access. Addresses are for the owner only, as in the
    activity log, which keeps them from other admins too."""
    store, actor = get_store(request), actor_from(request)
    target = await run(_target_of, store, actor.user.id, request.path_params["user_id"])
    if isinstance(target, Response):
        return target
    user_id, by_owner = target
    rows = [session_row(session, actor.session.id) for session in await run(sessions.list_sessions, store, user_id)]
    if not by_owner:
        for row in rows:
            row.pop("ip", None)
    return send_page(request, "sessions", rows)


async def revoke_user_session(request: Request) -> Response:
    """Sign one of an account's devices out, and only that."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    store, actor = get_store(request), actor_from(request)
    target = await run(_target_of, store, actor.user.id, request.path_params["user_id"])
    if isinstance(target, Response):
        return target
    user_id, _ = target
    session_id = request.path_params["session_id"]
    if session_id == actor.session.id:
        return bad_request("use sign out for this device")
    if not await run(sessions.revoke_session, store, user_id, session_id):
        return not_found("not found")
    audit(request, KIND_ADMIN, "session revoked", {"user_id": user_id})
    return JSONResponse({"ok": True})


async def label_one(request: Request) -> Response:
    """Name one of your own devices, this one included. An empty label clears
    the name. Admins see a label but cannot set one: it is what the person
    calls their own device."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    label, expect = body.get("label"), body.get("expect")
    if not sessions.valid_session_label(label):
        return bad_request("a device name can be at most 80 characters")
    if expect is not None and not isinstance(expect, str):
        return bad_request("expect must be a string")
    actor = actor_from(request)
    try:
        found = await run(sessions.label_session, get_store(request), actor.user.id, request.path_params["session_id"], label, expect)
    except users.RenameConflictError as stale:
        return conflict(str(stale), label=stale.current)
    if not found:
        return not_found("not found")
    # Not the label: it is the person's own words about where they are.
    audit(request, KIND_AUTH, "session_labelled", {})
    return JSONResponse({"ok": True, "label": label.strip()})


async def revoke_one(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    actor = actor_from(request)
    session_id = request.path_params["session_id"]
    if session_id == actor.session.id:
        return bad_request("use sign out for this device")
    if not await run(sessions.revoke_session, get_store(request), actor.user.id, session_id):
        return not_found("not found")
    audit(request, KIND_AUTH, "session_revoked")
    return JSONResponse({"ok": True})


async def revoke_others(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    actor = actor_from(request)
    removed = await run(sessions.revoke_other_sessions, get_store(request), actor.user.id, actor.session.id)
    audit(request, KIND_AUTH, "sessions_revoked", {"removed": removed})
    return JSONResponse({"ok": True, "removed": removed})
