"""The one place a proven first factor turns into a signed-in browser.

A login link, an invite link and a password all end here, inside the
transaction that spent them. An account with two-factor on gets a short-lived
challenge instead of a session, so a way of signing in cannot forget to ask
for the code: there is no other path to a session for an existing account.
(Joining through an invite link makes a new account, which has no 2FA yet.)

A challenge is shaped "<id>.<secret>" like every other credential, and it is
sha256'd for the same reason: the secret is random, there is nothing to brute
force. It lives for CHALLENGE_TTL_SECONDS and is used once.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.core import encryption
from app.core.db import BUCKET_SESSIONS, Transaction
from app.core.db import BUCKET_SIGN_IN_CHALLENGES, BUCKET_USERS, Store
from app.models import from_iso, to_iso, utc_now
from app.models import two_factor
from app.models.sessions import new_session
from app.models.sessions import split_credential
from app.models.users import User

CHALLENGE_TTL_SECONDS = 5 * 60


class ChallengeInvalidError(Exception):
    """Expired, used, never existed, or the account can no longer sign in."""

    def __init__(self) -> None:
        super().__init__("that sign-in has expired, start again")


@dataclass(frozen=True)
class SignInRules:
    """What decides how a sign-in ends, from the running configuration."""

    session_ttl_seconds: int
    two_factor: bool = False


@dataclass
class SignIn:
    """A first factor that was accepted. Exactly one of session_credential
    and challenge is set."""

    user_id: int
    session_credential: str = ""
    challenge: str = ""


def start_sign_in_tx(tx: Transaction, user: User, rules: SignInRules) -> SignIn:
    """Store a session, or a challenge if this account has to give a code."""
    if rules.two_factor and two_factor.is_on(user):
        challenge_id = encryption.url_token(12)
        secret = encryption.url_token(24)
        tx.put(BUCKET_SIGN_IN_CHALLENGES, challenge_id, {
            "user_id": user.id,
            "secret_hash": encryption.sha256_hex(secret),
            "expires_at": to_iso(utc_now() + timedelta(seconds=CHALLENGE_TTL_SECONDS)),
        })
        return SignIn(user_id=user.id, challenge=f"{challenge_id}.{secret}")
    session_id, session_credential, session = new_session(user.id, rules.session_ttl_seconds)
    tx.put(BUCKET_SESSIONS, session_id, session.to_record())
    return SignIn(user_id=user.id, session_credential=session_credential)


def _live_challenge(record: dict | None, secret: str) -> bool:
    return (
        record is not None
        and utc_now() <= from_iso(record["expires_at"])
        and encryption.constant_time_equal(record["secret_hash"], encryption.sha256_hex(secret))
    )


def challenge_user_id(store: Store, credential: object) -> int | None:
    """Whose challenge this is, or None for anything that is not a live one.
    The route needs to know before it checks a code, to count the guess."""
    parts = split_credential(credential)
    if parts is None:
        return None
    record = store.get(BUCKET_SIGN_IN_CHALLENGES, parts[0])
    return record["user_id"] if _live_challenge(record, parts[1]) else None


def finish_challenge(store: Store, credential: object, code: object, session_ttl_seconds: int, secret_key: str) -> tuple[SignIn, str]:
    """Spend a challenge and a code on a session, in one transaction, so two
    requests with the same code cannot both sign in, and an account disabled
    meanwhile is refused. Returns (sign-in, "totp" or "recovery"). Raises
    ChallengeInvalidError or two_factor.WrongCodeError; a wrong code leaves
    the challenge alive for another try."""
    parts = split_credential(credential)
    if parts is None:
        raise ChallengeInvalidError()
    challenge_id, secret = parts
    with store.transaction() as tx:
        challenge = tx.get(BUCKET_SIGN_IN_CHALLENGES, challenge_id)
        if not _live_challenge(challenge, secret):
            raise ChallengeInvalidError()
        record = tx.get(BUCKET_USERS, challenge["user_id"])
        if record is None or User.from_record(record).disabled or record.get("totp_secret", "") == "":
            raise ChallengeInvalidError()

        method = two_factor.check_code(record, code, secret_key)
        tx.put(BUCKET_USERS, record["id"], record)
        tx.delete(BUCKET_SIGN_IN_CHALLENGES, challenge_id)
        session_id, session_credential, session = new_session(record["id"], session_ttl_seconds)
        tx.put(BUCKET_SESSIONS, session_id, session.to_record())
    return SignIn(user_id=record["id"], session_credential=session_credential), method


def delete_challenges_for_user(tx: Transaction, user_id: int) -> int:
    """Remove every challenge an account holds, inside the caller's
    transaction: a challenge is a sign-in in progress, so anything that ends
    an account's sign-ins ends these too."""
    return tx.delete_where(BUCKET_SIGN_IN_CHALLENGES, lambda _key, record: record["user_id"] == user_id)


def purge_expired_challenges(store: Store) -> int:
    now = utc_now()
    return store.delete_where(BUCKET_SIGN_IN_CHALLENGES, lambda _key, record: now > from_iso(record["expires_at"]))
