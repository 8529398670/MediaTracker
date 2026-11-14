"""Self-service endpoints for any signed-in caller: who am I, rename myself,
a login link for another device, log out. The account screen itself is static/js/app.js, calling these."""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request

from app.apidocs import SESSION_ONLY, Reply, route
from app.apidocs import Request as RequestType
from app.apidocs.route import reply_response
from app.core.config import Config
from app.core.config import repo_file
from app.core.encryption import BadKeyError, CipherTextError
from app.core.logs import KIND_AUTH
from app.core.security import actor_from, clear_session_cookie, decrypt_cookie
from app.models import login_tokens, sessions, users
from app.models import passwords
from app.models import pins
from app.models import themes
from app.models import two_factor
from app.routes.admin import CancelLoginLinkReply, DisplayName, ExpiresInMinutes, LoginLink, LoginLinkReply, MaxUses, OkReply, RenameUserReply, link_options, link_reply
from app.routes.helpers import Refused, get_config, get_store, run
from app.routes.logs import audit
from app.routes.themes import Theme, theme_list
from app.routes.mcp_tools_accounts import with_login_url


class Me(Reply, kw_only=True):
    """Who is asking, and what the page needs to know before it draws."""

    api_name: ClassVar[str] = "Me"
    authenticated: bool
    id: int
    display_name: str
    role: Annotated[str, Meta(description="The effective role: never higher than an API key's own.")]
    account_role: str
    is_owner: bool
    login_link: Annotated[LoginLink | None, Meta(description="Your own live login link, or null.")]
    maintenance: Literal["none", "read_only", "full"]
    version: Annotated[str, Meta(description="The running build. dev when none was stamped.")]
    announcement: Annotated[str, Meta(description="server.announcement. Empty when there is none.")]
    repo: Annotated[str, Meta(description="app.repo without a trailing / or .git: where the source lives. Empty when it is not set.")]
    description: Annotated[str, Meta(description="app.description. Empty when there is none.")]
    show_about: Annotated[bool, Meta(description="app.show_about: whether the menu has About.")]
    openapi_url: Annotated[str, Meta(description="Where to read this API's reference: config/openapi.json in app.repo, or /api/openapi.json when there is no repo.")]
    mcp_url: Annotated[str, Meta(description="Where to read the MCP reference: config/mcp.json in app.repo, or /api/mcp.json when there is no repo. Only with server.mcp on.")]
    themes: Annotated[list[Theme] | None, Meta(description="Your themes (see the Theme schema): your own list, else the app's defaults, else null for the built-in ones.")]
    themes_custom: Annotated[bool, Meta(description="Whether you have your own list rather than following the defaults.")]
    theme_id: Annotated[str, Meta(description="The theme you use. Empty: the first.")]
    has_pin: bool
    username: str
    has_password: bool
    password_blocked: bool
    two_factor: bool
    passwords_enabled: bool
    two_factor_enabled: bool
    auth: str
    api_keys_enabled: bool
    mcp_enabled: Annotated[bool, Meta(description="server.mcp: whether POST /mcp answers.")]
    invite_links_enabled: Annotated[bool, Meta(description="Whether invite links are on.")]
    logs_enabled: bool
    logs_ui_clicks: bool
    can_show_others: Annotated[bool, Meta(description="Whether this caller may use the Showing picker. A user-scoped key of an admin reports what it may actually do, like role.")]
    default_subject: Annotated[int | None, Meta(description="Whose lists the Showing picker starts on: a user id, or null for your own.")]
    showing_locked: Annotated[bool, Meta(description="Whether an admin has locked the Showing picker.")]
    csrf_token: Annotated[str, Meta(description="Browser sessions only.")] | UnsetType = UNSET
    api_key_id: Annotated[str, Meta(description="API keys only.")] | UnsetType = UNSET
    api_key_name: Annotated[str, Meta(description="API keys only.")] | UnsetType = UNSET


@route(
    "GET /api/me", summary="Who am I",
    tag="Account",
    description="The account this API key belongs to, the role it acts with (role -- never higher than the "
    "key's own scope), and the account's own role.",
    mcp="whoami", read_only=True,
)
def me(request: Request) -> Me:
    """The frontend's first call on every page load: it answers "who am I,
    what may I do, and what CSRF token do I echo back". Handing the token out
    here means no page needs a hidden form field or a template variable. The
    MCP whoami tool answers the same, so the two cannot describe the same
    caller differently.

    "role" is the *effective* role, not the account's: a request made with a
    user-scoped API key belonging to an admin reports "user", because that is
    what it may actually do. account_role reports the account itself, for the
    rare caller that needs to tell the two apart. Reporting the account's role
    as "role" would have a client believe it has permissions the server will
    refuse to act on."""
    store, cfg, actor = get_store(request), get_config(request), actor_from(request)
    # is_owner tells the UI which account-management buttons to offer; the
    # server checks ownership again on every request that depends on it.
    owner_id = users.get_owner_id(store)
    my_themes, themes_custom = themes.mine(store, actor.user.themes)
    link = login_tokens.live_login_link(store, actor.user.id)
    reply = Me(
        authenticated=True,
        id=actor.user.id,
        display_name=actor.user.display_name,
        role=actor.role,
        account_role=actor.user.role,
        is_owner=actor.user.id == owner_id,
        login_link=LoginLink(**link) if link is not None else None,
        maintenance=cfg.maintenance,
        version=request.app.state.version,
        announcement=cfg.announcement,
        repo=cfg.repo,
        description=cfg.description,
        show_about=cfg.show_about,
        openapi_url=open_api_url(cfg),
        mcp_url=mcp_url(cfg),
        themes=theme_list(my_themes),
        themes_custom=themes_custom,
        theme_id=actor.user.theme_id,
        has_pin=pins.has_pin(actor.user),
        username=actor.user.username,
        has_password=passwords.has_password(actor.user),
        password_blocked=actor.user.password_blocked,
        two_factor=two_factor.is_on(actor.user),
        passwords_enabled=cfg.passwords_enabled,
        two_factor_enabled=cfg.two_factor_enabled,
        auth=actor.method,
        api_keys_enabled=cfg.api_keys_enabled,
        mcp_enabled=cfg.mcp_enabled,
        invite_links_enabled=cfg.invite_links_enabled,
        # Whether track.js sends anything, and whether it sends clicks.
        logs_enabled=cfg.logs.enabled,
        logs_ui_clicks=cfg.logs.enabled and cfg.logs.ui_clicks,
        # The Showing picker: whether this caller may use it, and whose lists
        # it starts on (None for their own).
        can_show_others=actor.is_admin or actor.user.can_show_others,
        default_subject=actor.user.default_subject,
        # An admin's lock on that choice: the picker cannot be changed.
        showing_locked=users.locked_subject(actor.user) is not None,
    )
    # Only a session has a CSRF token. A key-authenticated request has no
    # ambient credential to protect, so there is nothing to hand back -- see
    # check_csrf.
    if actor.session is not None:
        reply.csrf_token = actor.session.csrf_token
    if actor.api_key is not None:
        reply.api_key_id = actor.api_key.id
        reply.api_key_name = actor.api_key.name
    return reply


def open_api_url(cfg: Config) -> str:
    """Where the API reference is read: config/openapi.json in app.repo when
    that is set, so it opens as a page there, else this server's own copy,
    which needs the same sign-in."""
    return repo_file(cfg, "config/openapi.json") or "/api/openapi.json"


def mcp_url(cfg: Config) -> str:
    """Where the MCP reference is read: config/mcp.json in app.repo when that
    is set, else this server's own copy, which needs the same sign-in."""
    return repo_file(cfg, "config/mcp.json") or "/api/mcp.json"


class Rename(RequestType):
    display_name: DisplayName
    expect: str | None = None


@route(
    "POST /api/account/rename", summary="Rename your account",
    tag="Account", errors=(409,),
    description="Change your own display name (1-80 characters). expect, when given, is the name you think "
    "it has now; if someone changed it meanwhile the rename is refused with the current name, so nothing is "
    "overwritten unseen.",
    mcp="rename_account",
)
def rename(request: Request, body: Rename) -> RenameUserReply:
    """Rename yourself, over HTTP or the MCP rename_account tool. expect is
    the name the caller expects to replace: the frontend always sends it, so
    its undo cannot overwrite a rename made elsewhere."""
    if not users.valid_display_name(body.display_name):
        raise Refused(400, "display name must be 1-80 characters")
    try:
        renamed = users.rename_user(get_store(request), actor_from(request).user.id, body.display_name, body.expect)
    except users.RenameConflictError as refusal:
        raise Refused(409, str(refusal), display_name=refusal.current) from None
    if not renamed:
        raise Refused.internal("rename: the signed-in account has no record")
    name = body.display_name.strip()
    audit(request, KIND_AUTH, "renamed own account", {"name": name})
    return RenameUserReply(ok=True, display_name=name)


class SetPIN(RequestType):
    pin: Annotated[str, Meta(extra={"error": "bad_pin"})]


class SetPINReply(Reply):
    ok: bool
    has_pin: bool


@route(
    "POST /api/account/pin", summary="Set or clear your PIN",
    tag="Account", access=SESSION_ONLY, feature="invite_links",
)
def set_pin(request: Request, body: SetPIN) -> SetPINReply:
    """Set, or with an empty pin clear, the PIN asked for when this account
    signs back in through an invite link (see app/models/pins.py)."""
    try:
        if not pins.set_user_pin(get_store(request), actor_from(request).user.id, body.pin):
            raise Refused.internal("set pin: the signed-in account has no record")
    except pins.BadPinError:
        raise Refused(400, "bad_pin") from None
    audit(request, KIND_AUTH, "pin changed", {"has_pin": body.pin != ""})
    return SetPINReply(ok=True, has_pin=body.pin != "")


class MyLoginLink(RequestType):
    max_uses: MaxUses | None = None
    expires_in_minutes: ExpiresInMinutes | None = None


@route(
    "POST /api/account/login-link", summary="A login link for yourself",
    tag="Account",
    description="A link that signs your own account in on a browser or another device. Only a key with your "
    "account's full role may ask: one scoped down to user on an admin account is refused.",
    mcp_note="Answers with login_url (open it to sign in; it works once unless max_uses says otherwise), "
    "expires_at and max_uses. Any older link the account could still use stops working; its signed-in "
    "devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs "
    "out every device it signed in.",
    mcp="create_my_login_link", call=with_login_url,
)
def create_my_login_link(request: Request, body: MyLoginLink) -> LoginLinkReply:
    """Mint a login link for the caller's own account: the way to sign in on
    another device without asking an admin. Once by default, or reusable,
    like admin.reissue_login -- it is reissue_login pointed at yourself, so it
    has the same effect: any link the account could still use stops working,
    and existing sessions stay signed in.

    An API key may ask too, but only one that carries the account's full
    role: the link becomes a session, and a session acts with the account's
    role, so a key scoped down to "user" on an admin's account would otherwise
    climb. Revoking the key voids the link while it can still be used."""
    actor = actor_from(request)
    if actor.via_api_key and actor.role != actor.user.role:
        raise Refused(403, "this key acts with less than your account's role, so it cannot make a login link")
    options = link_options(request, body)
    credential, info = login_tokens.issue_login_link(get_store(request), actor.user.id, options)
    audit(request, KIND_AUTH, "own login link created", {"max_uses": info["max_uses"], "expires_at": info["expires_at"]})
    return LoginLinkReply(**link_reply(credential, info))


@route(
    "POST /api/account/login-link/cancel", summary="Stop your own login link working",
    tag="Account",
    description="Void your account's live login link without making a new one. Devices it already signed in "
    "stay signed in. Answers with removed: 0 or 1.",
    mcp="cancel_my_login_link", destructive=True,
)
def cancel_my_login_link(request: Request) -> CancelLoginLinkReply:
    """Stop the caller's own live login link working."""
    removed = login_tokens.cancel_login_link(get_store(request), actor_from(request).user.id)
    audit(request, KIND_AUTH, "own login link cancelled", {"removed": removed})
    return CancelLoginLinkReply(ok=True, removed=removed)


@route(
    "POST /api/logout", summary="Sign out",
    tag="Account",
    mcp_http="Ends a browser session; a key has none to end.",
)
async def logout(request: Request) -> OkReply:
    """Deletes the session server-side as well as clearing the cookie, so a
    copy of the cookie captured earlier is dead too.

    It is held to the CSRF token like every other state change. SameSite=
    Strict already stops another site from sending the cookie here, but not a
    page on a sibling subdomain, and being signed out by someone else's page
    is the first step of tricking a person into signing in to the wrong
    account.

    Called with an API key it does nothing and says so by succeeding: there is
    no session to destroy. A key is ended by revoking it, not by logging out."""
    audit(request, KIND_AUTH, "signed out")
    await destroy_cookie_session(request)
    response = reply_response(OkReply(ok=True))
    clear_session_cookie(response, get_config(request))
    return response  # type: ignore[return-value]


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
