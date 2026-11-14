"""Password sign-in (app/models/passwords.py). None of this exists while
auth.passwords is off -- RequirePasswords answers 404 -- except
/api/login/options, which is how the signed-out page finds out.

Passwords never reach these routes: password_digest is what the browser
derived from one (static/js/password.js).
"""
from __future__ import annotations

from typing import Annotated

from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request

from app.apidocs import OWNER, PUBLIC, SESSION_ONLY, Reply, route
from app.apidocs import Request as RequestType
from app.core.encryption import BadKeyError, CipherTextError
from app.core.logs import KIND_ADMIN, KIND_AUTH, LEVEL_INFO, LEVEL_WARN, anonymous
from app.core.middleware import client_ip, trusted_for
from app.core.security import actor_from, decrypt_cookie
from app.models import passwords
from app.models import two_factor
from app.models.attempts import AttemptGuard
from app.models.sessions import split_credential
from app.routes.admin import UserIDPath
from app.routes.auth import SIGN_IN, SignedIn, sign_in_response, sign_in_rules
from app.routes.helpers import Refused, get_config, get_store, run
from app.routes.logs import audit, audit_as, user_actor
from app.routes.two_factor import CODES
from app.routes.auth import SameOriginLogin

# Per name typed, not per account, so a lockout does not say which names are
# real. A wrong guess from one address across many names is what the second
# one is for: every attempt costs a bcrypt. Per process, like the rate limiter.
NAMES = AttemptGuard()
ADDRESSES = AttemptGuard(max_failures=30)


class LoginOptions(Reply, kw_only=True):
    passwords: bool
    two_factor: bool
    salt: str | UnsetType = UNSET


@route(
    "GET /api/login/options", summary="What sign-in offers",
    tag="Sign-in", access=PUBLIC, feature="passwords", no_switch=True,
)
def login_options(request: Request) -> LoginOptions:
    """What the signed-out page needs to know. Public, and the same for
    everyone: the salt is not a secret, and there is deliberately nothing here
    that depends on a username."""
    cfg = get_config(request)
    reply = LoginOptions(passwords=cfg.passwords_enabled, two_factor=cfg.two_factor_enabled)
    if cfg.passwords_enabled:
        reply.salt = passwords.install_salt(get_store(request))
    return reply


class PasswordLogin(RequestType):
    username: Annotated[str, Meta(extra={"error": "invalid_login"})]
    password_digest: Annotated[str, Meta(extra={"error": "invalid_login"})]


@route(
    "POST /api/login/password", summary="Sign in with a password",
    tag="Sign-in", access=PUBLIC, feature="passwords", use=[SameOriginLogin],
)
async def password_login(request: Request, body: PasswordLogin) -> SIGN_IN:
    """Unknown name, wrong password, a blocked or disabled account: all the
    same answer, after the same bcrypt. No CSRF token, for the same reason as
    /api/login."""
    store, cfg = get_store(request), get_config(request)
    name = passwords.normalize_username(body.username)[:64]
    address = client_ip(request.scope, cfg, trusted_for(cfg))
    # Reserved before the password is checked, so guesses sent in parallel
    # cannot all get past the lockout (see app/models/attempts.py).
    by_name = NAMES.reserve(name)
    if by_name is None:
        raise Refused(429, "login_locked")
    with by_name:
        by_address = ADDRESSES.reserve(address)
        if by_address is None:
            raise Refused(429, "login_locked")
        with by_address:
            user = await run(passwords.check_password, store, name, body.password_digest)
            signed = None if user is None else await run(passwords.start_password_sign_in, store, user, sign_in_rules(cfg))
            if signed is None:
                by_name.failed()
                by_address.failed()
                audit_as(request, anonymous(), KIND_AUTH, LEVEL_WARN, "password refused")
                raise Refused(400, "invalid_login")
            by_name.passed()
    message = "password accepted, waiting for a code" if signed.challenge else "signed in with a password"
    audit_as(request, await run(user_actor, store, user.id, "session"), KIND_AUTH, LEVEL_INFO, message)
    return await sign_in_response(request, signed, SignedIn(ok=True), 200)  # type: ignore[return-value]


def _session_id(request: Request) -> str:
    """The id of the session this request came with, to leave it alone when
    the account's others end."""
    cfg = get_config(request)
    try:
        parts = split_credential(decrypt_cookie(cfg, request.cookies.get(cfg.cookie_name, "")))
    except (CipherTextError, BadKeyError):
        return ""
    return "" if parts is None else parts[0]


def _set_password_refused(refusal: Exception) -> Refused:
    if isinstance(refusal, passwords.BadUsernameError):
        return Refused(400, "bad_username")
    if isinstance(refusal, passwords.BadDigestError):
        return Refused(400, "bad_digest")
    if isinstance(refusal, passwords.UsernameTakenError):
        return Refused(409, "username_taken")
    return Refused(403, "password_blocked")


class SetPassword(RequestType):
    username: Annotated[str, Meta(extra={"error": "bad_username"})]
    password_digest: Annotated[str, Meta(extra={"error": "bad_digest"})]
    # The page sends it whether or not two-factor is part of the app.
    code: str = ""


class SetPasswordReply(Reply):
    ok: bool
    has_password: bool


@route(
    "POST /api/account/password", summary="Set or clear your password",
    tag="Account", access=SESSION_ONLY, feature="passwords", errors=(409,),
)
def set_password(request: Request, body: SetPassword) -> SetPasswordReply:
    """Set the account's username and password, or with an empty
    password_digest remove the password. Session only: a key that could set
    one could turn itself into a session."""
    store, cfg = get_store(request), get_config(request)
    user = actor_from(request).user
    digest = body.password_digest
    # Reserved before the code is checked (see app/models/attempts.py). A
    # right code here forgives nothing, as before: only a wrong one counts.
    attempt = CODES.reserve(user.id)
    if attempt is None:
        raise Refused(429, "two_factor_locked")
    with attempt:
        try:
            found = passwords.set_password(
                store, user.id, body.username, digest, _session_id(request),
                body.code, cfg.two_factor_enabled, cfg.secret_key,
            )
        except two_factor.WrongCodeError:
            attempt.failed()
            raise Refused(403, "two_factor_wrong") from None
        except (passwords.BadUsernameError, passwords.BadDigestError, passwords.UsernameTakenError, passwords.PasswordBlockedError) as refusal:
            raise _set_password_refused(refusal) from None
    if not found:
        raise Refused.internal("set password: the signed-in account has no record")
    audit(request, KIND_AUTH, "password removed" if digest == "" else "password changed")
    return SetPasswordReply(ok=True, has_password=digest != "")


class SetPasswordAccess(UserIDPath):
    allowed: Annotated[bool, Meta(extra={"error": "allowed must be true or false"})]


class SetPasswordAccessReply(Reply):
    ok: bool
    password_blocked: bool


@route(
    "POST /api/owner/users/{user_id}/password-access", summary="Allow or block an account's password",
    tag="Owner", role=OWNER, feature="passwords",
)
def set_password_access(request: Request, body: SetPasswordAccess) -> SetPasswordAccessReply:
    """The owner's per-account switch (RequireOwner). {allowed: false} stops
    this account's password working and stops it setting one."""
    if not passwords.set_blocked(get_store(request), body.user_id, not body.allowed):
        raise Refused(404, "no such user")
    audit(request, KIND_ADMIN, "password access set", {"user_id": body.user_id, "allowed": body.allowed})
    return SetPasswordAccessReply(ok=True, password_blocked=not body.allowed)
