"""API keys are how anything that is not a browser calls this API: a script, a
cron job, a CI pipeline, another service. A key carries a role from the same
set users do, so there is one permission model rather than two -- see
app/models/api_keys.py and references/architecture.md.

Every signed-in user can mint their own keys, and revoke or delete them. An
admin can additionally see, revoke, and delete everyone's, which is what makes
"who has standing access to this app" an answerable question, and can mint one
that acts as someone else (create_key_for_user).

Revoking keeps the row, marked dead, so the listing still shows the key
existed and when it stopped working; the purge drops it later. Deleting
takes it off every listing. Either one stops the key immediately. Only
delete can be undone: for RESTORE_WINDOW the restore routes put a deleted key
back, working again (the Undo on the frontend's toast). Revoke is the switch
for a key that may have leaked, and has no way back.

Minting, revoking, and deleting require a browser session (the routes are registered
behind RequireSession in app/routes/__init__.py), so a leaked key cannot
quietly mint its replacement. The one exception is a key the owner let mint
keys (may_mint_keys): it may mint, list and revoke keys for other accounts
through /api/admin/users/{user_id}/keys and /api/admin/keys/{key_id}/revoke,
behind RequireKeyMinting. What it mints records it and is revoked with it --
see RequireSession and api_keys.revoke_minted_tx.
"""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

import msgspec
from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request
from starlette.responses import Response

from app.apidocs import ADMIN, PATH, QUERY, SESSION_ONLY, Reply, route
from app.apidocs import Request as RequestType
from app.core.db import Store
from app.core.logs import KIND_ADMIN, KIND_AUTH
from app.core.security import Guard, RequireKeyMinting, actor_from
from app.models import RestoreError, api_keys, to_iso, users
from app.routes.admin import DateTime, OkReply, UserIDPath
from app.routes.helpers import Dir, Page, Paged, Refused, get_config, get_store, match_rows, not_found, restore_refusal, sorted_page
from app.routes.logs import audit


class RequireAPIKeys(Guard):
    """Hides the key-management endpoints when the feature is switched off, so
    an app with no programmatic callers can close the surface entirely. The
    Authorization header is ignored in that state too -- that part is enforced
    in app/core/security.py, not here, because it has to hold for every route
    rather than only these."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        if not get_config(request).api_keys_enabled:
            return not_found("api keys are disabled on this server")
        return None


class APIKey(Reply, kw_only=True):
    """The only shape a key is ever returned in. The secret hash is not in
    it, and nor is the credential -- that exists in one response, from
    create_my_key, and is never recoverable afterwards."""

    api_name: ClassVar[str] = "APIKey"
    id: str
    user_id: int
    name: str
    role: Literal["admin", "user", "viewer"]
    created_at: DateTime
    revoked: bool
    expired: bool
    live: bool
    expires_at: DateTime | UnsetType = UNSET
    last_used_at: DateTime | UnsetType = UNSET
    revoked_at: DateTime | UnsetType = UNSET
    display_name: Annotated[str, Meta(description="The key's owner. On the admin list only.")] | UnsetType = UNSET
    created_by: Annotated[int, Meta(description="The admin who made this key for its owner. Absent if the owner made it.")] | UnsetType = UNSET
    created_by_name: str | UnsetType = UNSET
    may_sign_in: Annotated[bool, Meta(description="Whether this key may make a login link for its own account.")]
    may_mint_keys: Annotated[bool, Meta(description="Whether this key may make keys for other accounts. Only the owner switches it on.")]
    minted_by_key: Annotated[str, Meta(description="The key that made this one, or empty. Revoking that key revokes this one.")]


class NewAPIKey(APIKey, kw_only=True):
    api_name: ClassVar[str] = "NewAPIKey"
    credential: Annotated[str, Meta(description="Shown in this response only, and never recoverable.")]


def api_key_row(key: api_keys.APIKey, display_name: str = "") -> APIKey:
    """A key as every route answers it."""
    row = APIKey(
        id=key.id,
        user_id=key.user_id,
        name=key.name,
        role=key.role,  # type: ignore[arg-type]
        created_at=to_iso(key.created_at),
        revoked=key.revoked,
        expired=key.expired,
        live=key.live,
        may_sign_in=key.may_sign_in,
        may_mint_keys=key.may_mint_keys,
        minted_by_key=key.minted_by_key,
    )
    for field_name in ("expires_at", "last_used_at", "revoked_at"):
        value = getattr(key, field_name)
        if value is not None:
            setattr(row, field_name, to_iso(value))
    if display_name:
        row.display_name = display_name
    if key.created_by is not None:
        row.created_by = key.created_by
    return row


def name_creator(row: APIKey, key: api_keys.APIKey, names: dict[int, str]) -> APIKey:
    """Says who made a key on its owner's behalf. An admin deleted since has
    no name, and the page shows their id instead."""
    if key.created_by is not None and names.get(key.created_by):
        row.created_by_name = names[key.created_by]
    return row


def display_names(store: Store) -> dict[int, str]:
    """Every account's name by id: one pass rather than a get_user per key,
    since a read per row is the shape that quietly becomes slow."""
    return {user.id: user.display_name for user in users.list_users(store)}


# ?live=true, for hiding keys that no longer work. The lists keep them
# otherwise: a key that used to exist is part of the answer.
Live = Annotated[Literal["true"], QUERY, Meta(description="Leave out revoked and expired keys.")]


def _only_live(live: str, rows: list[APIKey]) -> list[APIKey]:
    return [row for row in rows if row.live] if live == "true" else rows


class ListMyKeys(Page):
    q: Annotated[str, QUERY, Meta(description="Keep keys whose name contains this, in any case.")] = ""
    live: Live = ""  # type: ignore[assignment]
    sort: Annotated[Literal["name", "role", "last_used_at", "expires_at", "created_at"], QUERY, Meta(description="Field to sort the whole list by. Rows without it go last.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


class KeysReply(Paged):
    keys: list[APIKey]


@route("GET /api/keys", summary="Your API keys", tag="API keys", access=SESSION_ONLY, feature="api_keys")
def list_my_keys(request: Request, body: ListMyKeys) -> KeysReply:
    """Answers "what has standing access as me". Revoked and expired keys are
    included, marked as such, because a key that used to exist is part of
    that answer."""
    store = get_store(request)
    keys = api_keys.list_api_keys_for_user(store, actor_from(request).user.id)
    # Most people have no key someone else made, so the names are only loaded
    # when one is there to be named.
    names = display_names(store) if any(key.created_by is not None for key in keys) else {}
    rows = [name_creator(api_key_row(key), key, names) for key in keys]
    rows = _only_live(body.live, match_rows(rows, body.q, "name"))
    page = sorted_page(rows, body.sort, body.dir, body)
    return KeysReply(keys=page.pop("rows"), **page)


EXPIRY_MESSAGE = f"expires_in_days must be 0 (never) or up to {api_keys.API_KEY_MAX_DAYS}"
KeyName = Annotated[str, Meta(min_length=1, max_length=80, extra={"error": "name must be 1-80 characters"})]
OWNER_KEYS_MESSAGE = "the owner's keys cannot be minted or revoked this way"
MANAGES_KEYS_MCP = "Manages API keys, which no MCP tool does."
MAKES_KEY_MCP = "Makes an API key, which no MCP tool does."
MINT_DAYS_MESSAGE = "expires_in_days must be 1-365"
ExpiresInDays = Annotated[int, Meta(ge=0, le=api_keys.API_KEY_MAX_DAYS, extra={"error": EXPIRY_MESSAGE})]


class CreateMyKey(RequestType):
    name: KeyName
    role: Annotated[Literal["admin", "user", "viewer"], Meta(extra={"error": "role must be admin, user or viewer"})] = "user"
    # Three-valued: absent or null means "use the configured default", 0
    # means "never expires", and a number means that many days. Collapsing
    # absent into 0 would turn "unset" into "forever".
    expires_in_days: Annotated[ExpiresInDays | None, Meta(description="Absent or null: the configured default. 0: never expires.")] = None


def _ttl_seconds(request: Request, days: int | None) -> int:
    ttl_seconds = api_keys.ttl_from_days(days, get_config(request).api_key_ttl_seconds)
    if ttl_seconds is None:
        raise Refused(400, EXPIRY_MESSAGE)
    return ttl_seconds


@route(
    "POST /api/keys", summary="Create an API key",
    tag="API keys", access=SESSION_ONLY, feature="api_keys", status=201,
)
def create_my_key(request: Request, body: CreateMyKey) -> NewAPIKey:
    """Mints a key for the signed-in user and returns the credential once. The
    default role is "user" even for an admin: an admin-scoped key can list and
    disable accounts and revoke anyone's access, so it should be asked for
    rather than handed out by omission.

    The ceiling -- a key cannot outrank its owner -- lives in
    api_keys.issue_api_key, not here, so the CLI gets it too."""
    if not api_keys.valid_name(body.name):
        raise Refused(400, "name must be 1-80 characters")
    ttl_seconds = _ttl_seconds(request, body.expires_in_days)
    try:
        credential, key = api_keys.issue_api_key(get_store(request), actor_from(request).user.id, body.name, body.role, ttl_seconds)
    except api_keys.APIKeyRoleError:
        raise Refused(403, "you cannot create an API key with more permission than your own account") from None
    except api_keys.APIKeyLimitError:
        raise Refused(400, "you already have the maximum number of live API keys -- revoke one first") from None
    except api_keys.APIKeyDisabledError:
        # Not reachable through a live session today, since a disabled
        # account cannot hold one. Mapped anyway so that a future path into
        # this handler fails as a refusal rather than a 500.
        raise Refused(403, "this account is disabled") from None

    audit(request, KIND_ADMIN, "api key created", {"key_id": key.id, "name": key.name, "role": key.role})
    # The credential appears here and nowhere else, ever.
    return NewAPIKey(**msgspec.structs.asdict(api_key_row(key)), credential=credential)


class CreateKeyForUser(CreateMyKey, kw_only=True):
    user_id: Annotated[int, Meta(ge=1, extra={"error": "user_id is required"})]


@route(
    "POST /api/admin/keys", summary="Create a key that acts as someone else",
    tag="API keys", access=SESSION_ONLY, role=ADMIN, feature="api_keys", status=201,
    description="Any admin may do this for an ordinary user, and only the owner for another admin. Nobody "
    "may do it for the owner. The key records who made it and shows that to the person it acts as.",
)
def create_key_for_user(request: Request, body: CreateKeyForUser) -> NewAPIKey:
    """Mints a key that acts as another account, for setting up someone's
    integration for them. It needs a browser session, like every route that
    makes a credential: the admin_keys group adds it, so a leaked admin key
    cannot mint itself a way in as somebody else.

    Who may mint for whom is api_keys.issue_api_key_for's to say. The key
    records who made it, and shows that to the person it acts as."""
    if not api_keys.valid_name(body.name):
        raise Refused(400, "name must be 1-80 characters")
    ttl_seconds = _ttl_seconds(request, body.expires_in_days)
    actor = actor_from(request).user
    try:
        credential, key = api_keys.issue_api_key_for(get_store(request), actor.id, body.user_id, body.name, body.role, ttl_seconds)
    except api_keys.APIKeyOwnerError:
        raise Refused(404, "no such user") from None
    except (api_keys.APIKeyForOwnerError, api_keys.APIKeyForAdminError) as refusal:
        raise Refused(403, str(refusal)) from None
    except api_keys.APIKeyRoleError:
        raise Refused(403, "a key cannot have more permission than the account it belongs to") from None
    except api_keys.APIKeyLimitError:
        raise Refused(400, "that account already has the maximum number of live API keys") from None
    except api_keys.APIKeyDisabledError:
        raise Refused(403, "that account is disabled") from None

    audit(request, KIND_ADMIN, "api key created", {"key_id": key.id, "name": key.name, "role": key.role, "user_id": key.user_id, "created_by": actor.id})
    # The credential appears here and nowhere else, ever.
    return NewAPIKey(**msgspec.structs.asdict(api_key_row(key)), credential=credential)


class KeyIDPath(RequestType):
    """The key a route under /api/keys/{key_id} or /api/admin/keys/{key_id}
    acts on."""

    key_id: Annotated[str, PATH, Meta(description="The key's id, from GET /api/keys (GET /api/admin/keys for anyone's).")]


class RenameKey(KeyIDPath):
    name: Annotated[str, Meta(min_length=1, max_length=80, description="1-80 characters.", extra={"error": "name must be 1-80 characters"})]
    # The name the caller expects to replace. The frontend always sends it,
    # so its undo cannot overwrite a rename made elsewhere.
    expect: Annotated[str | None, Meta(description="The name you think it has. Answers 409 if it has another.")] = None


class RenameKeyReply(Reply):
    ok: bool
    name: str


@route(
    "POST /api/keys/{key_id}/rename", summary="Rename one of your keys",
    tag="API keys", access=SESSION_ONLY, feature="api_keys", errors=(409,),
)
def rename_my_key(request: Request, body: RenameKey) -> RenameKeyReply:
    """Rename one of your own keys. Someone else's is "no such api key", for
    the same reason as in revoke_my_key."""
    return _rename(request, body, own_only=True)


@route(
    "POST /api/admin/keys/{key_id}/rename", summary="Rename anyone's key",
    tag="API keys", access=SESSION_ONLY, role=ADMIN, feature="api_keys", errors=(409,),
)
def rename_any_key(request: Request, body: RenameKey) -> RenameKeyReply:
    """An admin renaming anyone's key. A name changes nothing about what a key
    can do, but it is what the owner goes by when choosing a key to revoke, so
    it follows the same ladder as the key's expiry: nobody renames the owner's
    keys, and only the owner renames another admin's."""
    return _rename(request, body, own_only=False)


def _rename(request: Request, body: RenameKey, own_only: bool) -> RenameKeyReply:
    if not api_keys.valid_name(body.name):
        raise Refused(400, "name must be 1-80 characters")
    store = get_store(request)
    key = api_keys.get_api_key(store, body.key_id)
    if key is None or (own_only and key.user_id != actor_from(request).user.id):
        raise Refused(404, "no such api key")
    try:
        renamed = api_keys.rename_api_key(store, key.id, actor_from(request).user.id, body.name, body.expect)
    except users.RenameConflictError as refusal:
        raise Refused(409, str(refusal), name=refusal.current) from None
    except users.OwnerProtectedError:
        raise Refused(403, "only the owner can rename the owner's keys") from None
    except users.OwnerRequiredError:
        raise Refused(403, "only the owner can rename an admin's keys") from None
    if not renamed:
        raise Refused(404, "no such api key")
    audit(request, KIND_ADMIN, "api key renamed", {"key_id": key.id, "name": body.name.strip()})
    return RenameKeyReply(ok=True, name=body.name.strip())


class SetKeyExpiry(KeyIDPath):
    # Counts from now, and 0 means never, as when minting. Here it is
    # required: there is no default to fall back on.
    expires_in_days: Annotated[ExpiresInDays, Meta(description="Counted from now. 0 means it never expires.")]


@route(
    "POST /api/keys/{key_id}/expiry", summary="Change when one of your keys expires",
    tag="API keys", access=SESSION_ONLY, feature="api_keys",
)
def set_my_key_expiry(request: Request, body: SetKeyExpiry) -> APIKey:
    """Change when one of your own keys expires. The session this group
    requires is what stops a leaked key from extending itself."""
    return _set_expiry(request, body, own_only=True)


@route(
    "POST /api/admin/keys/{key_id}/expiry", summary="Change when anyone's key expires",
    tag="API keys", access=SESSION_ONLY, role=ADMIN, feature="api_keys",
)
def set_any_key_expiry(request: Request, body: SetKeyExpiry) -> APIKey:
    """The same for an admin. Whose keys they may change is
    api_keys.set_api_key_expiry's to say."""
    return _set_expiry(request, body, own_only=False)


def _set_expiry(request: Request, body: SetKeyExpiry, own_only: bool) -> APIKey:
    days = body.expires_in_days
    ttl_seconds = api_keys.ttl_from_days(days, 0)
    if ttl_seconds is None:
        raise Refused(400, EXPIRY_MESSAGE)
    store, actor = get_store(request), actor_from(request).user
    found = api_keys.get_api_key(store, body.key_id)
    if found is None or (own_only and found.user_id != actor.id):
        raise Refused(404, "no such api key")
    try:
        key = api_keys.set_api_key_expiry(store, found.id, actor.id, ttl_seconds)
    except api_keys.APIKeyDeadError:
        raise Refused(400, "only a live key can have its expiry changed -- create a new one instead") from None
    except (api_keys.APIKeyExpiryOwnerError, api_keys.APIKeyExpiryAdminError) as refusal:
        raise Refused(403, str(refusal)) from None
    if key is None:
        raise Refused(404, "no such api key")
    audit(request, KIND_ADMIN, "api key expiry changed", {"key_id": key.id, "expires_in_days": days})
    return api_key_row(key)


class SetKeySignIn(KeyIDPath):
    may_sign_in: Annotated[bool, Meta(description="true lets the key make a login link for your account: one that works once, for at most 15 minutes.")]


@route(
    "POST /api/keys/{key_id}/sign-in", summary="Let one of your keys make sign-in links",
    tag="API keys", access=SESSION_ONLY, feature="api_keys",
    description="Off by default. When on, the key may ask POST /api/account/login-link for a link that "
    "signs your account in on a browser, which then can do everything you can, including what keys may "
    "not. The link works once, for at most 15 minutes.",
)
def set_my_key_sign_in(request: Request, body: SetKeySignIn) -> APIKey:
    """Let one of your own keys make a login link for your account, or stop
    it. Session-only, so a key cannot give itself the right: a link becomes a
    browser session, which opens everything kept from keys. There is no admin
    version. Whether a key may sign in as you is yours alone to decide."""
    try:
        key = api_keys.set_api_key_sign_in(get_store(request), body.key_id, actor_from(request).user.id, body.may_sign_in)
    except api_keys.APIKeyNotYoursError:
        key = None
    except api_keys.APIKeyDeadError:
        raise Refused(400, "only a live key can be allowed to make sign-in links") from None
    except api_keys.APIKeyMintedError as refusal:
        raise Refused(400, str(refusal)) from None
    if key is None:
        raise Refused(404, "no such api key")
    audit(request, KIND_AUTH, "api key sign-in links changed", {"key_id": key.id, "may_sign_in": key.may_sign_in})
    return api_key_row(key)


class SetKeyMintKeys(KeyIDPath):
    may_mint_keys: Annotated[bool, Meta(description="true lets this key make, list and revoke other accounts' keys, each recording this key and revoked with it.")]


@route(
    "POST /api/keys/{key_id}/mint-keys", summary="Let one of your keys make keys",
    tag="API keys", access=SESSION_ONLY, feature="api_keys",
    description="Owner only, on one of your own admin-role keys. When on, the key may make keys for other accounts "
    "(never the owner's) through POST /api/admin/users/{user_id}/keys, list them, and revoke them. Each key it "
    "makes records it, and revoking or deleting this key revokes them all.",
)
def set_my_key_mint_keys(request: Request, body: SetKeyMintKeys) -> APIKey:
    """Let one of the owner's keys mint keys, or stop it. Session-only, like
    every other right a key is given, so no key can grant itself this one.
    Turning it off leaves the keys it minted working; revoking it ends them."""
    try:
        key = api_keys.set_api_key_mint_keys(get_store(request), body.key_id, actor_from(request).user.id, body.may_mint_keys)
    except api_keys.APIKeyNotOwnerError as refusal:
        raise Refused(403, str(refusal)) from None
    except api_keys.APIKeyDeadError:
        raise Refused(400, "only a live key can be allowed to mint keys") from None
    except (api_keys.APIKeyMintedError, api_keys.APIKeyMintRoleError) as refusal:
        raise Refused(400, str(refusal)) from None
    if key is None:
        raise Refused(404, "no such api key")
    audit(request, KIND_AUTH, "api key minting changed", {"key_id": key.id, "may_mint_keys": key.may_mint_keys})
    return api_key_row(key)


@route(
    "POST /api/keys/{key_id}/revoke", summary="Revoke one of your keys",
    tag="API keys", access=SESSION_ONLY, feature="api_keys",
)
def revoke_my_key(request: Request, body: KeyIDPath) -> OkReply:
    """Takes effect immediately -- the next request carrying that key fails.
    Someone else's key is reported as "no such api key" rather than
    "forbidden", so the endpoint does not confirm which key ids exist."""
    store = get_store(request)
    key = api_keys.get_api_key(store, body.key_id)
    if key is None or key.deleted or key.user_id != actor_from(request).user.id:
        raise Refused(404, "no such api key")
    api_keys.revoke_api_key(store, key.id)
    audit(request, KIND_ADMIN, "api key revoked", {"key_id": body.key_id})
    return OkReply(ok=True)


@route(
    "POST /api/keys/{key_id}/delete", summary="Delete one of your keys",
    tag="API keys", access=SESSION_ONLY, feature="api_keys",
)
def delete_my_key(request: Request, body: KeyIDPath) -> OkReply:
    """Delete one of your own keys -- live or already dead. It stops working
    at once and restore_my_key can bring it back for a few minutes. Someone
    else's key is "no such api key", for the same reason as in
    revoke_my_key."""
    store = get_store(request)
    key = api_keys.get_api_key(store, body.key_id)
    if key is None or key.user_id != actor_from(request).user.id:
        raise Refused(404, "no such api key")
    # False here means it is already deleted, or vanished since the lookup
    # -- deleted by its owner and an admin at once -- which is still "no such
    # key", not a fault.
    if not api_keys.delete_api_key(store, key.id, actor_from(request).user.id):
        raise Refused(404, "no such api key")
    audit(request, KIND_ADMIN, "api key deleted", {"key_id": body.key_id})
    return OkReply(ok=True)


@route(
    "POST /api/keys/{key_id}/restore", summary="Undo deleting one of your keys",
    tag="API keys", access=SESSION_ONLY, feature="api_keys", errors=(409,),
)
def restore_my_key(request: Request, body: KeyIDPath) -> APIKey:
    """Undo delete_my_key, within RESTORE_WINDOW. A key an admin deleted is
    the admin's to restore, not its owner's."""
    store, actor = get_store(request), actor_from(request).user
    key = api_keys.get_api_key(store, body.key_id)
    if key is None or key.user_id != actor.id:
        raise Refused(404, "no such api key")
    row = _restore(store, key.id, actor)
    audit(request, KIND_ADMIN, "api key restored", {"key_id": body.key_id})
    return row


def _restore(store: Store, key_id: str, actor: users.User) -> APIKey:
    try:
        key = api_keys.restore_api_key(store, key_id, actor.id, actor.is_admin)
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None
    except (users.OwnerProtectedError, users.OwnerRequiredError) as refusal:
        raise _owner_refused(refusal, "restore") from None
    except api_keys.APIKeyLimitError:
        raise Refused(409, "its owner already has the maximum number of live API keys") from None
    return api_key_row(key)


def _owner_refused(refusal: Exception, what: str = "change") -> Refused:
    """users.may_act_on_tx's refusal for a key, worded like the other routes'."""
    if isinstance(refusal, users.OwnerProtectedError):
        return Refused(403, f"only the owner can {what} the owner's keys")
    return Refused(403, f"only the owner can {what} an admin's keys")


class ListAllKeys(Page):
    q: Annotated[str, QUERY, Meta(description="Keep keys whose name or owner contains this, in any case.")] = ""
    live: Live = ""  # type: ignore[assignment]
    sort: Annotated[Literal["display_name", "name", "role", "last_used_at", "expires_at", "created_at"], QUERY, Meta(description="Field to sort the whole list by. Rows without it go last.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


@route(
    "GET /api/admin/keys", summary="Every key in the app",
    tag="API keys", access=SESSION_ONLY, role=ADMIN, feature="api_keys",
)
def list_all_keys(request: Request, body: ListAllKeys) -> KeysReply:
    """The admin view: every key in the app, with whose it is. This is the
    "who and what has standing access" question, and it is the reason admins
    can see keys they did not create."""
    store = get_store(request)
    keys = api_keys.list_api_keys(store)
    names = display_names(store)
    rows = [name_creator(api_key_row(key, names.get(key.user_id, "")), key, names) for key in keys]
    rows = _only_live(body.live, match_rows(rows, body.q, "name", "display_name"))
    page = sorted_page(rows, body.sort, body.dir, body)
    return KeysReply(keys=page.pop("rows"), **page)


@route(
    "POST /api/admin/keys/{key_id}/revoke", summary="Revoke anyone's key",
    tag="API keys", role=ADMIN, feature="api_keys", use=[RequireKeyMinting],
    description="Stops the key at once, and every key it made, down the chain. Needs a browser session or a key "
    "with may_mint_keys (any other key gets 403 key_minting_off), which may not revoke the owner's keys.",
    mcp_http=MANAGES_KEYS_MCP,
)
def revoke_any_key(request: Request, body: KeyIDPath) -> OkReply:
    """How an admin kills a credential belonging to someone else -- a laptop
    that went missing, a CI system being decommissioned, a contractor who has
    finished -- and how a minting key (an outside admin tool such as
    ProjectPortal) takes back one it handed out."""
    actor = actor_from(request)
    store = get_store(request)
    if actor.via_api_key:
        found = api_keys.get_api_key(store, body.key_id)
        if found is not None and found.user_id == users.get_owner_id(store):
            raise Refused(403, OWNER_KEYS_MESSAGE)
    try:
        revoked = api_keys.revoke_api_key(store, body.key_id, actor.user.id)
    except (users.OwnerProtectedError, users.OwnerRequiredError) as refusal:
        raise _owner_refused(refusal) from None
    if revoked is None:
        raise Refused(404, "no such api key")
    audit(request, KIND_ADMIN, "api key revoked", {"key_id": body.key_id})
    return OkReply(ok=True)




class MintKey(UserIDPath):
    name: KeyName
    role: Annotated[Literal["admin", "user", "viewer"], Meta(description="Capped at the account's own role.", extra={"error": "role must be admin, user or viewer"})]
    expires_in_days: Annotated[int, Meta(ge=1, le=365, description="Required: 1-365. A minted key always expires.", extra={"error": MINT_DAYS_MESSAGE})]


@route(
    "POST /api/admin/users/{user_id}/keys", summary="Make a key for an account",
    tag="API keys", role=ADMIN, feature="api_keys", status=201, use=[RequireKeyMinting], errors=(404,),
    description="Needs a browser session or a key the owner allowed to make keys (may_mint_keys); any other key "
    "gets 403 key_minting_off. The role is capped at the account's own; expires_in_days is required (1-365). "
    "Never for the owner. The new key records the key that made it, can never make keys or sign-in links itself, "
    "and is revoked when that key is revoked or deleted. Answers with the key and its credential, shown only now.",
    mcp_http=MAKES_KEY_MCP,
)
def mint_key_for_user(request: Request, body: MintKey) -> NewAPIKey:
    """Mint a key for another account, for an outside admin tool that runs the
    app (ProjectPortal's Manage screen). The rules are api_keys.mint_api_key's."""
    if not api_keys.valid_name(body.name):
        raise Refused(400, "name must be 1-80 characters")
    actor = actor_from(request)
    try:
        credential, key = api_keys.mint_api_key(
            get_store(request), actor.user.id, actor.key_id, body.user_id, body.name, body.role, body.expires_in_days * 24 * 60 * 60,
        )
    except api_keys.APIKeyOwnerError:
        raise Refused(404, "no such user") from None
    except api_keys.APIKeyForOwnerError:
        raise Refused(403, OWNER_KEYS_MESSAGE) from None
    except api_keys.APIKeyForAdminError as refusal:
        raise Refused(403, str(refusal)) from None
    except api_keys.APIKeyRoleError:
        raise Refused(403, "a key cannot have more permission than the account it belongs to") from None
    except api_keys.APIKeyLimitError:
        raise Refused(400, "that account already has the maximum number of live API keys") from None
    except api_keys.APIKeyDisabledError:
        raise Refused(403, "that account is disabled") from None
    audit(request, KIND_ADMIN, "api key minted", {"key_id": key.id, "name": key.name, "role": key.role, "user_id": key.user_id, "minted_by_key": key.minted_by_key})
    # The credential appears here and nowhere else, ever.
    return NewAPIKey(**msgspec.structs.asdict(api_key_row(key)), credential=credential)


class UserKeysReply(Reply):
    keys: list[APIKey]


@route(
    "GET /api/admin/users/{user_id}/keys", summary="An account's keys",
    tag="API keys", role=ADMIN, feature="api_keys", use=[RequireKeyMinting], errors=(404,),
    description="One account's keys, revoked and expired ones included, newest first. Each row says which key "
    "minted it (minted_by_key, empty when a person made it). Needs a browser session or a key with may_mint_keys; "
    "any other key gets 403 key_minting_off.",
    mcp_http=MANAGES_KEYS_MCP,
)
def list_user_keys(request: Request, body: UserIDPath) -> UserKeysReply:
    """One account's keys, for the tool that mints them."""
    store = get_store(request)
    if users.get_user(store, body.user_id) is None:
        raise Refused(404, "no such user")
    keys = api_keys.list_api_keys_for_user(store, body.user_id)
    names = display_names(store)
    return UserKeysReply(keys=[name_creator(api_key_row(key, names.get(key.user_id, "")), key, names) for key in keys])


@route(
    "POST /api/admin/keys/{key_id}/delete", summary="Delete anyone's key",
    tag="API keys", access=SESSION_ONLY, role=ADMIN, feature="api_keys",
)
def delete_any_key(request: Request, body: KeyIDPath) -> OkReply:
    """The key stops working and disappears from every listing, its owner's
    included. Unlike revoke_any_key it can be undone, by restore_any_key."""
    try:
        deleted = api_keys.delete_api_key(get_store(request), body.key_id, actor_from(request).user.id)
    except (users.OwnerProtectedError, users.OwnerRequiredError) as refusal:
        raise _owner_refused(refusal) from None
    if not deleted:
        raise Refused(404, "no such api key")
    audit(request, KIND_ADMIN, "api key deleted", {"key_id": body.key_id})
    return OkReply(ok=True)


@route(
    "POST /api/admin/keys/{key_id}/restore", summary="Undo deleting anyone's key",
    tag="API keys", access=SESSION_ONLY, role=ADMIN, feature="api_keys", errors=(409,),
)
def restore_any_key(request: Request, body: KeyIDPath) -> APIKey:
    """Undo a delete, any key's, within RESTORE_WINDOW."""
    row = _restore(get_store(request), body.key_id, actor_from(request).user)
    audit(request, KIND_ADMIN, "api key restored", {"key_id": body.key_id})
    return row
