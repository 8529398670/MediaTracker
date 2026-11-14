"""Two-factor sign-in, from a person's point of view: finishing a sign-in with
a code, and turning it on and off on their account (app/models/two_factor.py,
app/models/sign_in.py).

Setting it up needs a browser session, like every route that touches how an
account signs in: a key that could change this could lock its owner out, or
remove what protects them.
"""
from __future__ import annotations

from typing import Annotated

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import PUBLIC, SESSION_ONLY, Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_AUTH, LEVEL_INFO, LEVEL_WARN
from app.core.security import actor_from
from app.models import sign_in, two_factor
from app.models.attempts import AttemptGuard
from app.routes.admin import OkReply
from app.routes.auth import SignedIn, sign_in_response
from app.routes.helpers import Refused, get_config, get_store, run
from app.routes.logs import audit, audit_as, user_actor
from app.routes.auth import SameOriginLogin

# Wrong codes per account, wherever they are typed. Six digits with a window
# of three steps would otherwise fall to a patient guesser. Per process, like
# the rate limiter.
CODES = AttemptGuard()


class FinishSignIn(RequestType):
    challenge: Annotated[str, Meta(extra={"error": "challenge_invalid"})]
    code: str


@route(
    "POST /api/login/two-factor", summary="Finish a sign-in with a code",
    tag="Sign-in", access=PUBLIC, feature="two_factor", no_switch=True, use=[SameOriginLogin],
)
async def finish_sign_in(request: Request, body: FinishSignIn) -> SignedIn:
    """The second half of a sign-in. No CSRF token, for the same reason as
    /api/login: there is no session yet to hold one, and the JSON body rule
    guards it the same way."""
    store, cfg = get_store(request), get_config(request)
    user_id = await run(sign_in.challenge_user_id, store, body.challenge)
    if user_id is None:
        raise Refused(400, "challenge_invalid")
    # Reserved before the code is checked, so guesses sent in parallel cannot
    # all get past the lockout (see app/models/attempts.py).
    attempt = CODES.reserve(user_id)
    if attempt is None:
        raise Refused(429, "two_factor_locked")

    with attempt:
        try:
            signed, method = await run(sign_in.finish_challenge, store, body.challenge, body.code, cfg.session_ttl_seconds, cfg.secret_key)
        except sign_in.ChallengeInvalidError:
            raise Refused(400, "challenge_invalid") from None
        except two_factor.WrongCodeError:
            attempt.failed()
            audit_as(request, await run(user_actor, store, user_id, "anon"), KIND_AUTH, LEVEL_WARN, "wrong two-factor code")
            raise Refused(403, "two_factor_wrong") from None
        attempt.passed()
    message = "signed in with a recovery code" if method == "recovery" else "signed in with a two-factor code"
    audit_as(request, await run(user_actor, store, user_id, "session"), KIND_AUTH, LEVEL_INFO, message)
    return await sign_in_response(request, signed, SignedIn(ok=True), 200)  # type: ignore[return-value]


class StartSetupReply(Reply):
    secret: str


@route(
    "POST /api/account/two-factor/start", summary="Begin two-factor setup",
    tag="Account", access=SESSION_ONLY, feature="two_factor", errors=(409,),
)
def start_setup(request: Request) -> StartSetupReply:
    """A new secret for the person's authenticator app. The page builds the
    QR code from it, so nothing about it is stored as anything but cipher text
    and it is shown only here."""
    try:
        secret = two_factor.start_setup(get_store(request), actor_from(request).user.id, get_config(request).secret_key)
    except two_factor.AlreadyOnError:
        raise Refused(409, "two_factor_on") from None
    if secret is None:
        raise Refused.internal("two-factor setup: the signed-in account has no record")
    return StartSetupReply(secret=secret)


class Code(RequestType):
    code: str


class ConfirmSetupReply(Reply):
    recovery_codes: list[str]


@route(
    "POST /api/account/two-factor/confirm", summary="Turn two-factor on",
    tag="Account", access=SESSION_ONLY, feature="two_factor", errors=(409,),
)
def confirm_setup(request: Request, body: Code) -> ConfirmSetupReply:
    """The code that proves the app has the secret. Answers with the recovery
    codes, which are never shown again."""
    user_id = actor_from(request).user.id
    attempt = CODES.reserve(user_id)
    if attempt is None:
        raise Refused(429, "two_factor_locked")
    with attempt:
        try:
            codes = two_factor.confirm_setup(get_store(request), user_id, body.code, get_config(request).secret_key)
        except two_factor.AlreadyOnError:
            raise Refused(409, "two_factor_on") from None
        except two_factor.WrongCodeError:
            attempt.failed()
            raise Refused(403, "two_factor_wrong") from None
        if codes is None:
            raise Refused.internal("two-factor confirm: the signed-in account has no record")
        attempt.passed()
    audit(request, KIND_AUTH, "two-factor sign-in turned on")
    return ConfirmSetupReply(recovery_codes=codes)


@route(
    "POST /api/account/two-factor/disable", summary="Turn two-factor off",
    tag="Account", access=SESSION_ONLY, feature="two_factor", errors=(409,),
)
def disable(request: Request, body: Code) -> OkReply:
    user_id = actor_from(request).user.id
    attempt = CODES.reserve(user_id)
    if attempt is None:
        raise Refused(429, "two_factor_locked")
    with attempt:
        try:
            found = two_factor.disable(get_store(request), user_id, body.code, get_config(request).secret_key)
        except two_factor.NotOnError:
            raise Refused(409, "two_factor_off") from None
        except two_factor.WrongCodeError:
            attempt.failed()
            raise Refused(403, "two_factor_wrong") from None
        if not found:
            raise Refused.internal("two-factor disable: the signed-in account has no record")
        attempt.passed()
    audit(request, KIND_AUTH, "two-factor sign-in turned off")
    return OkReply(ok=True)
