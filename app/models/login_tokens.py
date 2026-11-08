"""Login tokens -- this project's entire replacement for a signup form and a
password reset flow. An admin (or the first-run bootstrap) mints one for a
specific user; redeeming the link is the login.

By default a link works once. It can instead allow up to max_uses sign-ins, or
any number (unlimited), always by the same account -- a link a person keeps
for a week, say, instead of asking for a new one on every device. An
expires_at of None means it never expires.

Same "<id>.<secret>" shape as a session, but the secret is bcrypt-hashed
rather than sha256'd. bcrypt is affordable here because it runs once per
sign-in, never once per request, and sign-ins are on their own rate budget;
the id prefix is what keeps that to a single hash comparison -- hashing every
candidate row would hand anyone a trivial way to pin the CPU.

Rows written before links could be reused have no max_uses (read as 1) and no
uses (read from used_at), so they keep meaning "once".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import encryption
from app.core.db import BUCKET_LOGIN_TOKENS, BUCKET_USERS, Record, Store, Transaction
from app.models import from_iso, to_iso, utc_now
from app.models.sessions import split_credential
from app.models.sign_in import SignIn, SignInRules, start_sign_in_tx
from app.models.users import User

LOGIN_LINK_MAX_USES = 1000
LOGIN_LINK_MAX_DAYS = 365
LOGIN_LINK_MAX_MINUTES = LOGIN_LINK_MAX_DAYS * 24 * 60

# How long a used-up link that never expires is kept, so a late click on it
# still says "already used". A link with an expiry is kept until then instead.
LOGIN_LINK_RETENTION = timedelta(days=30)


@dataclass
class LoginToken:
    user_id: int
    secret_hash: str
    created_at: datetime
    expires_at: datetime | None
    used_at: datetime | None = None  # the latest sign-in
    max_uses: int = 1
    unlimited: bool = False
    uses: int = 0

    def used_up(self) -> bool:
        return not self.unlimited and self.uses >= self.max_uses

    def expired(self, now: datetime | None = None) -> bool:
        return self.expires_at is not None and (now or utc_now()) > self.expires_at

    def usable(self) -> bool:
        return not self.used_up() and not self.expired()

    def info(self) -> dict:
        """The link as the UI shows it."""
        return {
            "max_uses": 0 if self.unlimited else self.max_uses,
            "unlimited": self.unlimited,
            "uses": self.uses,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "last_used_at": to_iso(self.used_at),
        }

    def to_record(self) -> Record:
        return {
            "user_id": self.user_id,
            "secret_hash": self.secret_hash,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "used_at": to_iso(self.used_at),
            "max_uses": self.max_uses,
            "unlimited": self.unlimited,
            "uses": self.uses,
        }

    @classmethod
    def from_record(cls, record: Record) -> "LoginToken":
        used_at = from_iso(record.get("used_at"))
        uses = record.get("uses") or (1 if used_at is not None else 0)
        return cls(
            user_id=record["user_id"],
            secret_hash=record["secret_hash"],
            created_at=from_iso(record["created_at"]),
            expires_at=from_iso(record.get("expires_at")),
            used_at=used_at,
            max_uses=max(1, record.get("max_uses") or 1),
            unlimited=bool(record.get("unlimited")),
            uses=uses,
        )


@dataclass(frozen=True)
class LinkOptions:
    """How a new link may be used. max_uses is ignored when unlimited is set;
    ttl_seconds 0 means the link never expires."""

    max_uses: int = 1
    unlimited: bool = False
    ttl_seconds: int = 0

    def valid(self) -> bool:
        uses_ok = self.unlimited or 1 <= self.max_uses <= LOGIN_LINK_MAX_USES
        return uses_ok and 0 <= self.ttl_seconds <= LOGIN_LINK_MAX_MINUTES * 60


class UnknownUserError(Exception):
    """issue_login_token was given a user id with no account behind it."""


class BadLoginLinkError(ValueError):
    """The uses or the expiry asked for are out of range."""

    def __init__(self) -> None:
        super().__init__("max_uses must be 0 (unlimited) or 1-1000, expires_in_minutes 0 (never) or 1-525600")


def once(ttl_seconds: int) -> LinkOptions:
    """The classic one-time link."""
    return LinkOptions(max_uses=1, ttl_seconds=ttl_seconds)


def _whole_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def resolve_link(max_uses: object, expires_in_minutes: object, once_ttl: int, multi_ttl: int) -> LinkOptions:
    """Turn what a caller asked for into options. max_uses: None means once, 0
    unlimited. expires_in_minutes: None means the configured default, 0 never.
    A link that works once defaults to once_ttl (auth.login_token_ttl_seconds);
    one that works more than once to multi_ttl
    (auth.multi_use_login_token_ttl_seconds), since a link meant to be kept for
    a while is no use if it dies in half an hour."""
    unlimited = False
    uses = 1
    if max_uses is not None:
        if not _whole_number(max_uses):
            raise BadLoginLinkError()
        if max_uses == 0:
            unlimited = True
        else:
            uses = max_uses
    ttl = multi_ttl if unlimited or uses > 1 else once_ttl
    if expires_in_minutes is not None:
        if not _whole_number(expires_in_minutes) or expires_in_minutes < 0:
            raise BadLoginLinkError()
        ttl = expires_in_minutes * 60
    options = LinkOptions(max_uses=0 if unlimited else uses, unlimited=unlimited, ttl_seconds=ttl)
    if not options.valid():
        raise BadLoginLinkError()
    return options


_EXPIRES = re.compile(r"^([0-9]+)([mhd])$")
_UNIT_MINUTES = {"m": 1, "h": 60, "d": 24 * 60}


def parse_link_flags(uses: str | None, expires: str | None) -> tuple[int | None, int | None]:
    """The CLI's --uses ("", "3", "unlimited") and --expires ("", "30m", "12h",
    "7d", "never") as (max_uses, expires_in_minutes) for resolve_link. Empty
    means the default."""
    uses = (uses or "").strip().lower()
    expires = (expires or "").strip().lower()
    max_uses: int | None = None
    if uses == "unlimited":
        max_uses = 0
    elif uses:
        if not uses.isdigit() or not 1 <= int(uses) <= LOGIN_LINK_MAX_USES:
            raise ValueError(f"--uses must be 1-{LOGIN_LINK_MAX_USES} or unlimited")
        max_uses = int(uses)
    minutes: int | None = None
    if expires == "never":
        minutes = 0
    elif expires:
        match = _EXPIRES.match(expires)
        minutes = int(match.group(1)) * _UNIT_MINUTES[match.group(2)] if match else 0
        if not match or not 1 <= minutes <= LOGIN_LINK_MAX_MINUTES:
            raise ValueError(f"--expires must be like 30m, 12h or 7d (at most {LOGIN_LINK_MAX_DAYS}d), or never")
    return max_uses, minutes


def describe_link(info: dict) -> str:
    """The one-line summary the CLI prints under a link."""
    if info["unlimited"]:
        text = "Works any number of times"
    elif info["max_uses"] == 1:
        text = "Works once"
    else:
        text = f"Works up to {info['max_uses']} times"
    if info["expires_at"] is None:
        return text + " and never expires."
    return text + ", until " + from_iso(info["expires_at"]).astimezone().strftime("%Y-%m-%d %H:%M") + "."


def issue_login_token(store: Store, user_id: int, ttl_seconds: int) -> str:
    """A link that works once, for ttl_seconds: issue_login_link with the
    classic options."""
    credential, _info = issue_login_link(store, user_id, once(ttl_seconds))
    return credential


def issue_login_link(store: Store, user_id: int, options: LinkOptions) -> tuple[str, dict]:
    """Returns the raw credential exactly once, and what the link allows. The
    credential is never stored and cannot be recovered -- if it is lost, mint
    another one.

    An account has at most one live link. Issuing a new one deletes any link
    the account could still use, in the same transaction, so "send them a new
    link" also kills the old one -- which is what you want when the old one
    went to the wrong place, and costs nothing when it simply expired. That
    includes a reusable link that has already been used: what matters is
    whether it would still let someone in."""
    if not options.valid():
        raise BadLoginLinkError()
    token_id = encryption.url_token(12)
    secret = encryption.url_token(24)
    now = utc_now()
    token = LoginToken(
        user_id=user_id,
        # bcrypt outside the transaction, so the write lock is not held for it.
        secret_hash=encryption.bcrypt_hash(secret),
        created_at=now,
        expires_at=now + timedelta(seconds=options.ttl_seconds) if options.ttl_seconds > 0 else None,
        max_uses=1 if options.unlimited else options.max_uses,
        unlimited=options.unlimited,
    )
    with store.transaction() as tx:
        if tx.get(BUCKET_USERS, user_id) is None:
            raise UnknownUserError(user_id)
        delete_pending_login_tokens(tx, user_id)
        tx.put(BUCKET_LOGIN_TOKENS, token_id, token.to_record())
    return f"{token_id}.{secret}", token.info()


def redeem_login_token(store: Store, credential: str, rules: SignInRules) -> SignIn | None:
    """Spend one use of a login link and start the sign-in it grants -- a
    session, or a two-factor challenge (see app/models/sign_in.py). Returns
    None for any failure -- expired, used up, never existed, the wrong secret,
    or a disabled account all look the same, so the answer cannot be used to
    probe which links are real.

    The bcrypt comparison runs before the write transaction, so the database's
    single write lock is never held for the deliberately slow part. Everything
    that decides the outcome is then re-checked inside one transaction: the
    token still has a use left and is unexpired, it is the same token that was
    compared, and the account exists and is enabled. Counting the use and
    storing the session happen there too. So two requests racing for a link's
    last use cannot both get a session, and a link redeemed while the account
    is being disabled either lands first (and set_user_disabled deletes its
    session and the link) or lands second (and is refused).

    With two-factor sign-in on, the use is counted when the code is asked
    for, not when it is entered."""
    parts = split_credential(credential)
    if parts is None:
        return None
    token_id, secret = parts

    record = store.get(BUCKET_LOGIN_TOKENS, token_id)
    if record is None:
        return None
    token = LoginToken.from_record(record)
    if not token.usable() or not encryption.bcrypt_compare(token.secret_hash, secret):
        return None

    with store.transaction() as tx:
        record = tx.get(BUCKET_LOGIN_TOKENS, token_id)
        if record is None:
            return None
        current = LoginToken.from_record(record)
        if not current.usable() or not encryption.constant_time_equal(current.secret_hash, token.secret_hash):
            return None
        owner = tx.get(BUCKET_USERS, current.user_id)
        if owner is None or User.from_record(owner).disabled:
            return None

        current.uses += 1
        current.used_at = utc_now()
        tx.put(BUCKET_LOGIN_TOKENS, token_id, current.to_record())
        return start_sign_in_tx(tx, User.from_record(owner), rules)


def live_login_links(store: Store) -> dict[int, dict]:
    """Each account with a usable link, to it, in one pass, for the admin user
    list. There is at most one per account (see issue_login_link)."""
    links: dict[int, dict] = {}
    for _key, record in store.all(BUCKET_LOGIN_TOKENS):
        token = LoginToken.from_record(record)
        if token.usable():
            links[token.user_id] = token.info()
    return links


def live_login_link(store: Store, user_id: int) -> dict | None:
    """The link the account could still sign in with, if any."""
    return live_login_links(store).get(user_id)


def cancel_login_link(store: Store, user_id: int) -> int:
    """Stop the account's live link working. Sessions it already made stay
    signed in, as with reissuing."""
    with store.transaction() as tx:
        return delete_pending_login_tokens(tx, user_id)


def delete_pending_login_tokens(tx: Transaction, user_id: int) -> int:
    """Remove every link an account could still sign in with, inside the
    caller's transaction -- unused ones, and reusable ones with uses left.
    Used-up and expired ones are left for the purge, so a second click on a
    spent link still fails as "already used"."""
    return tx.delete_where(
        BUCKET_LOGIN_TOKENS,
        lambda _key, record: record["user_id"] == user_id and LoginToken.from_record(record).usable(),
    )


def delete_login_tokens_for_user(tx: Transaction, user_id: int) -> int:
    """Remove every link an account holds, used ones included, inside the
    caller's transaction. Only delete_user wants this: once the account is
    gone, "already used" has nothing left to refer to."""
    return tx.delete_where(BUCKET_LOGIN_TOKENS, lambda _key, record: record["user_id"] == user_id)


def purge_expired_login_tokens(store: Store) -> int:
    """Drop spent and stale rows. Used tokens are kept until they expire
    rather than deleted on redemption, so a second click on a link fails as
    "already used" instead of looking like it never existed. A used-up link
    that never expires is kept for LOGIN_LINK_RETENTION after its last use."""
    now = utc_now()

    def dead(_key: object, record: Record) -> bool:
        token = LoginToken.from_record(record)
        if token.expired(now):
            return True
        return (
            token.expires_at is None and token.used_up()
            and token.used_at is not None and now - token.used_at > LOGIN_LINK_RETENTION
        )

    return store.delete_where(BUCKET_LOGIN_TOKENS, dead)
