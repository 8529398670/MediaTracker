"""Invite links: one link for a whole group -- posted in a group chat, say.

Each person who opens it types their name. A new name becomes a new account
(always role user), up to max_uses of them. A name close to one that already
joined through this link is offered back ("did you mean...?"), which is how
the same person signs in on their next device.

Picking an existing name signs you in as that person, so anyone holding the
link can be anyone who joined through it. Two limits keep that sane: only
accounts this link created can be picked (never an admin, never someone who
joined another way), and a person can set a PIN, which is then asked for. See
app/models/pins.py.

Same "<id>.<secret>" shape as the other credentials. The secret is a long
random token, so sha256 is enough; bcrypt is for low-entropy secrets.

accounts is append-only. Deleting an account does not hand its place back --
the link was for that many people, and the id is never reused, so the stale
entry simply never matches anything again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core import encryption
from app.core.db import BUCKET_INVITE_LINKS, BUCKET_SESSIONS, BUCKET_USERS, Record, Store, Transaction
from app.models import RestoreGoneError, deleted_long_ago, from_iso, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models.pins import name_closeness
from app.models.sessions import new_session, split_credential
from app.models.users import ROLE_USER, User, create_user_tx, get_user

INVITE_LINK_MAX_USES = 1000
INVITE_LINK_MAX_DAYS = 365

# How long a dead link's row is kept before the purge drops it, so the admin
# list still shows last week's links.
INVITE_LINK_RETENTION = timedelta(days=30)


class InviteLinkInvalidError(Exception):
    """The link is malformed, unknown, has the wrong secret, is expired or
    switched off, or its maker is no longer an enabled admin. One error for
    all of them, so the answer cannot be used to tell them apart."""


class InviteLinkFullError(Exception):
    """The link has no places left."""


class NotInviteAccountError(Exception):
    """That account cannot be signed in to through this link."""


class BadInviteLinkError(ValueError):
    def __init__(self) -> None:
        super().__init__("label must be 1-80 characters, uses 1-1000, days 1-365")


class InviteNotAdminError(Exception):
    def __init__(self) -> None:
        super().__init__("an invite link must be made by an enabled admin")


@dataclass
class InviteLink:
    id: str
    secret_hash: str
    label: str
    max_uses: int
    created_by: int
    created_at: datetime
    expires_at: datetime
    accounts: list[int] = field(default_factory=list)
    revoked_at: datetime | None = None
    # Set by delete_invite_link; restorable for RESTORE_WINDOW, like a key.
    deleted_at: datetime | None = None
    deleted_by: int | None = None

    @property
    def remaining(self) -> int:
        return max(0, self.max_uses - len(self.accounts))

    @property
    def live(self) -> bool:
        return self.revoked_at is None and self.deleted_at is None and utc_now() < self.expires_at

    def owns(self, user_id: int) -> bool:
        return user_id in self.accounts

    def to_record(self) -> Record:
        return {
            "id": self.id,
            "secret_hash": self.secret_hash,
            "label": self.label,
            "max_uses": self.max_uses,
            "accounts": list(self.accounts),
            "created_by": self.created_by,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "revoked_at": to_iso(self.revoked_at),
            "deleted_at": to_iso(self.deleted_at),
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_record(cls, record: Record) -> "InviteLink":
        return cls(
            id=record["id"],
            secret_hash=record["secret_hash"],
            label=record["label"],
            max_uses=record["max_uses"],
            accounts=list(record.get("accounts") or []),
            created_by=record["created_by"],
            created_at=from_iso(record["created_at"]),
            expires_at=from_iso(record["expires_at"]),
            revoked_at=from_iso(record.get("revoked_at")),
            deleted_at=from_iso(record.get("deleted_at")),
            deleted_by=record.get("deleted_by"),
        )


def valid_invite_link(label: object, max_uses: object, days: object) -> bool:
    return (
        isinstance(label, str)
        and 1 <= len(label.strip()) <= 80
        and isinstance(max_uses, int) and not isinstance(max_uses, bool)
        and 1 <= max_uses <= INVITE_LINK_MAX_USES
        and isinstance(days, int) and not isinstance(days, bool)
        and 1 <= days <= INVITE_LINK_MAX_DAYS
    )


def issue_invite_link(store: Store, label: str, max_uses: int, ttl: timedelta, created_by: int) -> tuple[str, InviteLink]:
    """Returns (credential, link). The credential exists exactly once, like a
    login link: only its hash is stored."""
    link_id = encryption.url_token(12)
    secret = encryption.url_token(24)
    now = utc_now()
    link = InviteLink(
        id=link_id,
        secret_hash=encryption.sha256_hex(secret),
        label=label.strip(),
        max_uses=max_uses,
        created_by=created_by,
        created_at=now,
        expires_at=now + ttl,
    )
    store.put(BUCKET_INVITE_LINKS, link_id, link.to_record())
    return f"{link_id}.{secret}", link


def issue_invite_link_as(store: Store, created_by: int, label: str, max_uses: int, days: int) -> tuple[str, InviteLink] | None:
    """issue_invite_link with the checks the CLI needs: the inputs are in range
    and the maker is an enabled admin, since a link made by anyone else would
    never load. None if there is no such user."""
    if not valid_invite_link(label, max_uses, days):
        raise BadInviteLinkError()
    creator = get_user(store, created_by)
    if creator is None:
        return None
    if creator.disabled or not creator.is_admin:
        raise InviteNotAdminError()
    return issue_invite_link(store, label, max_uses, timedelta(days=days), created_by)


def _split(credential: object) -> tuple[str, str] | None:
    if not isinstance(credential, str):
        return None
    return split_credential(credential.strip().strip("/"))


def _usable(link: InviteLink, secret: str, creator: Record | None) -> bool:
    """A link also dies with its maker's admin rights: once the admin who made
    it is disabled, deleted, or made a plain user, it stops working."""
    if not encryption.constant_time_equal(link.secret_hash, encryption.sha256_hex(secret)) or not link.live:
        return False
    if creator is None:
        return False
    maker = User.from_record(creator)
    return maker.is_admin and not maker.disabled


def load_invite_link(store: Store, credential: object) -> InviteLink:
    """Check a credential and return its live link, or raise
    InviteLinkInvalidError -- the same for every way it can be wrong."""
    parts = _split(credential)
    record = None if parts is None else store.get(BUCKET_INVITE_LINKS, parts[0])
    if record is None:
        raise InviteLinkInvalidError()
    link = InviteLink.from_record(record)
    if not _usable(link, parts[1], store.get(BUCKET_USERS, link.created_by)):
        raise InviteLinkInvalidError()
    return link


def _load_invite_link_tx(tx: Transaction, credential: object) -> InviteLink:
    """load_invite_link inside the caller's transaction, so the checks and
    whatever the link is used for land together."""
    parts = _split(credential)
    record = None if parts is None else tx.get(BUCKET_INVITE_LINKS, parts[0])
    if record is None:
        raise InviteLinkInvalidError()
    link = InviteLink.from_record(record)
    if not _usable(link, parts[1], tx.get(BUCKET_USERS, link.created_by)):
        raise InviteLinkInvalidError()
    return link


def join_invite_link(store: Store, credential: str, display_name: str, session_ttl_seconds: int) -> tuple[str, User]:
    """Create a new account through the link and the session it signs in
    with; returns (session credential, user). Checking the link, taking a
    place, creating the account and storing the session are one transaction,
    so two people joining at the same moment cannot both take the last place,
    and a link switched off mid-way either lands first or refuses."""
    with store.transaction() as tx:
        link = _load_invite_link_tx(tx, credential)
        if link.remaining <= 0:
            raise InviteLinkFullError()
        user = create_user_tx(tx, display_name, ROLE_USER)
        link.accounts.append(user.id)
        tx.put(BUCKET_INVITE_LINKS, link.id, link.to_record())
        session_id, session_credential, session = new_session(user.id, session_ttl_seconds)
        tx.put(BUCKET_SESSIONS, session_id, session.to_record())
    return session_credential, user


def claim_invite_account(store: Store, credential: str, user_id: int, session_ttl_seconds: int) -> tuple[str, User]:
    """Sign in as an account this link created -- the same person on another
    device. The caller checks the PIN first (bcrypt stays outside the write
    lock); everything else is re-checked here, in the transaction that stores
    the session."""
    with store.transaction() as tx:
        link = _load_invite_link_tx(tx, credential)
        record = tx.get(BUCKET_USERS, user_id) if link.owns(user_id) else None
        user = None if record is None else User.from_record(record)
        if user is None or user.disabled or user.is_admin:
            raise NotInviteAccountError()
        session_id, session_credential, session = new_session(user.id, session_ttl_seconds)
        tx.put(BUCKET_SESSIONS, session_id, session.to_record())
    return session_credential, user


def invite_account(store: Store, link: InviteLink, user_id: object) -> User:
    """An account the link may sign in as, or NotInviteAccountError: never an
    admin, a disabled account, or one that did not join through this link."""
    if not isinstance(user_id, int) or isinstance(user_id, bool) or not link.owns(user_id):
        raise NotInviteAccountError()
    user = get_user(store, user_id)
    if user is None or user.disabled or user.is_admin:
        raise NotInviteAccountError()
    return user


def invite_matches(store: Store, link: InviteLink, typed: str) -> list[User]:
    """This link's accounts whose names are close to typed, closest first.
    Disabled accounts and admins are never offered."""
    found: list[tuple[int, User]] = []
    for user_id in link.accounts:
        try:
            user = invite_account(store, link, user_id)
        except NotInviteAccountError:
            continue
        score = name_closeness(typed, user.display_name)
        if score >= 0:
            found.append((score, user))
    found.sort(key=lambda entry: entry[0])  # stable: ties keep join order
    return [user for _, user in found]


def list_invite_links(store: Store) -> list[InviteLink]:
    """Every link, newest first, leaving out deleted ones."""
    links = [InviteLink.from_record(record) for _, record in store.all(BUCKET_INVITE_LINKS)]
    links = [link for link in links if link.deleted_at is None]
    links.sort(key=lambda link: link.created_at, reverse=True)
    return links


def get_invite_link(store: Store, link_id: str) -> InviteLink | None:
    """Load a link by its public id, without its secret: for managing a link,
    never for joining through one."""
    record = store.get(BUCKET_INVITE_LINKS, link_id)
    return None if record is None else InviteLink.from_record(record)


def revoke_invite_link(store: Store, link_id: str) -> bool:
    """Switch a link off. Nobody can join or sign back in through it
    afterwards; the accounts it made keep their sessions."""

    def mutate(record: Record) -> None:
        if record.get("revoked_at") is None:
            record["revoked_at"] = to_iso(utc_now())

    return store.update_value(BUCKET_INVITE_LINKS, link_id, mutate) is not None


def delete_invite_link(store: Store, link_id: str, actor_id: int | None) -> bool:
    """Take a link off the list and stop it working; False if there is no
    such link or it is already deleted. The accounts it made stay; they just
    can no longer sign in on a new device through it.

    Like delete_api_key, it only marks the row, so restore_invite_link can
    bring it back for RESTORE_WINDOW. Revoking stays the one-way switch."""
    found = False

    def mutate(record: Record) -> None:
        nonlocal found
        found = record.get("deleted_at") is None
        mark_deleted(record, actor_id)

    return store.update_value(BUCKET_INVITE_LINKS, link_id, mutate) is not None and found


def restore_invite_link(store: Store, link_id: str, actor_id: int, actor_is_admin: bool) -> InviteLink:
    """Undo delete_invite_link. Raises a RestoreError when the window has
    passed or the actor may not. Only admins reach this today, so in practice
    any admin may restore any link."""

    def mutate(record: Record) -> None:
        unmark_deleted(record, actor_id, actor_is_admin)

    record = store.update_value(BUCKET_INVITE_LINKS, link_id, mutate)
    if record is None:
        raise RestoreGoneError()
    return InviteLink.from_record(record)


def purge_dead_invite_links(store: Store) -> int:
    """Drop links revoked or expired longer than INVITE_LINK_RETENTION ago,
    and deleted ones past their RESTORE_WINDOW. Dead links are already refused by load_invite_link, so this is only
    housekeeping."""
    cutoff = utc_now() - INVITE_LINK_RETENTION

    def dead(_key: object, record: Record) -> bool:
        revoked_at = from_iso(record.get("revoked_at"))
        return (
            (revoked_at is not None and revoked_at < cutoff)
            or from_iso(record["expires_at"]) < cutoff
            or deleted_long_ago(record)
        )

    return store.delete_where(BUCKET_INVITE_LINKS, dead)
