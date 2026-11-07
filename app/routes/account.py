"""Self-service endpoints for any signed-in caller: who am I, rename myself,
a login link for another device, log out. The account screen itself is static/js/app.js, calling these."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.core.db import Store
from app.core.encryption import BadKeyError, CipherTextError
from app.core.security import Actor, actor_from, check_csrf, clear_session_cookie, decrypt_cookie
from app.models import login_tokens, pins, sessions, users
from app.routes.helpers import bad_request, conflict, forbidden, get_config, get_store, read_json, run, server_error


async def me(request: Request) -> Response:
    """The frontend's first call on every page load: it answers "who am I,
    what may I do, and what CSRF token do I echo back". Handing the token out
    here means no page needs a hidden form field or a template variable.

    "role" is the *effective* role, not the account's: a request made with a
    user-scoped API key belonging to an admin reports "user", because that is
    what it may actually do. account_role reports the account itself, for the
    rare caller that needs to tell the two apart. Reporting the account's role
    as "role" would have a client believe it has permissions the server will
    refuse to act on."""
    return JSONResponse(await run(me_row, get_store(request), get_config(request), actor_from(request)))


def me_row(store: Store, cfg: Config, actor: Actor) -> dict[str, Any]:
    """me's answer, shared with the MCP whoami tool so the two cannot describe
    the same caller differently."""
    # is_owner tells the UI which account-management buttons to offer; the
    # server checks ownership again on every request that depends on it.
    owner_id = users.get_owner_id(store)
    payload: dict[str, Any] = {
        "authenticated": True,
        "id": actor.user.id,
        "display_name": actor.user.display_name,
        "role": actor.role,
        "account_role": actor.user.role,
        "is_owner": actor.user.id == owner_id,
        "has_pin": pins.has_pin(actor.user),
        "auth": actor.method,
        "api_keys_enabled": cfg.api_keys_enabled,
    }
    # Only a session has a CSRF token. A key-authenticated request has no
    # ambient credential to protect, so there is nothing to hand back -- see
    # check_csrf.
    if actor.session is not None:
        payload["csrf_token"] = actor.session.csrf_token
    if actor.api_key is not None:
        payload["api_key_id"] = actor.api_key.id
        payload["api_key_name"] = actor.api_key.name
    return payload


async def rename(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    display_name = body.get("display_name")
    if not users.valid_display_name(display_name):
        return bad_request("display name must be 1-80 characters")
    # Optional: the name the caller expects to replace. The frontend always
    # sends it, so its undo cannot overwrite a rename made elsewhere.
    expect = body.get("expect")
    if expect is not None and not isinstance(expect, str):
        return bad_request("expect must be a string")

    try:
        renamed = await run(users.rename_user, get_store(request), actor_from(request).user.id, display_name, expect)
    except users.RenameConflictError as refusal:
        return conflict(str(refusal), display_name=refusal.current)
    if not renamed:
        return server_error()
    return JSONResponse({"ok": True, "display_name": display_name.strip()})


async def set_pin(request: Request) -> Response:
    """Set, or with an empty pin clear, the PIN asked for when this account
    signs back in through an invite link (see app/models/pins.py)."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    pin = body.get("pin")
    if not isinstance(pin, str):
        return bad_request("bad_pin")
    try:
        if not await run(pins.set_user_pin, get_store(request), actor_from(request).user.id, pin):
            return server_error()
    except pins.BadPinError:
        return bad_request("bad_pin")
    return JSONResponse({"ok": True, "has_pin": pin != ""})


async def create_my_login_link(request: Request) -> Response:
    """Mint a one-time login link for the caller's own account: the way to
    sign in on another device without asking an admin. It is
    admin.reissue_login pointed at yourself, so it has the same effect: any
    unused link the account had stops working, and existing sessions stay
    signed in.

    Session only (see routes/__init__.py): a login link becomes a session, so
    an API key that could call this could turn itself into one."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    store, cfg = get_store(request), get_config(request)
    credential = await run(
        login_tokens.issue_login_token, store, actor_from(request).user.id, cfg.login_token_ttl_seconds
    )
    return JSONResponse({"login_path": f"/login/{credential}", "expires_in_seconds": cfg.login_token_ttl_seconds})


async def logout(request: Request) -> Response:
    """Deletes the session server-side as well as clearing the cookie, so a
    copy of the cookie captured earlier is dead too.

    It is held to the CSRF token like every other state change. SameSite=
    Strict already stops another site from sending the cookie here, but not a
    page on a sibling subdomain, and being signed out by someone else's page
    is the first step of tricking a person into signing in to the wrong
    account.

    Called with an API key it does nothing and says so by succeeding: there is
    no session to destroy. A key is ended by revoking it, not by logging out."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    await destroy_cookie_session(request)
    response = JSONResponse({"ok": True})
    clear_session_cookie(response, get_config(request))
    return response


async def destroy_cookie_session(request: Request) -> None:
    """Delete the session named by this request's cookie, if any. Deleting
    the record rather than only the cookie is what matters: a copy of the
    cookie taken earlier is then dead too."""
    cfg = get_config(request)
    raw = request.cookies.get(cfg.cookie_name, "")
    if not raw:
        return
    try:
        credential = decrypt_cookie(cfg, raw)
    except (CipherTextError, BadKeyError):
        return
    await run(sessions.destroy_session, get_store(request), credential)
