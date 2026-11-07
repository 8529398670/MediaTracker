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
from app.core.security import actor_from, check_csrf
from app.models import credentials, login_tokens, users
from app.routes.helpers import bad_request, error, forbidden, get_config, get_store, not_found, parse_id, read_json, run


async def list_users(request: Request) -> Response:
    """Marks the owner on its row, so the UI can tell which delete, disable,
    and revoke buttons the server would refuse."""
    return JSONResponse(await run(user_rows, get_store(request)))


def user_rows(store: Store) -> list[dict[str, Any]]:
    """Shared with the MCP admin_list_users tool."""
    owner_id = users.get_owner_id(store)
    return [
        {"id": u.id, "display_name": u.display_name, "role": u.role, "disabled": u.disabled, "owner": u.id == owner_id}
        for u in users.list_users(store)
    ]


async def create_user(request: Request) -> Response:
    """The signup process: an admin names someone, and gets back a one-time
    link to hand them. The link is returned as a path, not a full URL -- the
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

    store, cfg = get_store(request), get_config(request)
    user = await run(users.create_user, store, display_name, role)
    credential = await run(login_tokens.issue_login_token, store, user.id, cfg.login_token_ttl_seconds)
    return JSONResponse(
        {
            "user_id": user.id,
            "login_path": f"/login/{credential}",
            "expires_in_seconds": cfg.login_token_ttl_seconds,
        },
        status_code=201,
    )


async def reissue_login(request: Request) -> Response:
    """Covers the only real failure mode of this auth model: someone lost
    their cookie or their device, and there is no password reset to fall back
    on. An admin mints a fresh link instead. Any link the account had not
    used yet stops working (see login_tokens.issue_login_token).

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

    store, cfg = get_store(request), get_config(request)
    if await run(users.get_user, store, user_id) is None:
        return not_found("no such user")
    credential = await run(login_tokens.issue_login_token, store, user_id, cfg.login_token_ttl_seconds)
    return JSONResponse({"login_path": f"/login/{credential}", "expires_in_seconds": cfg.login_token_ttl_seconds})


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
    return JSONResponse({"ok": True})


async def revoke_access(request: Request) -> Response:
    """The response to "this account may be compromised": every session,
    unused login link, and live API key it holds stops working at once. The
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
    return JSONResponse({"ok": True, "revoked": revoked.to_dict()})


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
    return JSONResponse({"ok": True, "removed": removed.to_dict()})


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

    # Disabling also deletes the account's sessions and unused login links,
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
