"""Password sign-in, which the owner turns on with auth.passwords.

The server never sees a password. static/js/password.js derives a digest from
it in the browser (PBKDF2, salted with this install's salt and the username),
and that digest is what travels and what bcrypt hashes here. So:

- A leaked database cannot be replayed: it holds a bcrypt of the digest.
- A compromised server, or a stray log, cannot expose a password someone
  reuses elsewhere.
- The digest still works as a password on the wire. This is no substitute for
  HTTPS: anyone reading the traffic could replay it, or change the page.
- Rules about the password itself (its length) live in the browser, because
  the server cannot see it. Skipping them only weakens your own account.

The salt comes from a public route and is the same for everyone, because a
per-user one would need a lookup that says which usernames exist.

A digest is 43 base64url characters, safely under bcrypt's 72-byte limit.
"""
from __future__ import annotations

import re

from app.core import encryption
from app.core.db import BUCKET_META, BUCKET_SESSIONS, BUCKET_USERS, Store, Transaction
from app.models import two_factor
from app.models.sign_in import SignIn, SignInRules, start_sign_in_tx
from app.models.users import User, list_users

USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")
DIGEST_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
META_SALT_KEY = "password_salt"

# Compared against when there is no account to compare with, so an unknown
# name takes as long to refuse as a wrong password. The value is never a match
# for anything; only the time it takes matters.
_dummy_hash = ""


class BadUsernameError(ValueError):
    def __init__(self) -> None:
        super().__init__("a username is 3 to 32 letters, digits, dots, dashes or underscores")


class BadDigestError(ValueError):
    def __init__(self) -> None:
        super().__init__("that is not a password digest")


class UsernameTakenError(Exception):
    def __init__(self) -> None:
        super().__init__("that username is taken")


class PasswordBlockedError(Exception):
    def __init__(self) -> None:
        super().__init__("passwords are blocked for this account")


def normalize_username(value: object) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.match(value) is not None


def has_password(user: User) -> bool:
    return user.password_hash != ""


def usable(user: User, passwords_enabled: bool) -> bool:
    """Whether a password can sign this account in right now."""
    return passwords_enabled and has_password(user) and not user.password_blocked


def install_salt(store: Store) -> str:
    """This install's salt, made the first time it is asked for. Not a secret:
    it only stops one install's digests being useful against another's."""
    record = store.get(BUCKET_META, META_SALT_KEY)
    if record is not None:
        return record["salt"]
    with store.transaction() as tx:
        record = tx.get(BUCKET_META, META_SALT_KEY)
        if record is None:
            record = {"salt": encryption.url_token(16)}
            tx.put(BUCKET_META, META_SALT_KEY, record)
    return record["salt"]


def _username_taken(tx: Transaction, username: str, user_id: int) -> bool:
    return any(
        record.get("username", "") == username and key != user_id
        for key, record in tx.all(BUCKET_USERS)
    )


def set_password(
    store: Store,
    user_id: int,
    username: object,
    digest: object,
    keep_session_id: str,
    code: object,
    two_factor_enabled: bool,
    secret_key: str,
) -> bool:
    """Set the account's username and password, or with an empty digest
    remove the password. False if there is no such user.

    The two go together because the digest is salted with the username: a new
    name is a new digest. The old password is not asked for, because this is
    also how a forgotten one is replaced after signing in with a link, and a
    session can already mint itself a link. 2FA is what protects this, so an
    account that has it must give a code.

    Every other session of the account ends, in case the reason for changing
    a password is that someone else has it."""
    clearing = digest == ""
    name = normalize_username(username)
    if not clearing:
        if USERNAME_PATTERN.match(name) is None:
            raise BadUsernameError()
        if not valid_digest(digest):
            raise BadDigestError()
    # bcrypt outside the transaction, so the write lock is not held for it.
    password_hash = "" if clearing else encryption.bcrypt_hash(digest)

    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user_id)
        if record is None:
            return False
        if record.get("password_blocked", False):
            raise PasswordBlockedError()
        if two_factor_enabled and record.get("totp_secret", "") != "":
            two_factor.check_code(record, code, secret_key)
        if not clearing:
            if _username_taken(tx, name, user_id):
                raise UsernameTakenError()
            record["username"] = name
        record["password_hash"] = password_hash
        tx.put(BUCKET_USERS, user_id, record)
        tx.delete_where(
            BUCKET_SESSIONS,
            lambda key, session: session["user_id"] == user_id and key != keep_session_id,
        )
    return True


def set_blocked(store: Store, user_id: int, blocked: bool) -> bool:
    """The owner's per-account switch. The hash stays, so unblocking restores
    the password, and sessions stay signed in: this is about how an account
    signs in, not about ending access. False if there is no such user."""

    def mutate(record: dict) -> None:
        record["password_blocked"] = blocked

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None


def _find_by_username(store: Store, username: str) -> User | None:
    """A scan: with every record encrypted there is no column to search, and
    this runs once per sign-in, behind the attempt limits."""
    for user in list_users(store):
        if user.username == username:
            return user
    return None


def check_password(store: Store, username: object, digest: object) -> User | None:
    """The account these sign in, or None. Every way of being wrong costs one
    bcrypt comparison, so the time taken says nothing about which it was."""
    global _dummy_hash
    name = normalize_username(username)
    good_digest = valid_digest(digest)
    user = _find_by_username(store, name) if name != "" else None
    if user is None or not good_digest or user.disabled or user.password_blocked or not has_password(user):
        if _dummy_hash == "":
            _dummy_hash = encryption.bcrypt_hash(encryption.url_token(24))
        encryption.bcrypt_compare(_dummy_hash, digest if good_digest else "-" * 43)
        return None
    return user if encryption.bcrypt_compare(user.password_hash, digest) else None


def start_password_sign_in(store: Store, user: User, rules: SignInRules) -> SignIn | None:
    """Turn a checked password into a sign-in. bcrypt ran outside the write
    lock, so everything it depended on is checked again here: a password
    changed, an account disabled or blocked in between is refused."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_USERS, user.id)
        current = None if record is None else User.from_record(record)
        if (
            current is None
            or current.disabled
            or current.password_blocked
            or current.password_hash != user.password_hash
        ):
            return None
        return start_sign_in_tx(tx, current, rules)
