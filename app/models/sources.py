"""Sources: the lists and pages titles were found on -- "AFI's 100 Years...
100 Laughs", a subreddit, an Audible best-seller list. Shared, like titles,
and kept so the family can go back for more.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.core.db import BUCKET_SOURCES, Store, Transaction
from app.media import normalize
from app.models import deleted_long_ago, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models.revision import NotFoundError


def list_sources(store: Store) -> list[dict[str, Any]]:
    rows = [record for _key, record in store.all(BUCKET_SOURCES) if record.get("deleted_at") is None]
    return sorted(rows, key=lambda record: record.get("added_at") or "", reverse=True)


def create_source_tx(tx: Transaction, raw: dict[str, Any], actor_id: int | None, ident: str | None = None, added_at: str | None = None) -> dict[str, Any] | None:
    clean = normalize.clean_source(raw)
    if clean is None:
        return None
    record = {"id": ident or uuid.uuid4().hex, **clean, "added_at": added_at or to_iso(utc_now()), "added_by": actor_id, "deleted_at": None, "deleted_by": None}
    tx.put(BUCKET_SOURCES, record["id"], record)
    return record


def create_source(store: Store, raw: dict[str, Any], actor_id: int | None) -> dict[str, Any]:
    with store.transaction() as tx:
        record = create_source_tx(tx, raw, actor_id)
    if record is None:
        raise ValueError("a source needs an http(s) link")
    return record


def update_source(store: Store, source_id: str, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    with store.transaction() as tx:
        record = tx.get(BUCKET_SOURCES, source_id)
        if record is None or record.get("deleted_at") is not None:
            raise NotFoundError("source")
        clean = normalize.clean_source({**record, **raw})
        if clean is None:
            raise ValueError("a source needs an http(s) link")
        previous = {field: record.get(field) for field, value in clean.items() if record.get(field) != value}
        record.update(clean)
        tx.put(BUCKET_SOURCES, source_id, record)
        return record, previous


def delete_source(store: Store, source_id: str, actor_id: int) -> None:
    with store.transaction() as tx:
        record = tx.get(BUCKET_SOURCES, source_id)
        if record is None:
            raise NotFoundError("source")
        mark_deleted(record, actor_id)
        tx.put(BUCKET_SOURCES, source_id, record)


def restore_source(store: Store, source_id: str, actor_id: int, actor_is_admin: bool) -> dict[str, Any]:
    with store.transaction() as tx:
        record = tx.get(BUCKET_SOURCES, source_id)
        if record is None:
            raise NotFoundError("source")
        # A source is the family's, like a title: anyone may put it back.
        unmark_deleted(record, actor_id, True)
        tx.put(BUCKET_SOURCES, source_id, record)
        return record


def purge_deleted_sources(store: Store) -> int:
    return store.delete_where(BUCKET_SOURCES, lambda _key, record: deleted_long_ago(record))
