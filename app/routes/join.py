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

from app.core.logs import KIND_AUTH, LEVEL_INFO, LEVEL_WARN
from app.models import invite_links, pins, users
from app.models import passwords
from app.models.attempts import AttemptGuard
from app.models.invite_links import InviteLink, InviteLinkFullError, InviteLinkInvalidError, NotInviteAccountError
from app.models.sign_in import SignIn
from app.routes.auth import same_origin_json, sign_in_response, sign_in_rules
from app.routes.helpers import bad_request, error, forbidden, get_config, get_store, not_found, read_json, run
from app.routes.logs import audit_as, user_actor

# Per process, like the rate limiter. See AttemptGuard.
PINS = AttemptGuard()


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
    device -- asking for the PIN if that person set one.

    An account with a password and no PIN is refused: anyone holding the link
    can pick any name on it, and that must not walk around the password. The
    person signs in with it instead. An account with two-factor on still has
    to give its code after this, PIN or not."""
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
            audit_as(request, await run(user_actor, store, user.id, "anon"), KIND_AUTH, LEVEL_WARN, "wrong pin on an invite link", {"link_id": link.id})
            return forbidden("pin_needed" if not pin else "pin_wrong")
    elif passwords.usable(user, cfg.passwords_enabled):
        return forbidden("use_password")

    try:
        signed, user = await run(
            invite_links.claim_invite_account, store, body.get("credential"), user.id, sign_in_rules(cfg)
        )
    except InviteLinkInvalidError:
        return not_found("invite_link_invalid")
    except NotInviteAccountError:
        return not_found("no_such_account")
    message = "invite link accepted, waiting for a code" if signed.challenge else "signed back in through an invite link"
    audit_as(request, await run(user_actor, store, user.id, "session"), KIND_AUTH, LEVEL_INFO, message, {"link_id": link.id})
    return await sign_in_response(request, signed, {"ok": True, "display_name": user.display_name}, 200)


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
    audit_as(request, await run(user_actor, store, user.id, "session"), KIND_AUTH, LEVEL_INFO, "joined through an invite link", {"link_id": link.id})
    signed = SignIn(user_id=user.id, session_credential=session_credential)
    return await sign_in_response(request, signed, {"ok": True, "display_name": user.display_name}, 201)
