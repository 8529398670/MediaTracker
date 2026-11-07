"""Titles: the shared half of the library.

A title is what a thing *is* -- its name, year, poster, cast, the family's
tags and notes about it. Everyone sees the same titles; what each person has
done with one (queued it, watched it, loved it) is user_state.py.

Records are plain dicts in the shape app/media/normalize.py defines
(TITLE_EMPTY), plus the book-keeping fields the server alone sets:

    id, added_at, added_by, updated_at, updated_by, rev,
    deleted_at, deleted_by, merged_into

Deleting is soft and restorable for library.restore_days -- longer than the
10-minute undo window elsewhere, because a deleted title disappears for the
whole family, and they may not notice the same afternoon. The purge then
removes the title and every person's state for it.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.db import BUCKET_TITLES, BUCKET_USER_STATE, Store, Transaction
from app.media import normalize
from app.models import playlists
from app.models import RestoreExpiredError, RestoreGoneError, from_iso, to_iso, utc_now
from app.models.revision import NotFoundError, bump, check_expect, mark_purged

Title = dict[str, Any]


class TooManyTitlesError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"the library is full ({limit} titles, library.max_titles)")


def is_live(record: Title) -> bool:
    return record.get("deleted_at") is None


def build(fields: dict[str, Any], actor_id: int | None, ident: str | None = None, added_at: str | None = None) -> Title:
    """A complete new record from cleaned fields; nothing written."""
    now = to_iso(utc_now())
    record: Title = dict(normalize.TITLE_EMPTY)
    record.update(fields)
    record.update(
        {
            "id": ident or normalize.new_title_id(),
            "added_at": added_at or now,
            "added_by": actor_id,
            "updated_at": now,
            "updated_by": actor_id,
            "rev": 0,
            "deleted_at": None,
            "deleted_by": None,
            "merged_into": None,
        }
    )
    return record


def create_title_tx(tx: Transaction, record: Title, rev: int) -> Title:
    record["rev"] = rev
    tx.put(BUCKET_TITLES, record["id"], record)
    return record


def create_title(store: Store, fields: dict[str, Any], actor_id: int | None, max_titles: int) -> Title:
    """Store one new title. fields must already be cleaned
    (normalize.clean_title_fields) and carry a non-empty title."""
    if not fields.get("title"):
        raise ValueError("a title needs a name")
    record = build(fields, actor_id)
    with store.transaction() as tx:
        if count_live(tx) >= max_titles:
            raise TooManyTitlesError(max_titles)
        return create_title_tx(tx, record, bump(tx))


def count_live(tx: Transaction) -> int:
    return sum(1 for _key, record in tx.all(BUCKET_TITLES) if is_live(record))


def get_title(store: Store, title_id: str) -> Title | None:
    return store.get(BUCKET_TITLES, title_id) if normalize.valid_title_id(title_id) else None


def update_title(
    store: Store, title_id: str, changes: dict[str, Any], expect: object, actor_id: int | None
) -> tuple[Title, dict[str, Any]]:
    """Apply cleaned changes. Returns (record, previous values of the fields
    that changed) -- the previous values are the undo."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_TITLES, title_id)
        if record is None or not is_live(record):
            raise NotFoundError()
        check_expect(record, expect)
        previous = {field: record.get(field) for field, value in changes.items() if record.get(field) != value}
        if "title" in changes and not changes["title"]:
            raise ValueError("a title needs a name")
        if not previous:
            return record, {}
        record.update(changes)
        record["updated_at"] = to_iso(utc_now())
        record["updated_by"] = actor_id
        record["rev"] = bump(tx)
        tx.put(BUCKET_TITLES, title_id, record)
        return record, previous


def fill_title(store: Store, title_id: str, found: dict[str, Any], seen_updated_at: str | None, overwrite: tuple[str, ...] = ()) -> dict[str, Any]:
    """What a background job does: write provider facts into the blanks of a
    title -- or, for the fields named in overwrite, over them -- but only if
    nobody edited the title since the job read it. Returns the previous
    values of what it changed (empty when it changed nothing or stood
    aside)."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_TITLES, title_id)
        if record is None or not is_live(record):
            return {}
        if seen_updated_at is not None and record.get("updated_at") != seen_updated_at:
            return {}
        previous: dict[str, Any] = {}
        for field, value in found.items():
            if field not in normalize.ENRICH_FIELDS or normalize.is_empty(value):
                continue
            if normalize.is_empty(record.get(field)) or (field in overwrite and record.get(field) != value):
                previous[field] = record.get(field)
                record[field] = value
        if not previous:
            return {}
        record["updated_at"] = to_iso(utc_now())
        record["rev"] = bump(tx)
        tx.put(BUCKET_TITLES, title_id, record)
        return previous


def delete_title(store: Store, title_id: str, actor_id: int | None) -> Title:
    with store.transaction() as tx:
        return delete_title_tx(tx, title_id, actor_id, bump(tx))


def delete_title_tx(tx: Transaction, title_id: str, actor_id: int | None, rev: int, merged_into: str | None = None) -> Title:
    record = tx.get(BUCKET_TITLES, title_id)
    if record is None:
        raise NotFoundError()
    if record.get("deleted_at") is None:
        record["deleted_at"] = to_iso(utc_now())
        record["deleted_by"] = actor_id
        record["merged_into"] = merged_into
        record["rev"] = rev
        tx.put(BUCKET_TITLES, title_id, record)
    return record


def restore_title(store: Store, title_id: str, restore_days: int) -> Title:
    """Anyone may put a deleted title back: it is the family's, not the
    deleter's. Past the window it is gone for good (the purge's job)."""
    with store.transaction() as tx:
        return restore_title_tx(tx, title_id, restore_days, bump(tx))


def restore_title_tx(tx: Transaction, title_id: str, restore_days: int, rev: int) -> Title:
    record = tx.get(BUCKET_TITLES, title_id)
    if record is None:
        raise RestoreGoneError()
    deleted_at = from_iso(record.get("deleted_at"))
    if deleted_at is None:
        return record
    if utc_now() - deleted_at > timedelta(days=restore_days):
        raise RestoreExpiredError()
    record["deleted_at"] = None
    record["deleted_by"] = None
    record["merged_into"] = None
    record["rev"] = rev
    tx.put(BUCKET_TITLES, title_id, record)
    return record


def purge_deleted_titles(store: Store, restore_days: int) -> int:
    """Remove titles deleted longer ago than the window, with every person's
    state for them, in one transaction."""
    cutoff = utc_now() - timedelta(days=restore_days)
    with store.transaction() as tx:
        doomed = {
            key
            for key, record in tx.all(BUCKET_TITLES)
            if record.get("deleted_at") is not None and from_iso(record["deleted_at"]) < cutoff
        }
        if not doomed:
            return 0
        for key in doomed:
            tx.delete(BUCKET_TITLES, key)
        tx.delete_where(BUCKET_USER_STATE, lambda _key, state: state.get("title_id") in doomed)
        playlists.forget_titles_tx(tx, doomed)
        mark_purged(tx, bump(tx))
        return len(doomed)

