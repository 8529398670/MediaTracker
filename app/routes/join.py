"""Joining through an invite link (see app/models/invite_links.py; managing
links is app/routes/invite_links.py).

Everything here is public -- holding the link is the permission -- so every
POST is held to the same rule as /api/login: a JSON body from one of this
site's own pages (same_origin_json). The credential travels in the body,
never a query string, and the page that carries it in its path is served with
no-referrer (StaticServer.serve_login_page, which both link pages share).

A bad, expired, switched-off, or orphaned link always answers 404
invite_link_invalid, whichever of those it was.
"""
from __future__ import annotations

from starlette.requests import Request

from app.apidocs import PUBLIC, Reply, one_of, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_AUTH, LEVEL_INFO, LEVEL_WARN
from app.models import invite_links, pins, users
from app.models import passwords
from app.models.attempts import AttemptGuard
from app.models.invite_links import InviteLink, InviteLinkFullError, InviteLinkInvalidError, NotInviteAccountError
from app.models.sign_in import SignIn
from app.routes.auth import TwoFactorChallenge, sign_in_response, sign_in_rules
from app.routes.helpers import Refused, get_config, get_store, run
from app.routes.logs import audit_as, user_actor
from app.routes.auth import SameOriginJoin

# Per process, like the rate limiter. See AttemptGuard.
PINS = AttemptGuard()


class Join(RequestType):
    """What every join route takes; each reads the fields its step needs."""

    credential: str
    display_name: str = ""
    user_id: int = 0
    pin: str = ""


class JoinedReply(Reply):
    ok: bool
    display_name: str


# What joining or claiming an account answers.
JOINED = one_of("Joined", JoinedReply, TwoFactorChallenge, doc="Either the sign-in finished, or a two-factor code is needed.")


def _join_link(request: Request, body: Join) -> InviteLink:
    """Check where the request came from, and load the link."""
    try:
        return invite_links.load_invite_link(get_store(request), body.credential)
    except InviteLinkInvalidError:
        raise Refused(404, "invite_link_invalid") from None


class JoinInfoReply(Reply):
    label: str
    remaining: int


@route(
    "POST /api/join/info", summary="What an invite link is",
    tag="Invite links", access=PUBLIC, feature="invite_links", use=[SameOriginJoin],
)
def join_info(request: Request, body: Join) -> JoinInfoReply:
    link = _join_link(request, body)
    return JoinInfoReply(label=link.label, remaining=link.remaining)


class JoinMatch(Reply):
    id: int
    display_name: str
    has_pin: bool


class JoinMatchReply(Reply):
    matches: list[JoinMatch]
    can_create: bool


@route(
    "POST /api/join/match", summary="Accounts matching a name",
    tag="Invite links", access=PUBLIC, feature="invite_links", use=[SameOriginJoin],
)
def join_match(request: Request, body: Join) -> JoinMatchReply:
    """The "did you mean...?": the accounts from this link whose names are
    close to what was typed. The page always shows this step before creating
    anyone, even with no matches, because a typo would otherwise use up a
    place."""
    link = _join_link(request, body)
    if not users.valid_display_name(body.display_name):
        raise Refused(400, "display name must be 1-80 characters")
    matches = invite_links.invite_matches(get_store(request), link, body.display_name)
    rows = [JoinMatch(id=user.id, display_name=user.display_name, has_pin=pins.has_pin(user)) for user in matches]
    return JoinMatchReply(matches=rows, can_create=link.remaining > 0)


@route(
    "POST /api/join/claim", summary="Sign in as an existing account",
    tag="Invite links", access=PUBLIC, feature="invite_links", use=[SameOriginJoin],
)
async def join_claim(request: Request, body: Join) -> JOINED:
    """Sign in as an account this link created -- the same person on another
    device -- asking for the PIN if that person set one.

    An account with a password and no PIN is refused: anyone holding the link
    can pick any name on it, and that must not walk around the password. The
    person signs in with it instead. An account with two-factor on still has
    to give its code after this, PIN or not."""
    link = await run(_join_link, request, body)
    store, cfg = get_store(request), get_config(request)
    try:
        user = await run(invite_links.invite_account, store, link, body.user_id)
    except NotInviteAccountError:
        raise Refused(404, "no_such_account") from None

    if pins.has_pin(user):
        attempt = PINS.reserve(user.id)
        if attempt is None:
            raise Refused(429, "pin_locked")
        with attempt:
            ok = await run(pins.check_pin, user, body.pin)
            attempt.passed() if ok else attempt.failed()
        if not ok:
            audit_as(request, await run(user_actor, store, user.id, "anon"), KIND_AUTH, LEVEL_WARN, "wrong pin on an invite link", {"link_id": link.id})
            raise Refused(403, "pin_needed" if not body.pin else "pin_wrong")
    elif passwords.usable(user, cfg.passwords_enabled):
        raise Refused(403, "use_password")

    try:
        signed, user = await run(invite_links.claim_invite_account, store, body.credential, user.id, sign_in_rules(cfg))
    except InviteLinkInvalidError:
        raise Refused(404, "invite_link_invalid") from None
    except NotInviteAccountError:
        raise Refused(404, "no_such_account") from None
    message = "invite link accepted, waiting for a code" if signed.challenge else "signed back in through an invite link"
    audit_as(request, await run(user_actor, store, user.id, "session"), KIND_AUTH, LEVEL_INFO, message, {"link_id": link.id})
    return await sign_in_response(request, signed, JoinedReply(ok=True, display_name=user.display_name), 200)  # type: ignore[return-value]


@route(
    "POST /api/join/create", summary="Join as a new account",
    tag="Invite links", access=PUBLIC, feature="invite_links", status=201, errors=(409,),
    use=[SameOriginJoin],
)
async def join_create(request: Request, body: Join) -> JOINED:
    """Make a new account through the link, if it has places left, and sign
    it in."""
    link = await run(_join_link, request, body)
    if not users.valid_display_name(body.display_name):
        raise Refused(400, "display name must be 1-80 characters")

    store, cfg = get_store(request), get_config(request)
    try:
        session_credential, user = await run(invite_links.join_invite_link, store, body.credential, body.display_name, cfg.session_ttl_seconds)
    except InviteLinkInvalidError:
        raise Refused(404, "invite_link_invalid") from None
    except InviteLinkFullError:
        raise Refused(409, "invite_link_full") from None
    audit_as(request, await run(user_actor, store, user.id, "session"), KIND_AUTH, LEVEL_INFO, "joined through an invite link", {"link_id": link.id})
    signed = SignIn(user_id=user.id, session_credential=session_credential)
    return await sign_in_response(request, signed, JoinedReply(ok=True, display_name=user.display_name), 201)  # type: ignore[return-value]
