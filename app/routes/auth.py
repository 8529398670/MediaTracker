"""Signing in with a login link. Redeeming a valid link is the login; there
is nothing to phish out of a user beyond the link itself, which dies on first
use. An account with two-factor on goes on to give a code (see two_factor.py).

It takes two steps. GET /login/<credential> only serves the app's page
(StaticServer.serve_login_page), which asks the person to confirm; the page
then POSTs the credential here. Link previews in chat apps, mail scanners, and
browser prefetch all fetch a URL without anyone asking them to -- if the GET
were the login, they would spend the link before its owner ever clicked it.
And someone already signed in is told that continuing switches accounts,
rather than being silently signed in as whoever the link belongs to.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.core.logs import KIND_AUTH, LEVEL_INFO, LEVEL_WARN, anonymous
from app.core.middleware import client_ip, trusted_for
from app.core.security import set_session_cookie
from app.models import login_tokens
from app.models import sessions
from app.models.sign_in import SignIn, SignInRules
from app.routes.account import destroy_cookie_session
from app.routes.helpers import bad_request, forbidden, get_config, get_store, read_json, run
from app.routes.logs import audit_as, user_actor


def same_origin_json(request: Request) -> bool:
    """True for a request with a JSON content type that, if it came from a
    browser, came from one of this site's own pages."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return False
    return request.headers.get("sec-fetch-site", "same-origin") == "same-origin"


def sign_in_rules(cfg: Config) -> SignInRules:
    return SignInRules(session_ttl_seconds=cfg.session_ttl_seconds, two_factor=cfg.two_factor_enabled)


async def sign_in_response(request: Request, signed: SignIn, payload: dict[str, Any], status: int) -> Response:
    """How every way of signing in ends. A challenge goes back to the page,
    which asks for the code, and nothing changes in this browser yet.
    Otherwise this browser switches to the new session: the one it had is
    ended server-side, not merely replaced in the cookie jar."""
    if signed.challenge:
        return JSONResponse({"two_factor": True, "challenge": signed.challenge})
    await destroy_cookie_session(request)
    response = JSONResponse(payload, status_code=status)
    set_session_cookie(response, get_config(request), signed.session_credential)
    await _remember_client(request, signed.session_credential)
    return response


async def _remember_client(request: Request, credential: str) -> None:
    """Best effort: the person is signed in by now, and a sign-in is not worth
    failing over what the Account screen will show about it."""
    cfg = get_config(request)
    parts = sessions.split_credential(credential)
    if parts is None:
        return
    ip = client_ip(request.scope, cfg, trusted_for(cfg))
    try:
        await run(sessions.remember_client, get_store(request), parts[0], ip, request.headers.get("user-agent", ""))
    except Exception as error:  # noqa: BLE001 -- see above
        print(f"[sessions] could not note where a sign-in came from: {error}", flush=True)


async def redeem_login_link(request: Request) -> Response:
    """The one state-changing route with no CSRF token -- there is no session
    yet to hold one -- so it is guarded differently. A forged login signs a
    victim's browser in to the *attacker's* account, after which anything the
    victim does lands where the attacker can read it. Requiring a JSON body is
    what blocks that: an HTML form cannot send one, and a cross-origin fetch
    that tries needs a CORS preflight this server never approves.
    Sec-Fetch-Site, which every current browser sends, refuses the rest
    outright."""
    if not same_origin_json(request):
        return forbidden("login must be submitted from this site's own login page")
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    credential = body.get("credential")
    credential = credential.strip().strip("/") if isinstance(credential, str) else ""

    store, cfg = get_store(request), get_config(request)
    # Expired, already spent, never existed, wrong secret, or a disabled
    # account all get the same answer. Telling them apart would let someone
    # probe which links are real.
    signed = await run(login_tokens.redeem_login_token, store, credential, sign_in_rules(cfg)) if credential else None
    if signed is None:
        audit_as(request, anonymous(), KIND_AUTH, LEVEL_WARN, "login link refused")
        return bad_request("invalid login link")
    message = "login link accepted, waiting for a code" if signed.challenge else "signed in with a login link"
    audit_as(request, await run(user_actor, store, signed.user_id, "session"), KIND_AUTH, LEVEL_INFO, message)
    return await sign_in_response(request, signed, {"ok": True}, 200)
