"""PINs, and the name matching behind invite links.

A PIN is what stops anyone holding an invite link from signing in as anyone
who joined through it. It is asked for only there: login links, sessions and
API keys never look at it, so it is not a password and does not make this a
password system.
"""
from __future__ import annotations

import re
import threading
import time

from app.core import encryption
from app.core.db import BUCKET_USERS, Record, Store
from app.models.users import User

PIN_PATTERN = re.compile(r"^[0-9]{4,8}$")
PIN_MAX_FAILURES = 5
PIN_LOCKOUT_SECONDS = 15 * 60


class BadPinError(ValueError):
    def __init__(self) -> None:
        super().__init__("a PIN is 4 to 8 digits")


def set_user_pin(store: Store, user_id: int, pin: str) -> bool:
    """Set or (with "") clear the PIN. bcrypt-hashed: four digits is a small
    space, so the hash is only half the protection -- the claim route also
    limits attempts per account (PinGuard). False if there is no such user."""
    pin_hash = ""
    if pin != "":
        if not isinstance(pin, str) or not PIN_PATTERN.match(pin):
            raise BadPinError()
        pin_hash = encryption.bcrypt_hash(pin)

    def mutate(record: Record) -> None:
        record["pin_hash"] = pin_hash

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None


def has_pin(user: User) -> bool:
    return user.pin_hash != ""


def check_pin(user: User, pin: object) -> bool:
    """True for an account with no PIN, whatever was typed."""
    if user.pin_hash == "":
        return True
    return isinstance(pin, str) and pin != "" and encryption.bcrypt_compare(user.pin_hash, pin)


class PinGuard:
    """Limits wrong PINs per account. Four digits is only ten thousand
    guesses, so without this a PIN is decoration: PIN_MAX_FAILURES misses
    lock that account's PIN for PIN_LOCKOUT_SECONDS. In memory, like the rate
    limiter -- so it resets on restart and is per process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[int, int] = {}
        self._until: dict[int, float] = {}

    def locked(self, user_id: int) -> bool:
        with self._lock:
            return time.monotonic() < self._until.get(user_id, 0.0)

    def record(self, user_id: int, ok: bool) -> None:
        with self._lock:
            if ok:
                self._failures.pop(user_id, None)
                return
            self._failures[user_id] = self._failures.get(user_id, 0) + 1
            if self._failures[user_id] >= PIN_MAX_FAILURES:
                self._until[user_id] = time.monotonic() + PIN_LOCKOUT_SECONDS
                self._failures.pop(user_id, None)


def _normalize_name(name: str) -> str:
    """Fold a name for comparison: case, spacing, and punctuation should not
    make "Anna-Marie" a stranger to "anna marie"."""
    return "".join(character for character in name.strip().lower() if character.isalnum())


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, start=1):
        current = [i]
        for j, right in enumerate(b, start=1):
            cost = 0 if left == right else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[len(b)]


def name_closeness(typed: str, existing: str) -> int:
    """How alike two names are: 0 is the same name once case and punctuation
    are ignored, larger is further apart, and -1 means "not similar enough to
    suggest". This is the "did you mean...?" behind invite links."""
    a, b = _normalize_name(typed), _normalize_name(existing)
    if a == "" or b == "":
        return -1
    if a == b:
        return 0
    if len(a) >= 3 and (b.startswith(a) or a.startswith(b)):
        return 1
    distance = _edit_distance(a, b)
    allowed = 2 if len(b) >= 6 else 1
    if distance > allowed:
        return -1
    return distance + 1
