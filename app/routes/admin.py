"""Admin-only: deciding who gets in, and removing who should not. This --
plus the first-run bootstrap and `python -m app manage` -- is the entire
signup system.

One admin is the owner (see app/models/users.py). Any admin may delete an
ordinary user; only the owner may delete another admin; and nobody here may
delete, disable, or revoke the owner.

Note this is the *only* thing admin rights gate in the base template. See
references/architecture.md on defaulting new features to "any signed-in
user".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from, check_csrf
from app.models import credentials, from_iso, login_tokens, to_iso, users, utc_now
from app.models import passwords
from app.models import two_factor
from app.routes.helpers import bad_request, conflict, error, forbidden, get_config, get_store, not_found, parse_id, read_json, run, send_page
from app.routes.logs import audit


async def list_users(request: Request) -> Response:
    """Marks the owner on its row, so the UI can tell which delete, disable,
    and revoke buttons the server would refuse.

    ?q= keeps the accounts whose name or username contains it, in any case.
    Here and not in the browser, which only ever holds one page of them."""
    return send_page(request, "users", await run(user_rows, get_store(request), request.query_params.get("q", "")), ("display_name", "role", "disabled", "created_at"))


def user_rows(store: Store, query: str = "") -> list[dict[str, Any]]:
    """Shared with the MCP admin_list_users tool."""
    owner_id = users.get_owner_id(store)
    links = login_tokens.live_login_links(store)
    wanted = query.strip().lower()
    return [
        {
            "id": u.id,
            "display_name": u.display_name,
            "username": u.username,
            "role": u.role,
            "created_at": to_iso(u.created_at),
            "disabled": u.disabled,
            "owner": u.id == owner_id,
            "has_password": passwords.has_password(u),
            "password_blocked": u.password_blocked,
            "two_factor": two_factor.is_on(u),
            "login_link": links.get(u.id),
        }
        for u in users.list_users(store)
        if wanted in u.display_name.lower() or wanted in (u.username or "").lower()
    ]


def link_options(request: Request, body: dict) -> login_tokens.LinkOptions | None:
    """What the body asked a new login link to allow, with the configured
    defaults filling the gaps (see login_tokens.resolve_link). None when it is
    out of range."""
    cfg = get_config(request)
    try:
        return login_tokens.resolve_link(
            body.get("max_uses"), body.get("expires_in_minutes"),
            cfg.login_token_ttl_seconds, cfg.multi_use_login_token_ttl_seconds,
        )
    except login_tokens.BadLoginLinkError:
        return None


def link_response(credential: str, info: dict) -> dict[str, Any]:
    """What every route that mints a link answers. The link is a path, not a
    full URL (see create_user)."""
    expires_in = 0
    if info["expires_at"] is not None:
        expires_in = max(0, round((from_iso(info["expires_at"]) - utc_now()).total_seconds()))
    return {
        "login_path": f"/login/{credential}",
        "expires_in_seconds": expires_in,
        "expires_at": info["expires_at"],
        "max_uses": info["max_uses"],
        "unlimited": info["unlimited"],
    }


async def create_user(request: Request) -> Response:
    """The signup process: an admin names someone, and gets back a login link
    to hand them -- once by default, or reusable (see
    login_tokens.resolve_link). The link is returned as a path, not a full URL -- the
    browser knows the origin it is talking to, whereas the server behind a
    reverse proxy often does not, and a login link with the wrong host is
    worse than useless."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    display_name, role = body.get("display_name"), body.get("role")
    if not users.valid_display_name(display_name):
        return bad_request("display name must be 1-80 characters")
    if not users.valid_role(role):
        return bad_request("role must be admin or user")
    options = link_options(request, body)
    if options is None:
        return bad_request(str(login_tokens.BadLoginLinkError()))

    store = get_store(request)
    user = await run(users.create_user, store, display_name, role)
    credential, info = await run(login_tokens.issue_login_link, store, user.id, options)
    audit(request, KIND_ADMIN, "user created", {"user_id": user.id, "name": user.display_name, "role": user.role})
    return JSONResponse({"user_id": user.id, **link_response(credential, info)}, status_code=201)


async def reissue_login(request: Request) -> Response:
    """Covers the only real failure mode of this auth model: someone lost
    their cookie or their device, and there is no password reset to fall back
    on. An admin mints a fresh link instead. Any link the account could still
    sign in with stops working (see login_tokens.issue_login_link).

    It is not a reset: sessions the account already has stay signed in. When
    the worry is that someone else holds the account's credentials, use
    revoke_access first, then reissue."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")

    store = get_store(request)
    if await run(users.get_user, store, user_id) is None:
        return not_found("no such user")
    options = link_options(request, body)
    if options is None:
        return bad_request(str(login_tokens.BadLoginLinkError()))
    credential, info = await run(login_tokens.issue_login_link, store, user_id, options)
    audit(request, KIND_ADMIN, "login link reissued", {"user_id": user_id, "max_uses": info["max_uses"], "expires_at": info["expires_at"]})
    return JSONResponse(link_response(credential, info))


async def cancel_login_link(request: Request) -> Response:
    """Stop an account's live login link working, without making a new one:
    a reusable link that went somewhere it should not have. Sessions it
    already made stay signed in; revoke_access ends those too.

    An API key may do this, like revoke_access: it only takes a way in away."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")
    store = get_store(request)
    if await run(users.get_user, store, user_id) is None:
        return not_found("no such user")
    removed = await run(login_tokens.cancel_login_link, store, user_id)
    audit(request, KIND_ADMIN, "login link cancelled", {"user_id": user_id, "removed": removed})
    return JSONResponse({"ok": True, "removed": removed})


async def set_user_disabled(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")
    disabled = body.get("disabled")
    if not isinstance(disabled, bool):
        return bad_request("disabled must be true or false")

    refused = await run(set_disabled_checked, get_store(request), actor_from(request).user.id, user_id, disabled)
    if refused is not None:
        return refused.response()
    audit(request, KIND_ADMIN, "user disabled set", {"user_id": user_id, "disabled": disabled})
    return JSONResponse({"ok": True})


async def revoke_access(request: Request) -> Response:
    """The response to "this account may be compromised": every session,
    live login link, and live API key it holds stops working at once. The
    account itself stays enabled; reissue a login link to let its owner back
    in. See credentials.revoke_all_credentials for why this is separate from
    both disabling and reissuing."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")
    revoked = await run(revoke_access_checked, get_store(request), actor_from(request).user.id, user_id)
    if isinstance(revoked, RuleRefusal):
        return revoked.response()
    audit(request, KIND_ADMIN, "access revoked", {"user_id": user_id})
    return JSONResponse({"ok": True, "revoked": revoked.to_dict()})


async def rename_user(request: Request) -> Response:
    """An admin renaming someone else. Who may rename whom lives in
    credentials.rename_user_as. It needs a browser session, like making an
    account: a name is how people tell who they are dealing with."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")
    name = body.get("display_name")
    if not users.valid_display_name(name):
        return bad_request("display name must be 1-80 characters")
    expect = body.get("expect")
    if expect is not None and not isinstance(expect, str):
        return bad_request("expect must be a string")
    try:
        found = await run(credentials.rename_user_as, get_store(request), user_id, actor_from(request).user.id, name, expect)
    except users.RenameConflictError as stale:
        return conflict(str(stale), display_name=stale.current)
    except credentials.OwnerRequiredError:
        return forbidden("only the owner can rename an admin")
    if not found:
        return not_found("no such user")
    audit(request, KIND_ADMIN, "user renamed", {"user_id": user_id, "name": name.strip()})
    return JSONResponse({"ok": True, "display_name": name.strip()})


async def set_user_role(request: Request) -> Response:
    """Make an account an admin or an ordinary user. Who may do what lives in
    credentials.set_user_role. It needs a browser session, like making an
    account, so a leaked admin key cannot hand out admin rights."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")
    role = body.get("role")
    if not users.valid_role(role):
        return bad_request("role must be admin or user")
    try:
        changed = await run(credentials.set_user_role, get_store(request), user_id, actor_from(request).user.id, role)
    except credentials.SelfRoleError as refusal:
        return bad_request(str(refusal))
    except credentials.OwnerProtectedError:
        return forbidden("the owner is always an admin")
    except credentials.OwnerRequiredError:
        return forbidden("only the owner can take away an admin's rights")
    if changed is None:
        return not_found("no such user")
    if changed:
        audit(request, KIND_ADMIN, "user role changed", {"user_id": user_id, "role": role})
    return JSONResponse({"ok": True, "role": role})


async def delete_user(request: Request) -> Response:
    """Remove an account for good, together with every session, login link,
    and API key it held. Disabling is the reversible version; this is for an
    account that should not exist at all.

    Who may delete whom lives in credentials.delete_user, checked inside its
    transaction. The route also requires a browser session (see
    app/routes/__init__.py): this cannot be undone, so a leaked admin-scoped
    API key must not be able to do it."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")

    try:
        removed = await run(credentials.delete_user, get_store(request), user_id, actor_from(request).user.id)
    except credentials.SelfDeleteError:
        return bad_request("you cannot delete your own account")
    except credentials.OwnerProtectedError:
        return forbidden("the owner account cannot be deleted")
    except credentials.OwnerRequiredError:
        return forbidden("only the owner can delete an admin account")
    if removed is None:
        return not_found("no such user")
    audit(request, KIND_ADMIN, "user deleted", {"user_id": user_id})
    return JSONResponse({"ok": True, "removed": removed.to_dict()})


async def reset_two_factor(request: Request) -> Response:
    """For someone who lost both the phone and the recovery codes. Who may
    reset whom lives in credentials.reset_two_factor; it needs a browser
    session, because it removes what stands between a login link and the
    account."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = parse_id(request.path_params["user_id"])
    if user_id is None:
        return bad_request("invalid user id")
    try:
        found = await run(credentials.reset_two_factor, get_store(request), user_id, actor_from(request).user.id)
    except credentials.SelfResetError:
        return bad_request("you cannot reset your own two-factor sign-in")
    except credentials.OwnerProtectedError:
        return forbidden("the owner's two-factor sign-in can only be reset from a shell")
    except credentials.OwnerRequiredError:
        return forbidden("only the owner can reset an admin's two-factor sign-in")
    if not found:
        return not_found("no such user")
    audit(request, KIND_ADMIN, "two-factor reset", {"user_id": user_id})
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# rules shared with the MCP tools
#
# A refusal is kept apart from how it is delivered: the HTTP handlers above
# send it as a status and an error body, the MCP tools (mcp_tools.py) as a
# tool error with the same words. Writing each rule once is what keeps the two
# doors from drifting apart. These are synchronous; call them through run().
# ---------------------------------------------------------------------------


@dataclass
class RuleRefusal:
    status: int
    message: str

    def response(self) -> JSONResponse:
        return error(self.status, self.message)


def set_disabled_checked(store: Store, self_id: int, user_id: int, disabled: bool) -> RuleRefusal | None:
    """Every rule for switching an account off or on."""
    if users.get_user(store, user_id) is None:
        return RuleRefusal(404, "no such user")
    # Locking yourself out is unrecoverable without shell access, so it is
    # worth one guard rail even though an admin could still disable a peer.
    if disabled and user_id == self_id:
        return RuleRefusal(400, "you cannot disable your own account")

    # Disabling also deletes the account's sessions and live login links,
    # in the same transaction -- see credentials.set_user_disabled. The owner
    # cannot be disabled; that check is in the model so every route gets it.
    try:
        found = credentials.set_user_disabled(store, user_id, disabled)
    except credentials.OwnerProtectedError:
        return RuleRefusal(403, "the owner account cannot be disabled")
    if not found:
        return RuleRefusal(404, "no such user")
    return None


def revoke_access_checked(store: Store, self_id: int, user_id: int) -> credentials.Revoked | RuleRefusal:
    """Every rule for cutting an account's credentials off."""
    # Same guard rail as disabling: revoking your own access signs you out
    # with no link to get back in.
    if user_id == self_id:
        return RuleRefusal(400, "you cannot revoke your own access")

    # The owner is refused here (allow_owner False). Only an operator with
    # shell access may cut the owner off -- see revoke_all_credentials.
    try:
        revoked = credentials.revoke_all_credentials(store, user_id)
    except credentials.OwnerProtectedError:
        return RuleRefusal(403, "the owner account's access cannot be revoked")
    if revoked is None:
        return RuleRefusal(404, "no such user")
    return revoked
