"""Two-factor sign-in: a code from an authenticator app (TOTP), with recovery
codes for a lost phone. It is optional per person, and auth.two_factor decides
whether it is offered at all.

The secret has to be readable to check a code, so unlike every other
credential here it cannot be hashed. It is encrypted on its own with the
secret key, on top of whatever the record gets, because server.encrypt_at_rest
can be off.

Asking for the code at sign-in is app/models/sign_in.py.
"""
from __future__ import annotations

import time

from app.core import encryption
from app.core.db import BUCKET_USERS, Record, Store
from app.models.users import User

RECOVERY_CODE_COUNT = 10


class WrongCodeError(Exception):
    """The code was not right, or was empty, or was already used."""

    def __init__(self) -> None:
        super().__init__("that code is not right")


class AlreadyOnError(Exception):
    """Setup was started on an account that already has 2FA."""

    def __init__(self) -> None:
        super().__init__("two-factor sign-in is already on")


class NotOnError(Exception):
    """Something that needs 2FA on an account without it."""

    def __init__(self) -> None:
        super().__init__("two-factor sign-in is not on")


def is_on(user: User) -> bool:
    return user.totp_secret != ""


def _record_is_on(record: Record) -> bool:
    return record.get("totp_secret", "") != ""


def _normalize_recovery_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def _matches_totp(encrypted_secret: str, code: str, after_step: int, secret_key: str) -> int | None:
    secret = encryption.xchacha_decrypt_string(secret_key, encrypted_secret)
    return encryption.totp_match(secret, code, int(time.time()), after_step)


def check_code(record: Record, code: object, secret_key: str) -> str:
    """Check a code against a user record and use it up: a TOTP step can not
    be used twice, and a recovery code is gone once used. Returns "totp" or
    "recovery"; raises WrongCodeError.

    It changes the record it is given, so the caller decides when that is
    stored -- in the transaction that does whatever the code was for."""
    if not isinstance(code, str):
        raise WrongCodeError()
    code = code.strip().replace(" ", "")
    if code == "":
        raise WrongCodeError()

    if len(code) == encryption.TOTP_DIGITS and code.isascii() and code.isdigit():
        step = _matches_totp(record["totp_secret"], code, record.get("totp_last_step", 0), secret_key)
        if step is None:
            raise WrongCodeError()
        record["totp_last_step"] = step
        return "totp"

    wanted = encryption.sha256_hex(_normalize_recovery_code(code))
    hashes = record.get("recovery_hashes", [])
    found = [stored for stored in hashes if encryption.constant_time_equal(stored, wanted)]
    if not found:
        raise WrongCodeError()
    record["recovery_hashes"] = [stored for stored in hashes if stored not in found]
    return "recovery"


def start_setup(store: Store, user_id: int, secret_key: str) -> str | None:
    """Make a secret for the person to add to their app, and hold it until
    they prove it worked. Starting again replaces it. Returns the secret, or
    None if there is no such user. Raises AlreadyOnError."""
    secret = encryption.totp_new_secret()

    def mutate(record: Record) -> None:
        if _record_is_on(record):
            raise AlreadyOnError()
        record["totp_pending"] = encryption.xchacha_encrypt_string(secret_key, secret)

    return secret if store.update_value(BUCKET_USERS, user_id, mutate) is not None else None


def confirm_setup(store: Store, user_id: int, code: object, secret_key: str) -> list[str] | None:
    """Turn 2FA on, once a code proves the app has the secret. Returns the
    recovery codes -- the only time they exist in readable form -- or None if
    there is no such user. Raises WrongCodeError or AlreadyOnError."""
    codes = [encryption.recovery_code() for _ in range(RECOVERY_CODE_COUNT)]

    def mutate(record: Record) -> None:
        if _record_is_on(record):
            raise AlreadyOnError()
        pending = record.get("totp_pending", "")
        if pending == "" or not isinstance(code, str):
            raise WrongCodeError()
        step = _matches_totp(pending, code.strip().replace(" ", ""), 0, secret_key)
        if step is None:
            raise WrongCodeError()
        record["totp_secret"] = pending
        record["totp_pending"] = ""
        record["totp_last_step"] = step
        record["recovery_hashes"] = [encryption.sha256_hex(_normalize_recovery_code(item)) for item in codes]

    return codes if store.update_value(BUCKET_USERS, user_id, mutate) is not None else None


def clear_record(record: Record) -> None:
    """Take every trace of 2FA off a user record."""
    record["totp_secret"] = ""
    record["totp_pending"] = ""
    record["totp_last_step"] = 0
    record["recovery_hashes"] = []


def disable(store: Store, user_id: int, code: object, secret_key: str) -> bool:
    """Turn 2FA off, which takes a valid code: a stolen session must not be
    able to remove it. False if there is no such user. Raises NotOnError or
    WrongCodeError."""

    def mutate(record: Record) -> None:
        if not _record_is_on(record):
            raise NotOnError()
        check_code(record, code, secret_key)
        clear_record(record)

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None
