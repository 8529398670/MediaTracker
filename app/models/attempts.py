"""Limits wrong guesses at anything a person types: a PIN, a password, a
two-factor code. Six digits is a million guesses, and four is ten thousand, so
without this those are decoration.

In memory, like the rate limiter -- so it resets on restart and is per
process. It is a brake on guessing, not a record of anything.

Reserve, then settle: a route calls reserve() before it checks the guess and
settles the Attempt after, with how it went. reserve() counts the attempt in
flight, under the lock, and refuses once the misses so far plus the attempts
in flight reach max_failures. So guesses sent in parallel cannot all slip past
a check that only counts finished ones: twenty at once still get max_failures
evaluated, no more. Checking locked() and calling record() afterwards has
exactly that race, which is why the routes do not.
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

VOID, FAILED, PASSED = "void", "failed", "passed"


class Attempt:
    """One reserved guess. Mark it failed() or passed() once judged; leaving
    the with block settles it, as void (it costs nothing) if neither was
    called -- a stale challenge, an error."""

    def __init__(self, guard: AttemptGuard, key: Hashable) -> None:
        self._guard, self._key, self._outcome = guard, key, VOID

    def failed(self) -> None:
        self._outcome = FAILED

    def passed(self) -> None:
        self._outcome = PASSED

    def __enter__(self) -> Attempt:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._guard._settle(self._key, self._outcome)


class AttemptGuard:
    """max_failures misses lock a key for lockout_seconds."""

    def __init__(self, max_failures: int = MAX_FAILURES, lockout_seconds: int = LOCKOUT_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._failures: dict[Hashable, int] = {}
        self._pending: dict[Hashable, int] = {}
        self._until: dict[Hashable, float] = {}

    def reserve(self, key: Hashable) -> Attempt | None:
        """Claim one attempt for key before the guess is checked, or None when
        key is locked or its misses plus the attempts in flight have reached
        the limit. Use the Attempt as a context manager so it is settled."""
        with self._lock:
            until = self._until.get(key)
            if until is not None:
                if time.monotonic() < until:
                    return None
                del self._until[key]
            if self._failures.get(key, 0) + self._pending.get(key, 0) >= self._max_failures:
                return None
            self._pending[key] = self._pending.get(key, 0) + 1
        return Attempt(self, key)

    def _settle(self, key: Hashable, outcome: str) -> None:
        with self._lock:
            left = self._pending.get(key, 0) - 1
            if left > 0:
                self._pending[key] = left
            else:
                self._pending.pop(key, None)
            if outcome == PASSED:
                self._failures.pop(key, None)
            elif outcome == FAILED:
                self._record_failure(key)

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
        """The result of an attempt that was never reserved. The routes use
        reserve() instead (see the module's comment); this stays for code
        that counts outside a request."""
        with self._lock:
            if ok:
                self._failures.pop(key, None)
                return
            self._record_failure(key)

    def _record_failure(self, key: Hashable) -> None:
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
