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

from dataclasses import replace
from datetime import datetime, timezone
from typing import Annotated, Any, ClassVar, Literal

import msgspec
from msgspec import Meta
from starlette.requests import Request

from app.apidocs import ADMIN, PATH, QUERY, SESSION_ONLY, Reply, route
from app.apidocs import Request as RequestType
from app.core.error_codes import CODE_OWNER_PROTECTED, CODE_OWNER_REQUIRED
from app.core.db import Store
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from
from app.models import credentials, from_iso, login_tokens, to_iso, users, utc_now
from app.models import api_keys
from app.models import passwords
from app.models import two_factor
from app.routes.helpers import DateTime, Dir, Page, Paged, Refused, act_on_refusals, get_config, get_store, service_account_refusal, sorted_page
from app.routes.logs import audit
from app.routes.mcp_tools_accounts import with_login_url
from app.routes.mcp_tools_accounts import two_factor_on

# The two things every route that mints a login link may ask for, both
# optional (see login_tokens.resolve_link).
LINK_LIMITS = "max_uses must be 0 (unlimited) or 1-1000, expires_in_minutes 0 (never) or 1-525600"
MaxUses = Annotated[int, Meta(ge=0, le=1000, description="Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1.", extra={"error": LINK_LIMITS})]
ExpiresInMinutes = Annotated[int, Meta(ge=0, le=525600, description="0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise.", extra={"error": LINK_LIMITS})]
DisplayName = Annotated[str, Meta(min_length=1, max_length=80, extra={"error": "display name must be 1-80 characters"})]
Role = Annotated[Literal["admin", "user", "viewer"], Meta(extra={"error": "role must be admin, user or viewer"})]


class UserIDPath(RequestType):
    """The account a route under /api/admin/users/{user_id} acts on."""

    user_id: Annotated[int, PATH, Meta(ge=1, description="The account's id, from GET /api/admin/users (admin_list_users over MCP).", extra={"error": "invalid user id"})]


class LoginLink(Reply):
    """A login link as the UI shows it."""

    api_name: ClassVar[str] = "LoginLink"
    api_doc: ClassVar[str] = "A login link that can still be used. One per account at most."
    max_uses: Annotated[int, Meta(description="Sign-ins it allows. 0 when unlimited.")]
    unlimited: bool
    uses: Annotated[int, Meta(description="Sign-ins so far.")]
    created_at: DateTime
    expires_at: Annotated[DateTime | None, Meta(description="null when it never expires.")]
    last_used_at: DateTime | None


class Revoked(Reply):
    """What revoking an account's access, or deleting it, took away."""

    api_name: ClassVar[str] = "Revoked"
    sessions: int
    login_links: int
    api_keys: Annotated[int, Meta(extra_json_schema={"x-feature": "api_keys"})]
    passwords: Annotated[int, Meta(extra_json_schema={"x-feature": "passwords"})]


class UserRow(Reply):
    """An account as the admin screen lists it. The owner is marked on its
    row, so the UI can tell which delete, disable, and revoke buttons the
    server would refuse."""

    api_name: ClassVar[str] = "User"
    id: int
    display_name: str
    username: Annotated[str, Meta(description="Empty until a password is set.", extra_json_schema={"x-feature": "passwords"})]
    role: Literal["admin", "user", "viewer"]
    created_at: DateTime
    disabled: Annotated[bool, Meta(description="Switched off, or its expiry has passed.")]
    expires_at: Annotated[DateTime | None, Meta(description="When the account stops working, or null for never.")]
    expired: Annotated[bool, Meta(description="Whether expires_at has passed.")]
    owner: bool
    kind: Annotated[Literal["person", "service"], Meta(description="person, or service for an account with API keys only (ProjectPortal's own).")]
    has_password: Annotated[bool, Meta(extra_json_schema={"x-feature": "passwords"})]
    password_blocked: Annotated[bool, Meta(extra_json_schema={"x-feature": "passwords"})]
    two_factor: Annotated[bool, Meta(extra_json_schema={"x-feature": "two_factor"})]
    login_link: Annotated[LoginLink | None, Meta(description="The account's live login link, or null.")]
    can_show_others: Annotated[bool, Meta(description="Whether this account has the Showing picker (admins always do).")]
    showing_locked: Annotated[bool, Meta(description="Whether an admin has fixed whose lists it sees.")]
    default_subject: Annotated[int | None, Meta(description="Whose lists it starts on: a user id, or null for its own.")]


class ListUsers(Page):
    q: Annotated[str, QUERY, Meta(description="Keep accounts whose name or username contains this, in any case.")] = ""
    sort: Annotated[Literal["display_name", "role", "disabled", "created_at"], QUERY, Meta(description="Field to sort the whole list by. Rows without it go last.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


class ListUsersReply(Paged):
    users: list[UserRow]


@route(
    "GET /api/admin/users", summary="List users",
    tag="Admin", role=ADMIN,
    description="Accounts, a page at a time, including disabled ones, with each one's role and which is the "
    "owner. next is the offset of the following page, or null on the last one.",
    mcp="admin_list_users", read_only=True,
)
def list_users(request: Request, body: ListUsers) -> ListUsersReply:
    """Every account, a page at a time. ?q= keeps the accounts whose name or
    username contains it, in any case. Here and not in the browser, which only
    ever holds one page of them."""
    page = sorted_page(user_rows(get_store(request), body.q), body.sort, body.dir, body)
    return ListUsersReply(users=page.pop("rows"), **page)


def user_rows(store: Store, query: str = "") -> list[UserRow]:
    owner_id = users.get_owner_id(store)
    links = login_tokens.live_login_links(store)
    wanted = query.strip().lower()
    return [
        UserRow(
            id=u.id,
            display_name=u.display_name,
            username=u.username or "",
            role=u.role,
            created_at=to_iso(u.created_at),
            disabled=u.disabled,
            expires_at=to_iso(u.expires_at),
            expired=u.expired,
            owner=u.id == owner_id,
            kind=u.kind,  # type: ignore[arg-type]
            has_password=passwords.has_password(u),
            password_blocked=u.password_blocked,
            two_factor=two_factor.is_on(u),
            login_link=msgspec.convert(links[u.id], LoginLink) if u.id in links else None,
            can_show_others=u.can_show_others,
            showing_locked=u.showing_locked,
            default_subject=u.default_subject,
        )
        for u in users.list_users(store)
        if wanted in u.display_name.lower() or wanted in (u.username or "").lower()
    ]


def link_options(request: Request, body: Any) -> login_tokens.LinkOptions:
    """What the request asked a new login link to allow, with the configured
    defaults filling the gaps (see login_tokens.resolve_link), and the API key
    asking, if one is, so revoking that key voids the link. body is a dict or
    a request type with max_uses and expires_in_minutes."""
    cfg = get_config(request)
    asked = body if isinstance(body, dict) else {"max_uses": body.max_uses, "expires_in_minutes": body.expires_in_minutes}
    try:
        options = login_tokens.resolve_link(
            asked.get("max_uses"), asked.get("expires_in_minutes"),
            cfg.login_token_ttl_seconds, cfg.multi_use_login_token_ttl_seconds,
        )
    except login_tokens.BadLoginLinkError as refusal:
        raise Refused(400, str(refusal)) from None
    return replace(options, minted_by_key=actor_from(request).lineage_key)


class LoginLinkReply(Reply):
    """What every route that mints a link answers. The link is a path, not a
    full URL (see create_user); the MCP tools add login_url from the address
    the agent reached /mcp at."""

    login_path: Annotated[str, Meta(description="Path of the login link. A credential: treat it like a password.")]
    expires_in_seconds: Annotated[int, Meta(description="0 when it never expires.")]
    expires_at: Annotated[DateTime | None, Meta(description="null when it never expires.")]
    max_uses: Annotated[int, Meta(description="0 when unlimited.")]
    unlimited: bool


def link_reply(credential: str, info: dict) -> dict[str, Any]:
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


EXPIRY_FORMAT = "must be an RFC 3339 time or null"
AccountExpiry = Annotated[str, Meta(extra_json_schema={"format": "date-time"})]


def parse_expiry(value: str | None, field: str) -> datetime | None:
    """An account expiry as a request sends it: an RFC 3339 time with its
    offset, or None for never. 400 for anything else, and for a time that is
    not in the future."""
    if value is None:
        return None
    # account_expires_at may only be left out, so its message has no "or null".
    bad = f"{field} {EXPIRY_FORMAT}" if field == "expires_at" else f"{field} must be an RFC 3339 time"
    try:
        when = datetime.fromisoformat(value.strip())
    except ValueError:
        raise Refused(400, bad) from None
    if when.tzinfo is None:
        raise Refused(400, bad)
    if when <= utc_now():
        raise Refused(400, f"{field} must be in the future")
    return when.astimezone(timezone.utc)


class CreateUser(RequestType):
    display_name: DisplayName
    role: Role
    max_uses: MaxUses | None = None
    expires_in_minutes: ExpiresInMinutes | None = None
    account_expires_at: Annotated[AccountExpiry | None, Meta(description="When the account stops working (RFC 3339). Left out: never. expires_in_minutes is the login link's expiry, not this.")] = None
    kind: Annotated[Literal["person", "service"], Meta(description="person, the default. service is refused (403 service_account): a service account is made by Connect on the owner's API keys screen.")] = "person"


class CreateUserReply(LoginLinkReply):
    user_id: int


@route(
    "POST /api/admin/users", summary="Create an account",
    tag="Admin", role=ADMIN, status=201,
    description="Make a new account and its first login link, to hand to the person. role is admin, user or "
    "viewer (reads only). account_expires_at, when given, is when the "
    "account stops working. Answers with user_id and the link.",
    mcp_note="Answers with login_url (open it to sign in; it works once unless max_uses says otherwise), "
    "expires_at and max_uses. Any older link the account could still use stops working; its signed-in "
    "devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs "
    "out every device it signed in.",
    mcp="admin_create_user", call=with_login_url,
)
def create_user(request: Request, body: CreateUser) -> CreateUserReply:
    """The signup process: an admin names someone, and gets back a login link
    to hand them -- once by default, or reusable (see
    login_tokens.resolve_link). The link is returned as a path, not a full URL -- the
    browser knows the origin it is talking to, whereas the server behind a
    reverse proxy often does not, and a login link with the wrong host is
    worse than useless."""
    if body.kind == users.KIND_SERVICE:
        raise service_account_refusal()
    if not users.valid_display_name(body.display_name):
        raise Refused(400, "display name must be 1-80 characters")
    account_expires_at = parse_expiry(body.account_expires_at, "account_expires_at")
    options = link_options(request, body)
    store = get_store(request)
    user = users.create_user(store, body.display_name, body.role, account_expires_at)
    credential, info = login_tokens.issue_login_link(store, user.id, options)
    audit(request, KIND_ADMIN, "user created", {"user_id": user.id, "name": user.display_name, "role": user.role})
    return CreateUserReply(user_id=user.id, **link_reply(credential, info))


class ReissueLogin(UserIDPath):
    max_uses: MaxUses | None = None
    expires_in_minutes: ExpiresInMinutes | None = None


def key_login_link_options(request: Request, options: login_tokens.LinkOptions) -> login_tokens.LinkOptions:
    """The rules for a login link an API key asks for its own account, the same
    on every route that makes one: only a key its account let make sign-in
    links (may_sign_in), and only once, for at most 15 minutes, whatever it
    asked for. Unchanged for a browser session."""
    actor = actor_from(request)
    if actor.api_key is None:
        return options
    if not actor.api_key.may_sign_in:
        raise Refused(403, "this key may not make sign-in links: turn that on for it on the API keys card")
    ttl = options.ttl_seconds
    if ttl <= 0 or ttl > api_keys.KEY_LOGIN_LINK_TTL_SECONDS:
        ttl = api_keys.KEY_LOGIN_LINK_TTL_SECONDS
    return replace(options, max_uses=1, unlimited=False, ttl_seconds=ttl)


@route(
    "POST /api/admin/users/{user_id}/reissue-login", summary="A new login link for an account",
    tag="Admin", role=ADMIN, errors=(404,),
    description="For someone who lost their device or their link: a fresh login link for their account.",
    mcp_note="Answers with login_url (open it to sign in; it works once unless max_uses says otherwise), "
    "expires_at and max_uses. Any older link the account could still use stops working; its signed-in "
    "devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs "
    "out every device it signed in.",
    mcp="admin_reissue_login", call=with_login_url,
)
def reissue_login(request: Request, body: ReissueLogin) -> LoginLinkReply:
    """Covers the only real failure mode of this auth model: someone lost
    their cookie or their device, and there is no password reset to fall back
    on. An admin mints a fresh link instead. Any link the account could still
    sign in with stops working (see login_tokens.issue_login_link).

    It is not a reset: sessions the account already has stay signed in. When
    the worry is that someone else holds the account's credentials, use
    revoke_access first, then reissue."""
    store = get_store(request)
    if users.get_user(store, body.user_id) is None:
        raise Refused(404, "no such user")
    options = replace(link_options(request, body), actor_id=actor_from(request).user.id)
    # A key reissuing its own account's link is a key asking for a sign-in
    # link: the same rules as POST /api/account/login-link (may_sign_in, once,
    # 15 minutes), or this route would be the way round them.
    if body.user_id == actor_from(request).user.id:
        options = key_login_link_options(request, options)
    with act_on_refusals("reissue a login link for"):
        credential, info = login_tokens.issue_login_link(store, body.user_id, options)
    audit(request, KIND_ADMIN, "login link reissued", {"user_id": body.user_id, "max_uses": info["max_uses"], "expires_at": info["expires_at"]})
    return LoginLinkReply(**link_reply(credential, info))


class CancelLoginLinkReply(Reply):
    ok: bool
    removed: Annotated[int, Meta(description="Links removed: 0 or 1.")]


@route(
    "POST /api/admin/users/{user_id}/cancel-login-link", summary="Stop an account's login link working",
    bulk=True,
    tag="Admin", role=ADMIN, errors=(404,),
    description="Void an account's live login link without making a new one: a link that went somewhere it "
    "should not have.",
    mcp_note="Devices it already signed in stay signed in; admin_revoke_access ends those too. Answers with "
    "removed: 0 or 1.",
    mcp="admin_cancel_login_link", destructive=True,
)
def cancel_login_link(request: Request, body: UserIDPath) -> CancelLoginLinkReply:
    """Stop an account's live login link working, without making a new one:
    a reusable link that went somewhere it should not have. Sessions it
    already made stay signed in; revoke_access ends those too.

    An API key may do this, like revoke_access: it only takes a way in away."""
    store = get_store(request)
    if users.get_user(store, body.user_id) is None:
        raise Refused(404, "no such user")
    with act_on_refusals("cancel the login link of"):
        removed = login_tokens.cancel_login_link(store, body.user_id, actor_from(request).user.id)
    audit(request, KIND_ADMIN, "login link cancelled", {"user_id": body.user_id, "removed": removed})
    return CancelLoginLinkReply(ok=True, removed=removed)


class OkReply(Reply):
    """The answer of a route that has nothing to say but yes."""

    ok: bool


class SetUserDisabled(UserIDPath):
    disabled: Annotated[bool, Meta(extra={"error": "disabled must be true or false"})]


@route(
    "POST /api/admin/users/{user_id}/disabled", summary="Disable or enable a user",
    bulk=True,
    tag="Admin", role=ADMIN, errors=(404,),
    description="Switch an account off (disabled: true) or back on (false). Disabling signs it out "
    "everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The "
    "owner and your own account cannot be disabled.",
    mcp="admin_set_user_disabled",
)
def set_user_disabled(request: Request, body: SetUserDisabled) -> OkReply:
    """Switch an account off, or back on, over HTTP and as the MCP
    admin_set_user_disabled tool."""
    store, self_id = get_store(request), actor_from(request).user.id
    if users.get_user(store, body.user_id) is None:
        raise Refused(404, "no such user")
    # Locking yourself out is unrecoverable without shell access, so it is
    # worth one guard rail even though an admin could still disable a peer.
    if body.disabled and body.user_id == self_id:
        raise Refused(400, "you cannot disable your own account")
    # Disabling also deletes the account's sessions and live login links,
    # in the same transaction -- see credentials.set_user_disabled. The owner
    # cannot be disabled, and only the owner switches another admin off or
    # on; those checks are in the model so every route gets them.
    try:
        found = credentials.set_user_disabled(store, body.user_id, body.disabled, actor_id=self_id)
    except credentials.OwnerProtectedError:
        raise Refused(403, "the owner account cannot be disabled", code=CODE_OWNER_PROTECTED) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can disable or enable an admin account", code=CODE_OWNER_REQUIRED) from None
    if not found:
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "user disabled set", {"user_id": body.user_id, "disabled": body.disabled})
    return OkReply(ok=True)


class RevokeAccessReply(Reply):
    ok: bool
    revoked: Revoked


@route(
    "POST /api/admin/users/{user_id}/revoke-access", summary="Revoke a user's access",
    bulk=True,
    tag="Admin", role=ADMIN, errors=(404,),
    description="For an account that may be compromised: ends every session and voids its live login link "
    "and every API key it holds, at once.",
    mcp_note="The account stays enabled; admin_reissue_login lets its owner back in. The owner and your own "
    "account cannot be revoked.",
    mcp="admin_revoke_access", destructive=True,
)
def revoke_access(request: Request, body: UserIDPath) -> RevokeAccessReply:
    """The response to "this account may be compromised": every session,
    live login link, and live API key it holds stops working at once. The
    account itself stays enabled; reissue a login link to let its owner back
    in. See credentials.revoke_all_credentials for why this is separate from
    both disabling and reissuing. Over HTTP and as the MCP
    admin_revoke_access tool."""
    self_id = actor_from(request).user.id
    # Same guard rail as disabling: revoking your own access signs you out
    # with no link to get back in.
    if body.user_id == self_id:
        raise Refused(400, "you cannot revoke your own access")
    # The owner is refused here (allow_owner False), and only the owner
    # revokes another admin. Only an operator with shell access may cut the
    # owner off -- see revoke_all_credentials.
    try:
        revoked = credentials.revoke_all_credentials(get_store(request), body.user_id, actor_id=self_id)
    except credentials.OwnerProtectedError:
        raise Refused(403, "the owner account's access cannot be revoked", code=CODE_OWNER_PROTECTED) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can revoke the access of an admin account", code=CODE_OWNER_REQUIRED) from None
    if revoked is None:
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "access revoked", {"user_id": body.user_id})
    return RevokeAccessReply(ok=True, revoked=msgspec.convert(revoked.to_dict(), Revoked))


class RenameUser(UserIDPath):
    display_name: Annotated[str, Meta(min_length=1, max_length=80, description="1-80 characters.", extra={"error": "display name must be 1-80 characters"})]
    expect: Annotated[str | None, Meta(description="The name you think they have. Answers 409 if it is another.")] = None


class RenameUserReply(Reply):
    ok: bool
    display_name: str


@route(
    "POST /api/admin/users/{user_id}/rename", summary="Rename someone",
    tag="Admin", role=ADMIN, errors=(404, 409),
    description="Change another account's display name (1-80 characters). Only the owner renames an admin. "
    "expect, when given, is the name you think it has now; if it changed meanwhile the rename is refused "
    "with the current name.",
    mcp="admin_rename_user",
)
def rename_user(request: Request, body: RenameUser) -> RenameUserReply:
    """An admin renaming someone else. Who may rename whom lives in
    credentials.rename_user_as."""
    if not users.valid_display_name(body.display_name):
        raise Refused(400, "display name must be 1-80 characters")
    try:
        found = credentials.rename_user_as(get_store(request), body.user_id, actor_from(request).user.id, body.display_name, body.expect)
    except users.RenameConflictError as stale:
        raise Refused(409, str(stale), display_name=stale.current) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can rename an admin", code=CODE_OWNER_REQUIRED) from None
    if not found:
        raise Refused(404, "no such user")
    name = body.display_name.strip()
    audit(request, KIND_ADMIN, "user renamed", {"user_id": body.user_id, "name": name})
    return RenameUserReply(ok=True, display_name=name)


class SetUserRole(UserIDPath):
    role: Role


class SetUserRoleReply(Reply):
    ok: bool
    role: str


@route(
    "POST /api/admin/users/{user_id}/role", summary="Change an account's role",
    bulk=True,
    tag="Admin", role=ADMIN, errors=(404,),
    description="Make an account an admin, an ordinary user, or a viewer, who may read but change nothing. Only the "
    "owner takes an admin's rights away; "
    "the owner is always an admin, and nobody changes their own role. Becoming an admin ends the account's "
    "sessions and live login link.",
    mcp="admin_set_user_role",
)
def set_user_role(request: Request, body: SetUserRole) -> SetUserRoleReply:
    """Make an account an admin, a user or a viewer. Who may do what lives in
    credentials.set_user_role."""
    try:
        changed = credentials.set_user_role(get_store(request), body.user_id, actor_from(request).user.id, body.role)
    except credentials.SelfRoleError as refusal:
        raise Refused(400, str(refusal)) from None
    except credentials.OwnerProtectedError:
        raise Refused(403, "the owner is always an admin", code=CODE_OWNER_PROTECTED) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can take away an admin's rights", code=CODE_OWNER_REQUIRED) from None
    except credentials.ServiceAccountError:
        raise service_account_refusal() from None
    if changed is None:
        raise Refused(404, "no such user")
    if changed:
        audit(request, KIND_ADMIN, "user role changed", {"user_id": body.user_id, "role": body.role})
    return SetUserRoleReply(ok=True, role=body.role)


class SetUserShowing(UserIDPath):
    can_show_others: Annotated[bool, Meta(description="Give the account the Showing picker, or take it away.", extra={"error": "can_show_others must be true or false"})]
    default_subject: Annotated[int | None, Meta(description="Whose lists it starts on: a user id, or null for its own.", extra={"error": "default_subject must be a user id or null"})] = None
    showing_locked: Annotated[bool, Meta(description="Fix the picker on default_subject, so it cannot be changed.", extra={"error": "showing_locked must be true or false"})] = False


class SetUserShowingReply(Reply):
    ok: bool
    can_show_others: bool
    default_subject: int | None
    showing_locked: bool


@route(
    "POST /api/admin/users/{user_id}/showing", summary="Set an account's Showing picker",
    tag="Admin", role=ADMIN, access=SESSION_ONLY, errors=(404,),
    description="Give an ordinary account the Showing picker (or take it away), say whose lists it starts "
    "on, and optionally lock it there. Admins always have the picker.",
)
def set_user_showing(request: Request, body: SetUserShowing) -> SetUserShowingReply:
    """Give an ordinary account the Showing picker (or take it away) and say
    whose lists it starts on. Admins always have the picker, so this only
    matters for users; it still accepts any account so the flag survives a
    role change either way. Needs a browser session."""
    try:
        user = users.set_showing(get_store(request), body.user_id, body.can_show_others, body.default_subject, body.showing_locked)
    except users.NoSuchSubjectError:
        raise Refused(404, "no such user to start on") from None
    if user is None:
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "user showing changed", {"user_id": body.user_id, "can_show_others": user.can_show_others, "default_subject": user.default_subject, "showing_locked": user.showing_locked})
    return SetUserShowingReply(ok=True, can_show_others=user.can_show_others, default_subject=user.default_subject, showing_locked=user.showing_locked)


class SetUserExpiry(UserIDPath):
    expires_at: Annotated[AccountExpiry | None, Meta(description="When the account stops working (RFC 3339), or null for never.")]


class SetUserExpiryReply(Reply):
    ok: bool
    expires_at: Annotated[DateTime | None, Meta(description="null when it never expires.")]


@route(
    "POST /api/admin/users/{user_id}/expiry", summary="Set when an account expires",
    tag="Admin", role=ADMIN, errors=(404,),
    description="expires_at is when the account stops working (RFC 3339), or null for never. Once it passes the "
    "account counts as disabled: sign-in, its sessions and its keys stop, and housekeeping disables it and revokes "
    "its access. A later expiry does not re-enable an account housekeeping already disabled. It must be in the "
    "future. The owner's account never expires, nobody sets their own, and only the owner sets an admin's.",
    mcp="admin_set_user_expiry",
)
def set_user_expiry(request: Request, body: SetUserExpiry) -> SetUserExpiryReply:
    """Set or clear an account's expiry. Who may do it lives in
    credentials.set_user_expiry. Clearing it does not switch back on an
    account housekeeping already disabled for expiring: that is
    set_user_disabled, deliberately."""
    expires_at = parse_expiry(body.expires_at, "expires_at")
    try:
        found = credentials.set_user_expiry(get_store(request), body.user_id, actor_from(request).user.id, expires_at)
    except credentials.ExpiryPastError as refusal:
        raise Refused(400, str(refusal)) from None
    except credentials.OwnerExpiryError as refusal:
        raise Refused(403, str(refusal), code=CODE_OWNER_PROTECTED) from None
    except credentials.ExpirySelfError as refusal:
        raise Refused(403, str(refusal)) from None
    except credentials.OwnerProtectedError:
        raise Refused(403, "the owner's account cannot expire", code=CODE_OWNER_PROTECTED) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can set when an admin account expires", code=CODE_OWNER_REQUIRED) from None
    if not found:
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "user expiry set", {"user_id": body.user_id, "expires_at": to_iso(expires_at)})
    return SetUserExpiryReply(ok=True, expires_at=to_iso(expires_at))


class DeleteUserReply(Reply):
    ok: bool
    removed: Revoked


@route(
    "POST /api/admin/users/{user_id}/delete", summary="Delete an account",
    bulk=True,
    tag="Admin", role=ADMIN, errors=(404,),
    description="Remove an account for good, with its sessions, login link and API keys.",
    mcp_note="Cannot be undone: admin_set_user_disabled is the reversible version. Only the owner deletes "
    "an admin; nobody deletes the owner or themselves.",
    mcp="admin_delete_user", destructive=True,
)
def delete_user(request: Request, body: UserIDPath) -> DeleteUserReply:
    """Remove an account for good, together with every session, login link,
    and API key it held. Disabling is the reversible version; this is for an
    account that should not exist at all.

    Who may delete whom lives in credentials.delete_user, checked inside its
    transaction. An admin-scoped API key may do it too, and the MCP tool is
    marked destructive so a client asks first."""
    try:
        removed = credentials.delete_user(get_store(request), body.user_id, actor_from(request).user.id)
    except credentials.SelfDeleteError:
        raise Refused(400, "you cannot delete your own account") from None
    except credentials.OwnerProtectedError:
        raise Refused(403, "the owner account cannot be deleted", code=CODE_OWNER_PROTECTED) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can delete an admin account", code=CODE_OWNER_REQUIRED) from None
    if removed is None:
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "user deleted", {"user_id": body.user_id})
    return DeleteUserReply(ok=True, removed=msgspec.convert(removed.to_dict(), Revoked))


@route(
    "POST /api/admin/users/{user_id}/reset-two-factor", summary="Turn off an account's two-factor",
    bulk=True,
    tag="Admin", role=ADMIN, feature="two_factor",
    description="For someone who lost both their phone and their recovery codes: switches their two-factor "
    "sign-in off so a login link lets them in again. Only the owner resets an admin's; the owner's is reset "
    "from a shell.",
    mcp="admin_reset_two_factor", destructive=True, enabled=two_factor_on,
)
def reset_two_factor(request: Request, body: UserIDPath) -> OkReply:
    """For someone who lost both the phone and the recovery codes. Who may
    reset whom lives in credentials.reset_two_factor."""
    try:
        found = credentials.reset_two_factor(get_store(request), body.user_id, actor_from(request).user.id)
    except credentials.SelfResetError:
        raise Refused(400, "you cannot reset your own two-factor sign-in") from None
    except credentials.OwnerProtectedError:
        raise Refused(403, "the owner's two-factor sign-in can only be reset from a shell", code=CODE_OWNER_PROTECTED) from None
    except credentials.OwnerRequiredError:
        raise Refused(403, "only the owner can reset an admin's two-factor sign-in", code=CODE_OWNER_REQUIRED) from None
    if not found:
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "two-factor reset", {"user_id": body.user_id})
    return OkReply(ok=True)


