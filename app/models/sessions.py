"""The server side of a login.

The cookie never carries the user id or the role -- only an opaque reference
-- so revoking access is a matter of deleting this record, with no token
denylist to maintain.

The credential is shaped "<id>.<secret>": the id is the record key, so lookup
is a single fetch, and only the secret's hash is stored. A stolen database
therefore contains nothing that can be replayed as a cookie.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import encryption
from app.core.db import BUCKET_SESSIONS, Record, Store, Transaction
from app.models import from_iso, to_iso, utc_now
from app.models.users import User, get_user
from app.models.users import RenameConflictError

# How stale last_seen_at is allowed to get: the same trade as
# API_KEY_TOUCH_INTERVAL, a write on one request in a great many.
SESSION_TOUCH_INTERVAL = timedelta(minutes=15)
USER_AGENT_MAX_CHARS = 256
LABEL_MAX_CHARS = 80


@dataclass
class Session:
    user_id: int
    secret_hash: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    # What the Account screen lists, so a person can tell their devices apart.
    # A session from before these existed has none of them.
    ip: str = ""
    user_agent: str = ""
    last_seen_at: datetime | None = None
    # What the account's owner calls this device. It sits beside the browser
    # and system rather than replacing them, so a name cannot hide what a
    # device says it is.
    label: str = ""
    # The record's key. Filled in on the way out of the store and never written
    # into the record.
    id: str = ""

    def to_record(self) -> Record:
        record = {
            "user_id": self.user_id,
            "secret_hash": self.secret_hash,
            "csrf_token": self.csrf_token,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
        }
        if self.ip:
            record["ip"] = self.ip
        if self.user_agent:
            record["user_agent"] = self.user_agent
        if self.last_seen_at is not None:
            record["last_seen_at"] = to_iso(self.last_seen_at)
        if self.label:
            record["label"] = self.label
        return record

    @classmethod
    def from_record(cls, record: Record) -> "Session":
        return cls(
            user_id=record["user_id"],
            secret_hash=record["secret_hash"],
            csrf_token=record["csrf_token"],
            created_at=from_iso(record["created_at"]),
            expires_at=from_iso(record["expires_at"]),
            ip=record.get("ip", ""),
            user_agent=record.get("user_agent", ""),
            last_seen_at=from_iso(record.get("last_seen_at")),
            label=record.get("label", ""),
        )


def split_credential(raw: str) -> tuple[str, str] | None:
    """Split "<id>.<secret>" into (id, secret), or None for anything else.
    Shared by sessions, login tokens, and API keys, which all use the shape."""
    if not isinstance(raw, str):
        return None
    record_id, dot, secret = raw.partition(".")
    if not dot or not record_id or not secret:
        return None
    return record_id, secret


def new_session(user_id: int, ttl_seconds: int) -> tuple[str, str, Session]:
    """Returns (session_id, credential, session) without storing anything.
    Its callers -- sign_in.start_sign_in_tx, sign_in.finish_challenge,
    join_invite_link -- store the session in the same transaction that
    checks the link and the account are still good, so there is deliberately
    no create_session that writes one on its own. The credential is set on the cookie and never stored; only its
    secret's hash is."""
    session_id = encryption.url_token(16)
    secret = encryption.url_token(32)
    now = utc_now()
    session = Session(
        user_id=user_id,
        secret_hash=encryption.sha256_hex(secret),
        csrf_token=encryption.url_token(24),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    return session_id, f"{session_id}.{secret}", session


def load_session(store: Store, credential: str) -> tuple[Session, User] | None:
    """None for anything that is not a live session -- wrong shape, unknown
    id, bad secret, expired, or belonging to a disabled user. Callers only
    ever ask "am I logged in", and folding every failure into the same answer
    avoids leaking which check failed."""
    parts = split_credential(credential)
    if parts is None:
        return None
    session_id, secret = parts

    record = store.get(BUCKET_SESSIONS, session_id)
    if record is None:
        return None
    session = Session.from_record(record)
    session.id = session_id

    if not encryption.constant_time_equal(session.secret_hash, encryption.sha256_hex(secret)):
        return None
    if utc_now() > session.expires_at:
        store.delete(BUCKET_SESSIONS, session_id)
        return None

    user = get_user(store, session.user_id)
    if user is None or user.disabled:
        return None
    return session, user


def remember_client(store: Store, session_id: str, ip: str, user_agent: str) -> None:
    """Note where a new session signed in from. Every way of signing in ends
    in auth.sign_in_response, which calls this, rather than each store of a
    session taking two more arguments."""

    def mutate(record: Record) -> None:
        record["ip"] = ip
        record["user_agent"] = user_agent[:USER_AGENT_MAX_CHARS]
        record["last_seen_at"] = to_iso(utc_now())

    store.update_value(BUCKET_SESSIONS, session_id, mutate)


def session_expiry(session: Session, now: datetime, ttl_seconds: int, max_age_seconds: int) -> datetime:
    """When a session used now should end: ttl from now, but never later than
    max_age after it was signed in, and never earlier than it already ends, so
    shortening the ttl does not cut off a session mid-use."""
    limit = session.created_at + timedelta(seconds=max_age_seconds)
    return max(min(now + timedelta(seconds=ttl_seconds), limit), session.expires_at)


def touch_session(store: Store, session: Session, ttl_seconds: int, max_age_seconds: int) -> bool:
    """Record use at most once per SESSION_TOUCH_INTERVAL, and move the
    session's end out in the same write, so someone using the app every day is
    not signed out at a date set when they signed in. Without a password that
    would mean asking an admin for a new link. True means the end moved, which
    is the caller's cue to send the cookie again: it has its own expiry.

    Called when a request is resolved, not from load_session, so re-checking
    an open stream does not count as the person doing something. Failures are
    ignored on purpose, like api_keys._touch: a timestamp is not worth failing
    a request for."""
    now = utc_now()
    if session.last_seen_at is not None and now - session.last_seen_at < SESSION_TOUCH_INTERVAL:
        return False
    expires = session_expiry(session, now, ttl_seconds, max_age_seconds)

    def mutate(record: Record) -> None:
        record["last_seen_at"] = to_iso(now)
        record["expires_at"] = to_iso(expires)

    try:
        store.update_value(BUCKET_SESSIONS, session.id, mutate)
    except Exception:  # noqa: BLE001 -- bookkeeping only, see above
        return False
    session.last_seen_at = now
    extended = expires > session.expires_at
    session.expires_at = expires
    return extended


def list_sessions(store: Store, user_id: int) -> list[Session]:
    """One account's live sessions, newest first."""
    now = utc_now()
    found = []
    for key, record in store.all(BUCKET_SESSIONS):
        if record["user_id"] != user_id:
            continue
        session = Session.from_record(record)
        if now > session.expires_at:
            continue
        session.id = str(key)
        found.append(session)
    found.sort(key=lambda session: session.created_at, reverse=True)
    return found


def valid_session_label(label: object) -> bool:
    """True for a label, or for nothing, which clears it."""
    return isinstance(label, str) and len(label.strip()) <= LABEL_MAX_CHARS


def label_session(store: Store, user_id: int, session_id: str, label: str, expect: str | None = None) -> bool:
    """Name one of an account's own devices; an empty label clears the name.
    False when it has no such session, which covers another account's, as with
    revoke_session.

    expect, when given, is the label the caller believes is stored, as in
    users.rename_user: RenameConflictError if it is not."""
    found = False

    def mutate(record: Record) -> None:
        nonlocal found
        if record["user_id"] != user_id:
            return
        found = True
        current = record.get("label", "")
        if expect is not None and current != expect.strip():
            raise RenameConflictError(current)
        if label.strip():
            record["label"] = label.strip()
        else:
            record.pop("label", None)

    return store.update_value(BUCKET_SESSIONS, session_id, mutate) is not None and found


def revoke_session(store: Store, user_id: int, session_id: str) -> bool:
    """End one of an account's sessions. False when it has no such session,
    which covers another account's: looking and deleting are one transaction,
    so nothing can change hands between them."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_SESSIONS, session_id)
        if record is None or record["user_id"] != user_id:
            return False
        tx.delete(BUCKET_SESSIONS, session_id)
    return True


def revoke_other_sessions(store: Store, user_id: int, keep_id: str) -> int:
    """End every live session an account has but one, and say how many. An
    expired one is left for the purge, so the count is what the person saw
    listed."""
    now = utc_now()

    def doomed(key: object, record: Record) -> bool:
        return record["user_id"] == user_id and key != keep_id and now <= from_iso(record["expires_at"])

    return store.delete_where(BUCKET_SESSIONS, doomed)


def destroy_session(store: Store, credential: str) -> None:
    parts = split_credential(credential)
    if parts is not None:
        store.delete(BUCKET_SESSIONS, parts[0])


def destroy_sessions_for_user(tx: Transaction, user_id: int) -> int:
    """Delete every session an account holds, inside the caller's
    transaction. Deleting sessions is only ever half of a revocation, so this
    takes a transaction rather than opening one: set_user_disabled and
    revoke_all_credentials (app/models/credentials.py) run it together with
    the account change, and a login link redeemed at the same moment either
    lands before (and its session is deleted here) or after (and sees the
    change)."""
    return tx.delete_where(BUCKET_SESSIONS, lambda _key, record: record["user_id"] == user_id)


def purge_expired_sessions(store: Store) -> int:
    """Part of the hourly purge job. Expired rows are already
    refused by load_session, so this is only housekeeping to stop the file
    growing without bound -- one transaction, for the same reason as above."""
    now = utc_now()
    return store.delete_where(BUCKET_SESSIONS, lambda _key, record: now > from_iso(record["expires_at"]))
