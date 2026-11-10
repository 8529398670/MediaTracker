"""Self-service endpoints for any signed-in caller: who am I, rename myself,
a login link for another device, log out. The account screen itself is static/js/app.js, calling these."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.core.config import repo_file
from app.core.db import Store
from app.core.encryption import BadKeyError, CipherTextError
from app.core.logs import KIND_AUTH
from app.core.security import Actor, actor_from, check_csrf, clear_session_cookie, decrypt_cookie
from app.models import login_tokens, sessions, users
from app.models import passwords
from app.models import pins
from app.models import themes
from app.models import two_factor
from app.routes.admin import link_options, link_response
from app.routes.helpers import Refused, bad_request, forbidden, get_config, get_store, read_json, run, server_error
from app.routes.logs import audit


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
    return JSONResponse(await run(me_row, get_store(request), get_config(request), actor_from(request), request.app.state.version))


def open_api_url(cfg: Config) -> str:
    """Where the API reference is read: config/openapi.json in app.repo when
    that is set, so it opens as a page there, else this server's own copy,
    which needs the same sign-in."""
    return repo_file(cfg, "config/openapi.json") or "/api/openapi.json"


def mcp_url(cfg: Config) -> str:
    """Where the MCP reference is read: config/mcp.json in app.repo when that
    is set, else this server's own copy, which needs the same sign-in."""
    return repo_file(cfg, "config/mcp.json") or "/api/mcp.json"


def me_row(store: Store, cfg: Config, actor: Actor, version: str) -> dict[str, Any]:
    """me's answer, shared with the MCP whoami tool so the two cannot describe
    the same caller differently."""
    # is_owner tells the UI which account-management buttons to offer; the
    # server checks ownership again on every request that depends on it.
    owner_id = users.get_owner_id(store)
    my_themes, themes_custom = themes.mine(store, actor.user.themes)
    payload: dict[str, Any] = {
        "authenticated": True,
        "id": actor.user.id,
        "display_name": actor.user.display_name,
        "role": actor.role,
        "account_role": actor.user.role,
        # The Showing picker: whether this caller may use it, and whose lists
        # it starts on (None for their own). A user-scoped key of an admin
        # reports what it may actually do, like "role".
        "can_show_others": actor.is_admin or actor.user.can_show_others,
        "default_subject": actor.user.default_subject,
        # An admin's lock on that choice: the picker cannot be changed.
        "showing_locked": users.locked_subject(actor.user) is not None,
        "is_owner": actor.user.id == owner_id,
        "login_link": login_tokens.live_login_link(store, actor.user.id),
        "maintenance": cfg.maintenance,
        "version": version,
        "announcement": cfg.announcement,
        "repo": cfg.repo,
        "description": cfg.description,
        "show_about": cfg.show_about,
        "openapi_url": open_api_url(cfg),
        "mcp_url": mcp_url(cfg),
        "themes": my_themes,
        "themes_custom": themes_custom,
        "theme_id": actor.user.theme_id,
        "has_pin": pins.has_pin(actor.user),
        "username": actor.user.username,
        "has_password": passwords.has_password(actor.user),
        "password_blocked": actor.user.password_blocked,
        "two_factor": two_factor.is_on(actor.user),
        "passwords_enabled": cfg.passwords_enabled,
        "two_factor_enabled": cfg.two_factor_enabled,
        "auth": actor.method,
        "api_keys_enabled": cfg.api_keys_enabled,
        "mcp_enabled": cfg.mcp_enabled,
        "invite_links_enabled": cfg.invite_links_enabled,
        # Whether track.js sends anything, and whether it sends clicks.
        "logs_enabled": cfg.logs.enabled,
        "logs_ui_clicks": cfg.logs.enabled and cfg.logs.ui_clicks,
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
    try:
        return JSONResponse(await run(rename_checked, request, body.get("display_name"), body.get("expect")))
    except Refused as refused:
        return refused.response(request)


def rename_checked(request: Request, display_name: Any, expect: Any) -> dict[str, Any]:
    """rename after the request is read, for it and the MCP rename_account
    tool. Synchronous: it runs in a worker thread."""
    if not users.valid_display_name(display_name):
        raise Refused(400, "display name must be 1-80 characters")
    # Optional: the name the caller expects to replace. The frontend always
    # sends it, so its undo cannot overwrite a rename made elsewhere.
    if expect is not None and not isinstance(expect, str):
        raise Refused(400, "expect must be a string")
    try:
        renamed = users.rename_user(get_store(request), actor_from(request).user.id, display_name, expect)
    except users.RenameConflictError as refusal:
        raise Refused(409, str(refusal), display_name=refusal.current) from None
    if not renamed:
        raise Refused.internal("rename: the signed-in account has no record")
    audit(request, KIND_AUTH, "renamed own account", {"name": display_name.strip()})
    return {"ok": True, "display_name": display_name.strip()}


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
            return server_error(request, "set pin: the signed-in account has no record")
    except pins.BadPinError:
        return bad_request("bad_pin")
    audit(request, KIND_AUTH, "pin changed", {"has_pin": pin != ""})
    return JSONResponse({"ok": True, "has_pin": pin != ""})


async def create_my_login_link(request: Request) -> Response:
    """Mint a login link for the caller's own account: the way to sign in on
    another device without asking an admin. Once by default, or reusable,
    like admin.reissue_login -- it is reissue_login pointed at yourself, so it
    has the same effect: any link the account could still use stops working,
    and existing sessions stay signed in.

    Session only (see routes/__init__.py): a login link becomes a session, so
    an API key that could call this could turn itself into one."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    options = link_options(request, body)
    if options is None:
        return bad_request(str(login_tokens.BadLoginLinkError()))
    credential, info = await run(login_tokens.issue_login_link, get_store(request), actor_from(request).user.id, options)
    audit(request, KIND_AUTH, "own login link created", {"max_uses": info["max_uses"], "expires_at": info["expires_at"]})
    return JSONResponse(link_response(credential, info))


async def cancel_my_login_link(request: Request) -> Response:
    """Stop the caller's own live login link working."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    removed = await run(login_tokens.cancel_login_link, get_store(request), actor_from(request).user.id)
    audit(request, KIND_AUTH, "own login link cancelled", {"removed": removed})
    return JSONResponse({"ok": True, "removed": removed})


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
    audit(request, KIND_AUTH, "signed out")
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
