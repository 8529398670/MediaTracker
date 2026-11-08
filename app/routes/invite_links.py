"""Managing invite links (see app/models/invite_links.py; joining through one
is app/routes/join.py). Admin only. The link's credential is returned once,
on creation, as a path -- the browser adds its own origin, like a login
link."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from, check_csrf
from app.models import RestoreError, invite_links, users
from app.models.invite_links import InviteLink
from app.models.users import User
from app.routes.helpers import bad_request, conflict, forbidden, get_store, match_rows, not_found, read_json, restore_refused, run, send_page
from app.routes.logs import audit


def _row(link: InviteLink, creator: User | None) -> dict[str, Any]:
    live = link.live
    # A link outlives its maker's admin rights only on paper: it stops
    # working the moment they lose them (see load_invite_link).
    if creator is None or creator.disabled or not creator.is_admin:
        live = False
    row: dict[str, Any] = {
        "id": link.id,
        "label": link.label,
        "max_uses": link.max_uses,
        "used": len(link.accounts),
        "remaining": link.remaining,
        "live": live,
        "expires_at": link.expires_at.isoformat(),
        "revoked": link.revoked_at is not None,
        "created_by": link.created_by,
    }
    if creator is not None:
        row["created_by_name"] = creator.display_name
    return row


def invite_link_rows(store: Store) -> list[dict[str, Any]]:
    creators = {user.id: user for user in users.list_users(store)}
    return [_row(link, creators.get(link.created_by)) for link in invite_links.list_invite_links(store)]


async def list_invite_links(request: Request) -> Response:
    rows = match_rows(await run(invite_link_rows, get_store(request)), request.query_params.get("q", ""), "label", "created_by_name")
    return send_page(request, "invite_links", rows, ("label", "used", "expires_at"))


async def create_invite_link(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    label, max_uses, days = body.get("label"), body.get("max_uses"), body.get("days")
    if not invite_links.valid_invite_link(label, max_uses, days):
        return bad_request("label must be 1-80 characters, uses 1-1000, days 1-365")

    store, creator = get_store(request), actor_from(request).user
    credential, link = await run(invite_links.issue_invite_link, store, label, max_uses, timedelta(days=days), creator.id)
    row = _row(link, creator)
    row["join_path"] = f"/join/{credential}"
    audit(request, KIND_ADMIN, "invite link created", {"link_id": link.id, "label": link.label, "max_uses": link.max_uses})
    return JSONResponse(row, status_code=201)


async def rename_invite_link(request: Request) -> Response:
    """Change a link's label."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    label = body.get("label")
    if not invite_links.valid_invite_label(label):
        return bad_request("label must be 1-80 characters")
    # Optional: the label the caller expects to replace, so an undo cannot
    # overwrite a rename made elsewhere.
    expect = body.get("expect")
    if expect is not None and not isinstance(expect, str):
        return bad_request("expect must be a string")
    link_id = request.path_params["link_id"]
    try:
        renamed = await run(invite_links.rename_invite_link, get_store(request), link_id, label, expect)
    except users.RenameConflictError as refusal:
        return conflict(str(refusal), label=refusal.current)
    if not renamed:
        return not_found("no such invite link")
    audit(request, KIND_ADMIN, "invite link renamed", {"link_id": link_id, "label": label.strip()})
    return JSONResponse({"ok": True, "label": label.strip()})


async def set_invite_link_limits(request: Request) -> Response:
    """Change a link's places, and its expiry when days is given; leaving days
    out keeps the expiry. It needs a session, like making a link: more places
    is more accounts, so a leaked admin key must not be a way to add them."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    max_uses, days = body.get("max_uses"), body.get("days")
    if not invite_links.valid_invite_limits(max_uses, days):
        return bad_request("uses must be 1-1000 and days 1-365")
    store = get_store(request)
    ttl = None if days is None else timedelta(days=days)
    try:
        link = await run(invite_links.set_invite_link_limits, store, request.path_params["link_id"], max_uses, ttl)
    except invite_links.InvitePlacesError as refusal:
        return bad_request(str(refusal))
    if link is None:
        return not_found("no such invite link")
    audit(request, KIND_ADMIN, "invite link limits changed", {"link_id": link.id, "max_uses": link.max_uses, "expires_at": link.expires_at.isoformat()})
    return JSONResponse(_row(link, await run(users.get_user, store, link.created_by)))


async def switch_on_invite_link(request: Request) -> Response:
    """Undo revoke_invite_link. Switching off is safe for an admin key; this
    needs a session, or a leaked key could reopen a closed link."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    store = get_store(request)
    link = await run(invite_links.switch_on_invite_link, store, request.path_params["link_id"])
    if link is None:
        return not_found("no such invite link")
    audit(request, KIND_ADMIN, "invite link switched back on", {"link_id": link.id})
    return JSONResponse(_row(link, await run(users.get_user, store, link.created_by)))


async def revoke_invite_link(request: Request) -> Response:
    """Switch a link off. The accounts it made keep working."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    if not await run(invite_links.revoke_invite_link, get_store(request), request.path_params["link_id"]):
        return not_found("no such invite link")
    audit(request, KIND_ADMIN, "invite link revoked", {"link_id": request.path_params["link_id"]})
    return JSONResponse({"ok": True})


async def delete_invite_link(request: Request) -> Response:
    """Drop a link from the list. The accounts it made stay; they just can no
    longer sign in on a new device through it. restore_invite_link undoes it
    for a few minutes."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    actor_id = actor_from(request).user.id
    if not await run(invite_links.delete_invite_link, get_store(request), request.path_params["link_id"], actor_id):
        return not_found("no such invite link")
    audit(request, KIND_ADMIN, "invite link deleted", {"link_id": request.path_params["link_id"]})
    return JSONResponse({"ok": True})


async def restore_invite_link(request: Request) -> Response:
    """Undo delete_invite_link, within RESTORE_WINDOW. The link works again
    exactly as before, uses and expiry included."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    store, actor = get_store(request), actor_from(request).user
    try:
        link = await run(invite_links.restore_invite_link, store, request.path_params["link_id"], actor.id, actor.is_admin)
    except RestoreError as refusal:
        return restore_refused(refusal)
    audit(request, KIND_ADMIN, "invite link restored", {"link_id": request.path_params["link_id"]})
    return JSONResponse(_row(link, await run(users.get_user, store, link.created_by)))
