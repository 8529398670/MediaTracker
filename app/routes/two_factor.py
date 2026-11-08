"""Two-factor sign-in, from a person's point of view: finishing a sign-in with
a code, and turning it on and off on their account (app/models/two_factor.py,
app/models/sign_in.py).

Setting it up needs a browser session, like every route that touches how an
account signs in: a key that could change this could lock its owner out, or
remove what protects them.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logs import KIND_AUTH, LEVEL_INFO, LEVEL_WARN
from app.core.security import actor_from, check_csrf
from app.models import sign_in, two_factor
from app.models.attempts import AttemptGuard
from app.routes.auth import same_origin_json, sign_in_response
from app.routes.helpers import bad_request, conflict, error, forbidden, get_config, get_store, read_json, run, server_error
from app.routes.logs import audit, audit_as, user_actor

# Wrong codes per account, wherever they are typed. Six digits with a window
# of three steps would otherwise fall to a patient guesser. Per process, like
# the rate limiter.
CODES = AttemptGuard()


async def finish_sign_in(request: Request) -> Response:
    """The second half of a sign-in. No CSRF token, for the same reason as
    /api/login: there is no session yet to hold one, and the JSON body rule
    guards it the same way."""
    if not same_origin_json(request):
        return forbidden("login must be submitted from this site's own login page")
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    store, cfg = get_store(request), get_config(request)
    credential = body.get("challenge")
    user_id = await run(sign_in.challenge_user_id, store, credential)
    if user_id is None:
        return bad_request("challenge_invalid")
    if CODES.locked(user_id):
        return error(429, "two_factor_locked")

    try:
        signed, method = await run(
            sign_in.finish_challenge, store, credential, body.get("code"), cfg.session_ttl_seconds, cfg.secret_key
        )
    except sign_in.ChallengeInvalidError:
        return bad_request("challenge_invalid")
    except two_factor.WrongCodeError:
        CODES.record(user_id, False)
        audit_as(request, await run(user_actor, store, user_id, "anon"), KIND_AUTH, LEVEL_WARN, "wrong two-factor code")
        return forbidden("two_factor_wrong")
    CODES.record(user_id, True)
    message = "signed in with a recovery code" if method == "recovery" else "signed in with a two-factor code"
    audit_as(request, await run(user_actor, store, user_id, "session"), KIND_AUTH, LEVEL_INFO, message)
    return await sign_in_response(request, signed, {"ok": True}, 200)


async def start_setup(request: Request) -> Response:
    """A new secret for the person's authenticator app. The page builds the
    QR code from it, so nothing about it is stored as anything but cipher text
    and it is shown only here."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    try:
        secret = await run(two_factor.start_setup, get_store(request), actor_from(request).user.id, get_config(request).secret_key)
    except two_factor.AlreadyOnError:
        return conflict("two_factor_on")
    if secret is None:
        return server_error(request, "two-factor setup: the signed-in account has no record")
    return JSONResponse({"secret": secret})


async def confirm_setup(request: Request) -> Response:
    """The code that proves the app has the secret. Answers with the recovery
    codes, which are never shown again."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = actor_from(request).user.id
    if CODES.locked(user_id):
        return error(429, "two_factor_locked")
    try:
        codes = await run(two_factor.confirm_setup, get_store(request), user_id, body.get("code"), get_config(request).secret_key)
    except two_factor.AlreadyOnError:
        return conflict("two_factor_on")
    except two_factor.WrongCodeError:
        CODES.record(user_id, False)
        return forbidden("two_factor_wrong")
    if codes is None:
        return server_error(request, "two-factor confirm: the signed-in account has no record")
    CODES.record(user_id, True)
    audit(request, KIND_AUTH, "two-factor sign-in turned on")
    return JSONResponse({"recovery_codes": codes})


async def disable(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    user_id = actor_from(request).user.id
    if CODES.locked(user_id):
        return error(429, "two_factor_locked")
    try:
        found = await run(two_factor.disable, get_store(request), user_id, body.get("code"), get_config(request).secret_key)
    except two_factor.NotOnError:
        return conflict("two_factor_off")
    except two_factor.WrongCodeError:
        CODES.record(user_id, False)
        return forbidden("two_factor_wrong")
    if not found:
        return server_error(request, "two-factor disable: the signed-in account has no record")
    CODES.record(user_id, True)
    audit(request, KIND_AUTH, "two-factor sign-in turned off")
    return JSONResponse({"ok": True})
