"""Limits wrong guesses at anything a person types: a PIN, a password, a
two-factor code. Six digits is a million guesses, and four is ten thousand, so
without this those are decoration.

In memory, like the rate limiter -- so it resets on restart and is per
process. It is a brake on guessing, not a record of anything.
"""
from __future__ import annotations

import threading
import time
from typing import Hashable

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
# Keys can be anything a stranger typed, so what is remembered has to be
# bounded. Past this the oldest count is forgotten.
MAX_ENTRIES = 10000


class AttemptGuard:
    """max_failures misses lock a key for lockout_seconds."""

    def __init__(self, max_failures: int = MAX_FAILURES, lockout_seconds: int = LOCKOUT_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._failures: dict[Hashable, int] = {}
        self._until: dict[Hashable, float] = {}

    def locked(self, key: Hashable) -> bool:
        with self._lock:
            until = self._until.get(key)
            if until is None:
                return False
            if time.monotonic() < until:
                return True
            del self._until[key]
            return False

    def record(self, key: Hashable, ok: bool) -> None:
        with self._lock:
            if ok:
                self._failures.pop(key, None)
                return
            self._failures[key] = self._failures.get(key, 0) + 1
            if self._failures[key] >= self._max_failures:
                self._until[key] = time.monotonic() + self._lockout_seconds
                self._failures.pop(key, None)
            self._trim()

    def _trim(self) -> None:
        now = time.monotonic()
        if len(self._until) > self._max_entries:
            self._until = {key: until for key, until in self._until.items() if until > now}
        for entries in (self._failures, self._until):
            while len(entries) > self._max_entries:
                del entries[next(iter(entries))]
