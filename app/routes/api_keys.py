"""API keys are how anything that is not a browser calls this API: a script, a
cron job, a CI pipeline, another service. A key carries a role from the same
set users do, so there is one permission model rather than two -- see
app/models/api_keys.py and references/architecture.md.

Every signed-in user can mint their own keys, and revoke or delete them. An
admin can additionally see, revoke, and delete everyone's, which is what makes
"who has standing access to this app" an answerable question.

Revoking keeps the row, marked dead, so the listing still shows the key
existed and when it stopped working; the purge drops it later. Deleting
takes it off every listing. Either one stops the key immediately. Only
delete can be undone: for RESTORE_WINDOW the restore routes put a deleted key
back, working again (the Undo on the frontend's toast). Revoke is the switch
for a key that may have leaked, and has no way back.

Minting, revoking, and deleting require a browser session (the routes are registered
behind RequireSession in app/routes/__init__.py), so a leaked key cannot
quietly mint its replacement. The admin routes that hand out login links
require one too, for the same reason -- see RequireSession.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.core.security import Guard, actor_from, check_csrf
from app.models import RestoreError, api_keys, to_iso, users
from app.routes.helpers import (
    bad_request,
    conflict,
    forbidden,
    get_config,
    get_store,
    not_found,
    read_json,
    restore_refused,
    run,
)


class RequireAPIKeys(Guard):
    """Hides the key-management endpoints when the feature is switched off, so
    an app with no programmatic callers can close the surface entirely. The
    Authorization header is ignored in that state too -- that part is enforced
    in app/core/security.py, not here, because it has to hold for every route
    rather than only these."""

    def refuse(self, request: Request) -> Response | None:
        if not get_config(request).api_keys_enabled:
            return not_found("api keys are disabled on this server")
        return None


def api_key_row(key: api_keys.APIKey, display_name: str = "") -> dict[str, Any]:
    """The only shape a key is ever returned in. The secret hash is not in it,
    and nor is the credential -- that exists in one response, from
    create_my_key, and is never recoverable afterwards."""
    row: dict[str, Any] = {
        "id": key.id,
        "user_id": key.user_id,
        "name": key.name,
        "role": key.role,
        "created_at": to_iso(key.created_at),
        "revoked": key.revoked,
        "expired": key.expired,
        "live": key.live,
    }
    for field_name in ("expires_at", "last_used_at", "revoked_at"):
        value = getattr(key, field_name)
        if value is not None:
            row[field_name] = to_iso(value)
    if display_name:
        row["display_name"] = display_name
    return row


async def list_my_keys(request: Request) -> Response:
    """Answers "what has standing access as me". Revoked and expired keys are
    included, marked as such, because a key that used to exist is part of
    that answer."""
    keys = await run(api_keys.list_api_keys_for_user, get_store(request), actor_from(request).user.id)
    return JSONResponse([api_key_row(key) for key in keys])


async def create_my_key(request: Request) -> Response:
    """Mints a key for the signed-in user and returns the credential once. The
    default role is "user" even for an admin: an admin-scoped key can list and
    disable accounts and revoke anyone's access, so it should be asked for
    rather than handed out by omission.

    The ceiling -- a key cannot outrank its owner -- lives in
    api_keys.issue_api_key, not here, so the CLI gets it too."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    name = body.get("name")
    if not api_keys.valid_name(name):
        return bad_request("name must be 1-80 characters")
    role = body.get("role") or users.ROLE_USER
    if not users.valid_role(role):
        return bad_request("role must be admin or user")
    # expires_in_days stays three-valued: absent or null means "use the
    # configured default", 0 means "never expires", and a number means that
    # many days. Collapsing absent into 0 would turn "unset" into "forever".
    ttl_seconds = api_keys.ttl_from_days(body.get("expires_in_days"), get_config(request).api_key_ttl_seconds)
    if ttl_seconds is None:
        return bad_request(f"expires_in_days must be 0 (never) or up to {api_keys.API_KEY_MAX_DAYS}")

    try:
        credential, key = await run(
            api_keys.issue_api_key, get_store(request), actor_from(request).user.id, name, role, ttl_seconds
        )
    except api_keys.APIKeyRoleError:
        return forbidden("you cannot create an API key with more permission than your own account")
    except api_keys.APIKeyLimitError:
        return bad_request("you already have the maximum number of live API keys -- revoke one first")
    except api_keys.APIKeyDisabledError:
        # Not reachable through a live session today, since a disabled
        # account cannot hold one. Mapped anyway so that a future path into
        # this handler fails as a refusal rather than a 500.
        return forbidden("this account is disabled")

    # The credential appears here and nowhere else, ever.
    row = api_key_row(key)
    row["credential"] = credential
    return JSONResponse(row, status_code=201)


async def revoke_my_key(request: Request) -> Response:
    """Takes effect immediately -- the next request carrying that key fails.
    Someone else's key is reported as "no such api key" rather than
    "forbidden", so the endpoint does not confirm which key ids exist."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")

    store = get_store(request)
    key = await run(api_keys.get_api_key, store, request.path_params["key_id"])
    if key is None or key.deleted or key.user_id != actor_from(request).user.id:
        return not_found("no such api key")
    await run(api_keys.revoke_api_key, store, key.id)
    return JSONResponse({"ok": True})


async def delete_my_key(request: Request) -> Response:
    """Delete one of your own keys -- live or already dead. It stops working
    at once and restore_my_key can bring it back for a few minutes. Someone
    else's key is "no such api key", for the same reason as in
    revoke_my_key."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")

    store = get_store(request)
    key = await run(api_keys.get_api_key, store, request.path_params["key_id"])
    if key is None or key.user_id != actor_from(request).user.id:
        return not_found("no such api key")
    # False here means it is already deleted, or vanished since the lookup
    # -- deleted by its owner and an admin at once -- which is still "no such
    # key", not a fault.
    if not await run(api_keys.delete_api_key, store, key.id, actor_from(request).user.id):
        return not_found("no such api key")
    return JSONResponse({"ok": True})


async def restore_my_key(request: Request) -> Response:
    """Undo delete_my_key, within RESTORE_WINDOW. A key an admin deleted is
    the admin's to restore, not its owner's."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")

    store, actor = get_store(request), actor_from(request).user
    key = await run(api_keys.get_api_key, store, request.path_params["key_id"])
    if key is None or key.user_id != actor.id:
        return not_found("no such api key")
    return await _restore(store, key.id, actor)


async def _restore(store: Store, key_id: str, actor: users.User) -> Response:
    try:
        key = await run(api_keys.restore_api_key, store, key_id, actor.id, actor.is_admin)
    except RestoreError as refusal:
        return restore_refused(refusal)
    except api_keys.APIKeyLimitError:
        return conflict("its owner already has the maximum number of live API keys")
    return JSONResponse(api_key_row(key))


async def list_all_keys(request: Request) -> Response:
    """The admin view: every key in the app, with whose it is. This is the
    "who and what has standing access" question, and it is the reason admins
    can see keys they did not create."""
    store = get_store(request)
    keys = await run(api_keys.list_api_keys, store)
    # One pass to build the lookup rather than a get_user per key: a read per
    # row is the shape that quietly becomes slow.
    names = {user.id: user.display_name for user in await run(users.list_users, store)}
    return JSONResponse([api_key_row(key, names.get(key.user_id, "")) for key in keys])


async def revoke_any_key(request: Request) -> Response:
    """How an admin kills a credential belonging to someone else -- a laptop
    that went missing, a CI system being decommissioned, a contractor who has
    finished."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    if await run(api_keys.revoke_api_key, get_store(request), request.path_params["key_id"]) is None:
        return not_found("no such api key")
    return JSONResponse({"ok": True})


async def delete_any_key(request: Request) -> Response:
    """The key stops working and disappears from every listing, its owner's
    included. Unlike revoke_any_key it can be undone, by restore_any_key."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    actor_id = actor_from(request).user.id
    if not await run(api_keys.delete_api_key, get_store(request), request.path_params["key_id"], actor_id):
        return not_found("no such api key")
    return JSONResponse({"ok": True})


async def restore_any_key(request: Request) -> Response:
    """Undo a delete, any key's, within RESTORE_WINDOW."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    return await _restore(get_store(request), request.path_params["key_id"], actor_from(request).user)
