"""One module per stored record type. There is no ORM and no query builder --
each module is a small set of plain functions over app.core.db.Store, which is
enough for a store of records and keeps the storage layer readable end to end.

Records are JSON, so timestamps are stored as ISO 8601 strings in UTC; the
helpers below are the only place that conversion happens.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# How long a deleted API key or invite link can still be put back. Delete is
# the undoable one of the two ways to switch something off (revoke is final),
# and this is the length of that undo: long enough for the toast's Undo and a
# Ctrl+Z a few minutes later, short enough that "deleted" soon means gone.
# The row is dead the moment it is deleted; the window only decides how long
# the purge leaves it lying there.
RESTORE_WINDOW = timedelta(minutes=10)


class RestoreError(Exception):
    """Why a deleted row cannot be put back. The message is safe to show."""


class RestoreGoneError(RestoreError):
    def __init__(self) -> None:
        super().__init__("it is not there to restore")


class RestoreForbiddenError(RestoreError):
    def __init__(self) -> None:
        super().__init__("only whoever deleted it, or an admin, can put it back")


class RestoreExpiredError(RestoreError):
    def __init__(self) -> None:
        super().__init__("it was deleted too long ago to put back")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def from_iso(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def mark_deleted(record: dict, actor_id: int | None) -> None:
    """The soft delete both deletable records share: dead now, restorable for
    RESTORE_WINDOW. Deleting twice keeps the first mark, like revoking."""
    if record.get("deleted_at") is None:
        record["deleted_at"] = to_iso(utc_now())
        record["deleted_by"] = actor_id


def unmark_deleted(record: dict, actor_id: int, actor_is_admin: bool) -> None:
    """The other half of mark_deleted, for update_value. Raises a
    RestoreError, which rolls the write back, when it may not happen."""
    deleted_at = from_iso(record.get("deleted_at"))
    if deleted_at is None:
        raise RestoreGoneError()
    if not actor_is_admin and record.get("deleted_by") != actor_id:
        raise RestoreForbiddenError()
    if utc_now() - deleted_at > RESTORE_WINDOW:
        raise RestoreExpiredError()
    record["deleted_at"] = None
    record["deleted_by"] = None


def deleted_long_ago(record: dict) -> bool:
    """For the purges: a deletion past its undo window."""
    deleted_at = from_iso(record.get("deleted_at"))
    return deleted_at is not None and utc_now() - deleted_at > RESTORE_WINDOW
