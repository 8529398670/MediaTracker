"""User accounts, and the owner.

Links are the way in. A password is optional and off by default (see
app/models/passwords.py): an account gets one only by signing in with a link
first, so there is no signup, and the owner decides whether passwords work at
all. See references/architecture.md.

The owner is the one admin who outranks the others. It exists for a single
decision the admin role cannot settle by itself: who may permanently delete
an admin. Without it, any admin can delete any other, and the last one to act
wins.

It is recorded as one id in the meta bucket rather than as a role beside
admin and user. Roles are also what API keys carry and what narrow_role
compares, so a third one would spread into key scoping, role validation, and
every role check in the app -- all to express something that only matters to
a few account-management routes. As a marker, the owner is an ordinary admin
everywhere else.

The invariant: the owner is always an existing, enabled admin, or there is no
owner because there are no admins. Every path keeps it -- the first admin
created becomes the owner (create_user), nothing may delete or disable the
owner (app/models/credentials.py), and ownership only moves to another
enabled admin (transfer_owner). That is also why the first-run bootstrap
never fires again once an owner exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime

from app.core.db import BUCKET_META, BUCKET_USERS, Record, Store, Transaction
from app.models import from_iso, to_iso, utc_now

ROLE_ADMIN = "admin"
ROLE_USER = "user"

META_OWNER_KEY = "owner_user_id"


class NotAdminError(Exception):
    """Refusal for making a non-admin, or a disabled admin, the owner."""

    def __init__(self) -> None:
        super().__init__("the owner must be an enabled admin")


@dataclass
class User:
    id: int
    display_name: str
    role: str
    created_at: datetime
    disabled_at: datetime | None = None
    # The optional PIN asked for when someone signs back in through an
    # invite link. It is not a password: nothing else checks it. See
    # app/models/pins.py.
    pin_hash: str = ""
    # What password sign-in needs: a unique name to look the account up by,
    # since display names are not unique, and a bcrypt hash of what the
    # browser derived from the password. See app/models/passwords.py.
    username: str = ""
    password_hash: str = ""
    # The owner's per-account block. It stops the password working and keeps
    # the hash, so unblocking restores it.
    password_blocked: bool = False
    # TOTP secrets are encrypted here as well as with the record, because
    # server.encrypt_at_rest can be off and a secret cannot be hashed. See
    # app/models/two_factor.py.
    totp_secret: str = ""
    totp_pending: str = ""
    totp_last_step: int = 0
    recovery_hashes: list[str] = field(default_factory=list)
    # The "Showing" picker for someone who is not an admin: an admin grants
    # it, and may say whose lists the account starts on (default_subject,
    # None for its own). Admins always have the picker. See
    # app/routes/subject.py.
    can_show_others: bool = False
    default_subject: int | None = None
    # The admin's lock on that choice: the account always sees default_subject
    # (its own lists if None) and cannot switch. Ignored for admins.
    showing_locked: bool = False

    @property
    def disabled(self) -> bool:
        return self.disabled_at is not None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def to_record(self) -> Record:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "role": self.role,
            "created_at": to_iso(self.created_at),
            "disabled_at": to_iso(self.disabled_at),
            "pin_hash": self.pin_hash,
            "username": self.username,
            "password_hash": self.password_hash,
            "password_blocked": self.password_blocked,
            "totp_secret": self.totp_secret,
            "totp_pending": self.totp_pending,
            "totp_last_step": self.totp_last_step,
            "recovery_hashes": self.recovery_hashes,
            "can_show_others": self.can_show_others,
            "default_subject": self.default_subject,
            "showing_locked": self.showing_locked,
        }

    @classmethod
    def from_record(cls, record: Record) -> "User":
        return cls(
            id=record["id"],
            display_name=record["display_name"],
            role=record["role"],
            created_at=from_iso(record["created_at"]),
            disabled_at=from_iso(record.get("disabled_at")),
            pin_hash=record.get("pin_hash", ""),
            username=record.get("username", ""),
            password_hash=record.get("password_hash", ""),
            password_blocked=record.get("password_blocked", False),
            totp_secret=record.get("totp_secret", ""),
            totp_pending=record.get("totp_pending", ""),
            totp_last_step=record.get("totp_last_step", 0),
            recovery_hashes=record.get("recovery_hashes", []),
            can_show_others=record.get("can_show_others", False),
            default_subject=record.get("default_subject"),
            showing_locked=record.get("showing_locked", False),
        )


def may_act_for_others(user: User) -> bool:
    """Whether the account may use the Showing picker (?user=<id>)."""
    return user.is_admin or user.can_show_others


def locked_subject(user: User) -> int | None:
    """Whose lists an account an admin has locked must see, or None when it
    may choose (admins are never locked)."""
    if user.is_admin or not user.showing_locked:
        return None
    return user.default_subject if user.default_subject is not None else user.id


class NoSuchSubjectError(Exception):
    """set_showing was asked to start an account on someone who is not there."""


def set_showing(store: Store, user_id: int, allowed: bool, default_subject: int | None, locked: bool = False) -> User | None:
    """Grant or take away the Showing picker, and say whose lists the account
    starts on; None if there is no such account. Starting on someone else
    needs the picker (the server would refuse ?user= otherwise), so choosing
    someone grants it. Taking the picker away with no one chosen forgets the
    starting person, and starting on yourself is stored as None. locked keeps
    the account on that person: it cannot switch the picker."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        if default_subject == user_id:
            default_subject = None
        if default_subject is not None:
            allowed = True
        if default_subject is not None and tx.get(BUCKET_USERS, default_subject) is None:
            raise NoSuchSubjectError()
        record["can_show_others"] = bool(allowed)
        record["default_subject"] = default_subject
        # Without Showing and with no one chosen there is nothing to lock.
        record["showing_locked"] = bool(locked) and (allowed or default_subject is not None)
        tx.put(BUCKET_USERS, user_id, record)
        return User.from_record(record)


def valid_role(role: str) -> bool:
    return role in (ROLE_ADMIN, ROLE_USER)


def valid_display_name(display_name: str) -> bool:
    """Bounds the one piece of free text a user controls. The cap is about
    keeping the database and the UI sane; escaping for display is the
    frontend's job (static/js/dom.js never uses innerHTML for user values)."""
    return isinstance(display_name, str) and 1 <= len(display_name.strip()) <= 80


def create_user(store: Store, display_name: str, role: str) -> User:
    """Store a new account. The first admin ever created -- by the first-run
    bootstrap or `manage bootstrap-admin` -- also becomes the owner, in the
    same transaction, so there is no moment where admins exist and no owner
    does.

    Ids come from the bucket's sequence and are never reused, so a deleted
    account's id can never come back as a different person."""
    with store.transaction() as tx:
        return create_user_tx(tx, display_name, role)


def create_user_tx(tx: Transaction, display_name: str, role: str) -> User:
    """create_user inside the caller's transaction, for an account that has to
    be created together with something else -- joining through an invite link
    creates the account, takes a place on the link, and starts the session
    all at once."""
    if not valid_role(role):
        raise ValueError(f"invalid role: {role!r}")
    user = User(
        id=tx.next_sequence(BUCKET_USERS),
        display_name=display_name.strip(),
        role=role,
        created_at=utc_now(),
    )
    tx.put(BUCKET_USERS, user.id, user.to_record())
    if role == ROLE_ADMIN and owner_id_tx(tx) is None:
        _set_owner_tx(tx, user.id)
    return user


def get_user(store: Store, user_id: int) -> User | None:
    record = store.get(BUCKET_USERS, user_id)
    return None if record is None else User.from_record(record)


def list_users(store: Store) -> list[User]:
    return [User.from_record(record) for _, record in store.all(BUCKET_USERS)]


class RenameConflictError(Exception):
    """The name was not what the caller expected: someone changed it since.
    current is the name it has now."""

    def __init__(self, current: str) -> None:
        super().__init__("the name was changed somewhere else in the meantime")
        self.current = current


def rename_user(store: Store, user_id: int, display_name: str, expect: str | None = None) -> bool:
    """Goes through update_value rather than get_user followed by a put. The
    read and the write land in one transaction, which is what stops two
    concurrent admin requests from each reading the old row and the slower one
    silently discarding the other's change.

    Disabling an account is not here: it has to take the account's sessions
    and login links with it in the same transaction, so it lives in
    app/models/credentials.py beside the other operations that span
    buckets.

    expect, when given, is the name the caller believes is stored, checked
    in the same transaction: RenameConflictError if it is not. It is what
    makes an undo of a rename safe -- putting the old name back must not
    overwrite one somebody chose in another tab since."""

    def mutate(record: Record) -> None:
        if expect is not None and record["display_name"] != expect.strip():
            raise RenameConflictError(record["display_name"])
        record["display_name"] = display_name.strip()

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None


def any_admin_exists(store: Store) -> bool:
    """Decides whether the server prints a first-run login link on boot. Once
    one enabled admin exists, that bootstrap path stays closed."""
    return any(user.is_admin and not user.disabled for user in list_users(store))


def owner_id_tx(tx: Transaction) -> int | None:
    """The owner's id inside the caller's transaction, or None."""
    record = tx.get(BUCKET_META, META_OWNER_KEY)
    return None if record is None else record["user_id"]


def _set_owner_tx(tx: Transaction, user_id: int) -> None:
    tx.put(BUCKET_META, META_OWNER_KEY, {"user_id": user_id})


def get_owner_id(store: Store) -> int | None:
    record = store.get(BUCKET_META, META_OWNER_KEY)
    return None if record is None else record["user_id"]


def ensure_owner(store: Store) -> int | None:
    """Adopt an owner for a database that predates the marker: the lowest-id
    enabled admin, which on any database that started from the first-run
    bootstrap is the account that bootstrap created. A no-op once an owner is
    recorded, so it is safe to call on every boot."""
    with store.transaction() as tx:
        owner_id = owner_id_tx(tx)
        if owner_id is not None:
            return owner_id
        for _key, record in tx.all(BUCKET_USERS):  # key order is id order
            user = User.from_record(record)
            if user.is_admin and not user.disabled:
                _set_owner_tx(tx, user.id)
                return user.id
    return None


def transfer_owner(store: Store, user_id: int) -> User | None:
    """Hand ownership to another enabled admin; None if there is no such user.

    Reachable only from the CLI: ownership is the one thing the web UI cannot
    change about itself, so a compromised admin session cannot promote itself
    past the other admins."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return None
        user = User.from_record(record)
        if not user.is_admin or user.disabled:
            raise NotAdminError()
        _set_owner_tx(tx, user_id)
    return user
