"""Joining through an invite link (see app/models/invite_links.py; managing
links is app/routes/invite_links.py).

Everything here is public -- holding the link is the permission -- so every
POST is held to the same rule as /api/login: a JSON body from one of this
site's own pages (same_origin_json). The credential travels in the body,
never a query string, and the page that carries it in its path is served with
no-referrer (StaticServer.serve_login_page, which both link pages share).

A bad, expired, switched-off, or orphaned link always answers 404
invite_link_invalid, whichever of those it was.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import set_session_cookie
from app.models import invite_links, pins, users
from app.models.invite_links import InviteLink, InviteLinkFullError, InviteLinkInvalidError, NotInviteAccountError
from app.routes.account import destroy_cookie_session
from app.routes.auth import same_origin_json
from app.routes.helpers import bad_request, error, forbidden, get_config, get_store, not_found, read_json, run

# Per process, like the rate limiter. See PinGuard.
PINS = pins.PinGuard()


async def _join_link(request: Request) -> tuple[InviteLink | None, dict[str, Any], Response | None]:
    """Check the request, decode the body, and load the link. Returns (link,
    body, None), or (None, body, the response to send)."""
    if not same_origin_json(request):
        return None, {}, forbidden("invite links must be used from this site's own page")
    body = await read_json(request)
    if body is None:
        return None, {}, bad_request("malformed request body")
    try:
        link = await run(invite_links.load_invite_link, get_store(request), body.get("credential"))
    except InviteLinkInvalidError:
        return None, body, not_found("invite_link_invalid")
    return link, body, None


async def join_info(request: Request) -> Response:
    link, _, refused = await _join_link(request)
    if link is None:
        return refused
    return JSONResponse({"label": link.label, "remaining": link.remaining})


async def join_match(request: Request) -> Response:
    """The "did you mean...?": the accounts from this link whose names are
    close to what was typed. The page always shows this step before creating
    anyone, even with no matches, because a typo would otherwise use up a
    place."""
    link, body, refused = await _join_link(request)
    if link is None:
        return refused
    display_name = body.get("display_name")
    if not users.valid_display_name(display_name):
        return bad_request("display name must be 1-80 characters")
    matches = await run(invite_links.invite_matches, get_store(request), link, display_name)
    rows = [{"id": user.id, "display_name": user.display_name, "has_pin": pins.has_pin(user)} for user in matches]
    return JSONResponse({"matches": rows, "can_create": link.remaining > 0})


async def join_claim(request: Request) -> Response:
    """Sign in as an account this link created -- the same person on another
    device -- asking for the PIN if that person set one."""
    link, body, refused = await _join_link(request)
    if link is None:
        return refused
    store, cfg = get_store(request), get_config(request)
    try:
        user = await run(invite_links.invite_account, store, link, body.get("user_id"))
    except NotInviteAccountError:
        return not_found("no_such_account")

    if pins.has_pin(user):
        if PINS.locked(user.id):
            return error(429, "pin_locked")
        pin = body.get("pin")
        ok = await run(pins.check_pin, user, pin)
        PINS.record(user.id, ok)
        if not ok:
            return forbidden("pin_needed" if not pin else "pin_wrong")

    try:
        session_credential, user = await run(
            invite_links.claim_invite_account, store, body.get("credential"), user.id, cfg.session_ttl_seconds
        )
    except InviteLinkInvalidError:
        return not_found("invite_link_invalid")
    except NotInviteAccountError:
        return not_found("no_such_account")
    return await _start_session(request, session_credential, {"ok": True, "display_name": user.display_name}, 200)


async def join_create(request: Request) -> Response:
    """Make a new account through the link, if it has places left, and sign
    it in."""
    link, body, refused = await _join_link(request)
    if link is None:
        return refused
    display_name = body.get("display_name")
    if not users.valid_display_name(display_name):
        return bad_request("display name must be 1-80 characters")

    store, cfg = get_store(request), get_config(request)
    try:
        session_credential, user = await run(
            invite_links.join_invite_link, store, body.get("credential"), display_name, cfg.session_ttl_seconds
        )
    except InviteLinkInvalidError:
        return not_found("invite_link_invalid")
    except InviteLinkFullError:
        return error(409, "invite_link_full")
    return await _start_session(request, session_credential, {"ok": True, "display_name": user.display_name}, 201)


async def _start_session(request: Request, session_credential: str, payload: dict[str, Any], status: int) -> Response:
    """Switch this browser to a session that was just stored: the one it had
    is ended server-side first, exactly like redeem_login_link."""
    await destroy_cookie_session(request)
    response = JSONResponse(payload, status_code=status)
    set_session_cookie(response, get_config(request), session_credential)
    return response
