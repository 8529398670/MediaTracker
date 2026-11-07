"""The library's revision counter, and the one way an edit says "you were
looking at an old copy".

Every write to the shared library -- a title, someone's state, a type --
bumps meta.library_rev in the same transaction and stamps the record it
wrote with the new number. That gives three things for the price of one
integer:

- the in-memory snapshot (library_cache.py) knows when to rebuild, even when
  the write came from another process (`manage import-legacy`, a job);
- a browser polling /api/library?since=<rev> gets only what changed;
- the purge records the rev it ran at, so a browser that missed it reloads
  everything instead of keeping titles that no longer exist.
"""
from __future__ import annotations

from typing import Any

from app.core.db import BUCKET_META, Store, Transaction

META_LIBRARY_REV = "library_rev"
META_PURGED_REV = "library_purged_rev"


class ConflictError(Exception):
    """The record was not what the caller expected -- someone changed it
    since they looked. current is what it is now, so the caller can show it.
    The routes answer 409, and Undo drops the step with "changed elsewhere"."""

    def __init__(self, current: dict[str, Any] | None) -> None:
        super().__init__("it was changed somewhere else in the meantime")
        self.current = current


class NotFoundError(Exception):
    def __init__(self, what: str = "title") -> None:
        super().__init__(f"no such {what}")


def bump(tx: Transaction) -> int:
    record = tx.get(BUCKET_META, META_LIBRARY_REV)
    rev = (record or {}).get("rev", 0) + 1
    tx.put(BUCKET_META, META_LIBRARY_REV, {"rev": rev})
    return rev


def current(store: Store) -> int:
    record = store.get(BUCKET_META, META_LIBRARY_REV)
    return (record or {}).get("rev", 0)


def purged_rev(store: Store) -> int:
    record = store.get(BUCKET_META, META_PURGED_REV)
    return (record or {}).get("rev", 0)


def mark_purged(tx: Transaction, rev: int) -> None:
    tx.put(BUCKET_META, META_PURGED_REV, {"rev": rev})


def check_expect(record: dict[str, Any] | None, expect: object) -> None:
    """expect is {field: value the caller believes is stored}. Any mismatch is
    a ConflictError. An empty or missing expect checks nothing -- an ordinary
    edit is last-writer-wins per field, which is what two people editing
    different fields of one title want; undo and redo always send one."""
    if not isinstance(expect, dict) or not expect:
        return
    for field, value in expect.items():
        if (record or {}).get(field) != value:
            raise ConflictError(record)
