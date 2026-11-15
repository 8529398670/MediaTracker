"""The only place that decides who a request belongs to and whether it is
allowed to change anything. Route handlers read the answer; they never
re-derive it. One implementation means one place to get right, and one place
to look when auditing.

There are two ways to prove who you are, and they meet here rather than
anywhere downstream: a session cookie (a browser) or an API key in an
Authorization header (a script, a cron job, another service). Everything past
this module sees one Actor and one effective role, so a route does not know or
care which door the request came through.
"""
from __future__ import annotations

from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import encryption
from app.core.config import Config
from app.core.config_live import Holder
from app.core.db import Store
from app.models import utc_now
from app.models.api_keys import APIKey, load_api_key, narrow_role
from app.models.sessions import Session, load_session, touch_session
from app.models.users import ROLE_ADMIN, User, get_owner_id

# Auth method names, as reported by /api/me. Worth exposing so a client can
# tell a browser session from a key without guessing.
METHOD_SESSION = "session"
METHOD_API_KEY = "api_key"


@dataclass
class Actor:
    """Who a request belongs to, plus how they proved it.

    role is the *effective* role, not the account's: a user-scoped API key
    held by an admin authenticates as a user. Every permission check reads
    this field, so the narrowing cannot be forgotten at a call site."""

    user: User
    role: str
    session: Session | None = None
    api_key: APIKey | None = None
    # This request moved the session's end, so the response carries the cookie
    # again. See LoadActor.
    session_extended: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def via_api_key(self) -> bool:
        """Distinguishes the two doors. It decides the CSRF question below, and
        it is what an endpoint reads if it genuinely must be browser-only."""
        return self.api_key is not None

    @property
    def key_id(self) -> str:
        """The id of the API key this request came with, or "" for a browser
        session. A login link or invite link a key makes records it, so
        revoking the key voids them (see login_tokens.void_links_minted_by_key)."""
        return self.api_key.id if self.api_key is not None else ""

    @property
    def method(self) -> str:
        return METHOD_API_KEY if self.via_api_key else METHOD_SESSION


# ---------------------------------------------------------------------------
# the session cookie
# ---------------------------------------------------------------------------


def set_session_cookie(response: Response, cfg: Config, credential: str) -> None:
    """Store the session credential encrypted with the server key. The server
    already checks the credential against the database, so the encryption is
    not what makes the session unforgeable -- it means the cookie is opaque to
    anyone reading it out of a browser profile or a proxy log, and that a
    tampered cookie fails to decrypt instead of reaching the lookup."""
    _write_session_cookie(response, cfg, encryption.xchacha_encrypt_string(encryption.subkey(cfg.secret_key, encryption.PURPOSE_COOKIE), credential), cfg.session_ttl_seconds)


def _write_session_cookie(response: Response, cfg: Config, sealed: str, max_age: int) -> None:
    """The one place the cookie's attributes are spelled, so the copy sent when
    a session extends cannot drift from the one sent at sign-in."""
    response.set_cookie(
        cfg.session_cookie_name,
        sealed,
        max_age=max_age,
        path="/",
        secure=cfg.secure_cookies,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, cfg: Config) -> None:
    response.delete_cookie(cfg.session_cookie_name, path="/", secure=cfg.secure_cookies, httponly=True, samesite="strict")
    if cfg.secure_cookies:
        # A cookie from before the __Host- prefix goes too.
        response.delete_cookie(cfg.cookie_name, path="/", secure=True, httponly=True, samesite="strict")


def decrypt_cookie(cfg: Config, raw: str) -> str:
    """Turn the stored cookie back into a session credential. Exposed because
    logging out has to destroy the server-side record, not just drop the
    cookie -- otherwise a copy of the cookie taken earlier still works.
    Raises encryption.CipherTextError for anything that is not ours."""
    return encryption.xchacha_decrypt_string(encryption.subkey(cfg.secret_key, encryption.PURPOSE_COOKIE), raw)


# ---------------------------------------------------------------------------
# resolving the caller
# ---------------------------------------------------------------------------


def _resolve_session(store: Store, cfg: Config, cookies: dict[str, str]) -> Actor | None:
    raw = cookies.get(cfg.session_cookie_name, "")
    if raw == "":
        return None
    try:
        credential = decrypt_cookie(cfg, raw)
    except (encryption.CipherTextError, encryption.BadKeyError):
        return None
    loaded = load_session(store, credential)
    if loaded is None:
        return None
    session, user = loaded
    extended = touch_session(store, session, cfg.session_ttl_seconds, cfg.session_max_age_seconds)
    return Actor(user=user, role=user.role, session=session, session_extended=extended)


def _resolve_api_key(store: Store, cfg: Config, authorization: str) -> Actor | None:
    """Reads "Authorization: Bearer <id>.<secret>".

    One header and one scheme, deliberately: a second accepted spelling (an
    X-API-Key, a query parameter) is a second code path to audit, and a
    credential in a query string ends up in access logs and browser history.

    cfg.api_keys_enabled is checked here rather than only on the routes that
    mint keys, so turning the feature off actually closes the door: the header
    stops being believed at all, and existing keys stop authenticating."""
    if not cfg.api_keys_enabled:
        return None
    # The scheme and the key, split on any whitespace, and nothing else.
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    loaded = load_api_key(store, parts[1])
    if loaded is None:
        return None
    key, user = loaded
    # The ceiling, applied per request. See narrow_role: the stored role is
    # what was asked for, this is what is granted.
    return Actor(user=user, role=narrow_role(user.role, key.role), api_key=key)


def _has_bearer(authorization: str) -> bool:
    """True when the request carries any Authorization header. Any at all is
    an attempt at a key, and one that does not hold a good key is nobody
    (_resolve_api_key): it never falls back to the cookie. Splitting only on a
    space let "Bearer<TAB>key" fall back and run as the signed-in account
    (S16)."""
    return authorization.strip() != ""


def resolve_actor(store: Store, cfg: Config, cookies: dict[str, str], authorization: str) -> Actor | None:
    """An Authorization: Bearer header decides it: the request is that key or
    no one, and the cookie is not read. Otherwise the cookie. A script using
    a narrow key must not quietly run as the full account whose cookie
    happens to be in the jar, and a bad key is no one, not the cookie.

    The CSRF rule below stays sound: a header is never ambient -- a page on
    another site cannot add one without a CORS preflight this server does not
    answer -- and a request that skips the token check by carrying a key
    needed that key to begin with."""
    if _has_bearer(authorization):
        return _resolve_api_key(store, cfg, authorization)
    return _resolve_session(store, cfg, cookies)


class LoadActor:
    """Runs on every request. It resolves the caller once and stashes the
    result on request.state, so a handler and a guard asking "who is this" do
    not cost two database reads. It never rejects anything -- that is the
    guards' job -- because plenty of routes are fine for anonymous visitors.

    The lookup touches SQLite, so it runs in a worker thread rather than on
    the event loop.

    It reads the running configuration per request: whether API keys are
    believed at all (auth.api_keys) can change while the server runs."""

    def __init__(self, app: ASGIApp, store: Store, settings: Holder) -> None:
        self.app = app
        self.store = store
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope)
            actor = await run_in_threadpool(
                resolve_actor, self.store, self.settings.get(), dict(request.cookies), request.headers.get("authorization", "")
            )
            request.state.actor = actor
            if actor is not None and actor.session_extended:
                send = self._sending_cookie(send, request.cookies[self.settings.get().session_cookie_name], actor.session)
        await self.app(scope, receive, send)

    def _sending_cookie(self, send: Send, sealed: str, session: Session) -> Send:
        """The browser drops the cookie at its own expiry, so extending only
        the record would still sign this person out when that arrived. Unless
        the route set the cookie itself: logging out or switching account on
        the request that extended has to win, and two headers for one cookie
        would leave the answer to their order."""
        cfg = self.settings.get()
        carrier = Response()
        _write_session_cookie(carrier, cfg, sealed, int((session.expires_at - utc_now()).total_seconds()))
        header = next(item for item in carrier.raw_headers if item[0] == b"set-cookie")
        name = cfg.session_cookie_name.encode("latin-1") + b"="

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(key.lower() == b"set-cookie" and value.startswith(name) for key, value in headers):
                    headers.append(header)
                message["headers"] = headers
            await send(message)

        return send_with_cookie


def actor_from(request: Request) -> Actor | None:
    return getattr(request.state, "actor", None)


# ---------------------------------------------------------------------------
# guards
#
# RequireLogin, RequireAdmin, RequireSession and RequireAPIKey are middleware
# attached to routes where they are registered (app/routes/__init__.py), rather than
# helpers called at the top of each handler, so a new protected route is
# protected by where it is registered -- forgetting the check is not something
# you can do silently.
# ---------------------------------------------------------------------------


def _refuse(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class Guard:
    """Base for the guards: subclasses return a refusal, or None to let the
    request through."""

    # The error statuses it can answer with, for the API docs.
    statuses: tuple[int, ...] = ()

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def refuse(self, request: Request) -> Response | None:  # pragma: no cover - overridden
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        refusal = self.refuse(Request(scope))
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RequireLogin(Guard):
    statuses = (401,)

    def refuse(self, request: Request) -> Response | None:
        if actor_from(request) is None:
            return _refuse(401, "not authenticated")
        return None


class RequireAdmin(Guard):
    statuses = (401, 403)

    def refuse(self, request: Request) -> Response | None:
        actor = actor_from(request)
        if actor is None:
            return _refuse(401, "not authenticated")
        if not actor.is_admin:
            return _refuse(403, "forbidden")
        return None


class RequireSession(Guard):
    """Refuses a request that authenticated with an API key, even a correctly
    scoped one. It guards what a key must not reach (see
    app/routes/__init__.py): minting, renaming and revoking API keys, your own
    password, PIN and two-factor, other people's files, and the owner's
    screens.

    Accounts and ways in are not on that list. An admin key may create and
    delete accounts, change roles and hand out login links and invite links.
    A key makes its own account a login link only once that account switched
    it on from a session (APIKey.may_sign_in), and then one that works once,
    for at most 15 minutes. What keeps revoking a leaked key meaningful is
    that every link records the key that made it, and revoking or deleting
    the key voids those still usable and ends every session one of its login
    links signed in (login_tokens.void_links_minted_by_key). Disabling or
    demoting the key's account does the same for all its keys. What it does
    not undo is anything such a session did meanwhile, or the accounts made
    through an invite link it handed out: those show in the activity log and
    the user list.

    Keys themselves stay browser-only: a key that could mint a key would leave
    a successor behind with nothing to tie it to the one revoked."""

    statuses = (401, 403)

    def refuse(self, request: Request) -> Response | None:
        actor = actor_from(request)
        if actor is None:
            return _refuse(401, "not authenticated")
        if actor.via_api_key:
            return _refuse(403, "this endpoint requires a signed-in session, not an API key")
        return None


class RequireAPIKey(Guard):
    """RequireSession's mirror: refuses a browser session and lets only a key
    through. It guards /mcp, which is for agents and scripts. Taking only a
    header credential there means no ambient cookie can ride along on a
    request some other page caused, so the endpoint needs no CSRF token and
    the no-credentials rule for keys covers everything it can do."""

    statuses = (401, 403)

    def refuse(self, request: Request) -> Response | None:
        actor = actor_from(request)
        if actor is None:
            response = _refuse(401, "not authenticated")
            response.headers["WWW-Authenticate"] = "Bearer"
            return response
        if not actor.via_api_key:
            return _refuse(403, "this endpoint requires an API key, not a signed-in session")
        return None


class RequireOwner(Guard):
    """Lets through only the owner, signed in from a browser. It guards the
    activity log (app/routes/logs.py), which shows what every account did --
    including the other admins, which is exactly why they cannot read it.
    Everyone else, any API key included, gets the 404 an unknown route gets:
    the Logs screen is not something to advertise.

    A session, not a key: the log holds every account's IP addresses and
    activity, and a key is a credential that lives in files. An app that
    wants the log readable by a script should add a narrow export,
    knowingly.

    Finding the owner reads SQLite, so unlike the guards above this one runs
    its check in a worker thread."""

    statuses = (404,)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope)
        actor = actor_from(request)
        allowed = actor is not None and not actor.via_api_key and actor.is_admin
        if allowed:
            owner_id = await run_in_threadpool(get_owner_id, request.app.state.store)
            allowed = owner_id is not None and owner_id == actor.user.id
        if not allowed:
            await _refuse(404, "not_found")(scope, receive, send)
            return
        await self.app(scope, receive, send)


def still_owner(store: Store, credential: str) -> bool:
    """Whether a session is still the owner's, for something that outlives the
    request that was let in: an open stream, which RequireOwner checked once.
    Straight to load_session, not through resolve_actor: it must not touch
    last_seen_at, since a stream staying open is not the person being there,
    and an API key has no business answering for a session that ended."""
    loaded = load_session(store, credential)
    if loaded is None:
        return False
    _, user = loaded
    return user.role == ROLE_ADMIN and get_owner_id(store) == user.id


def log_actor(actor: Actor | None) -> dict:
    """Who an activity-log entry belongs to: the account, the role it acted
    with, and which door it came through (a key by its public id only)."""
    if actor is None:
        return {"method": "anon"}
    result = {"user_id": actor.user.id, "name": actor.user.display_name, "role": actor.role, "method": actor.method}
    if actor.api_key is not None:
        result["key_id"] = actor.api_key.id
    return result


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def check_csrf(request: Request, submitted: object) -> bool:
    """Guards state-changing requests. SameSite=Strict already blocks the
    common cross-site POST, but it is a browser-side promise: older browsers,
    odd cross-scheme cases, and non-browser clients do not all honour it. A
    per-session token echoed back in the JSON body costs nothing and does not
    depend on the browser behaving.

    A request authenticated by an API key is exempt, and that is not a hole.
    CSRF exists because a cookie is *ambient* -- the browser attaches it to a
    request some other site caused. Nothing attaches an Authorization header
    on its own; a forged cross-site request from an attacker's page carries no
    key, so there is nothing to forge with. Requiring a token here would
    instead mean every script had to fetch one first, for no gain."""
    actor = actor_from(request)
    if actor is None:
        return False
    if actor.via_api_key:
        return True
    if actor.session is None or not isinstance(submitted, str) or submitted == "":
        return False
    return encryption.constant_time_equal(actor.session.csrf_token, submitted)
