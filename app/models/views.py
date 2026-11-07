"""Saved views: a named query (filters, sort, grouping) plus how cards look,
on one screen, one tap away -- "Unwatched pre-code by IMDb", "Mom's queue".

They belong to one person. Deleting is soft and restorable for the usual
undo window, like API keys.
"""
from __future__ import annotations

from typing import Any

from app.core.db import BUCKET_VIEWS, Store, Transaction
from app.media.normalize import text
from app.models import mark_deleted, to_iso, unmark_deleted, utc_now, deleted_long_ago
from app.models.revision import NotFoundError

MAX_VIEWS = 200
SCREENS = ("library", "discover")


def clean(raw: dict[str, Any]) -> dict[str, Any]:
    name = text(raw.get("name"), 80)
    if not name:
        raise ValueError("a view needs a name")
    screen = raw.get("screen") if raw.get("screen") in SCREENS else "library"
    query = text(raw.get("query"), 4000)
    card = raw.get("card") if isinstance(raw.get("card"), dict) else None
    return {"name": name, "screen": screen, "scope": text(raw.get("scope"), 80), "query": query, "card": card, "icon": text(raw.get("icon"), 40)}


def list_views(store: Store, owner_id: int) -> list[dict[str, Any]]:
    rows = [record for _key, record in store.all(BUCKET_VIEWS) if record["owner_id"] == owner_id and record.get("deleted_at") is None]
    return sorted(rows, key=lambda record: (record.get("position", 0), record["id"]))


def create_view(store: Store, owner_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    fields = clean(raw)
    with store.transaction() as tx:
        mine = [record for _key, record in tx.all(BUCKET_VIEWS) if record["owner_id"] == owner_id and record.get("deleted_at") is None]
        if len(mine) >= MAX_VIEWS:
            raise ValueError("too many saved views")
        ident = tx.next_sequence(BUCKET_VIEWS)
        record = {
            "id": ident,
            "owner_id": owner_id,
            **fields,
            "position": max((record.get("position", 0) for record in mine), default=0) + 1,
            "created_at": to_iso(utc_now()),
            "updated_at": to_iso(utc_now()),
            "deleted_at": None,
            "deleted_by": None,
        }
        tx.put(BUCKET_VIEWS, ident, record)
        return record


def _owned(tx: Transaction, view_id: int, owner_id: int) -> dict[str, Any]:
    record = tx.get(BUCKET_VIEWS, view_id)
    if record is None or record["owner_id"] != owner_id:
        raise NotFoundError("view")
    return record


def update_view(store: Store, owner_id: int, view_id: int, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (record, previous values) -- the previous values are the undo."""
    with store.transaction() as tx:
        record = _owned(tx, view_id, owner_id)
        if record.get("deleted_at") is not None:
            raise NotFoundError("view")
        merged = clean({**record, **raw})
        previous = {field: record.get(field) for field, value in merged.items() if record.get(field) != value}
        record.update(merged)
        record["updated_at"] = to_iso(utc_now())
        tx.put(BUCKET_VIEWS, view_id, record)
        return record, previous


def reorder_views(store: Store, owner_id: int, ids: list[int]) -> None:
    with store.transaction() as tx:
        for position, view_id in enumerate(ids, start=1):
            record = tx.get(BUCKET_VIEWS, view_id)
            if record is not None and record["owner_id"] == owner_id:
                record["position"] = position
                tx.put(BUCKET_VIEWS, view_id, record)


def delete_view(store: Store, owner_id: int, view_id: int, actor_id: int) -> None:
    with store.transaction() as tx:
        record = _owned(tx, view_id, owner_id)
        mark_deleted(record, actor_id)
        tx.put(BUCKET_VIEWS, view_id, record)


def restore_view(store: Store, owner_id: int, view_id: int, actor_id: int, actor_is_admin: bool) -> dict[str, Any]:
    with store.transaction() as tx:
        record = _owned(tx, view_id, owner_id)
        unmark_deleted(record, actor_id, actor_is_admin)
        tx.put(BUCKET_VIEWS, view_id, record)
        return record


def purge_deleted_views(store: Store) -> int:
    return store.delete_where(BUCKET_VIEWS, lambda _key, record: deleted_long_ago(record))


def delete_for_user_tx(tx: Transaction, user_id: int) -> int:
    return tx.delete_where(BUCKET_VIEWS, lambda _key, record: record["owner_id"] == user_id)
