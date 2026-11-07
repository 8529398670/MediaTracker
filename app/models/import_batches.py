"""What one import added, so the whole import can be undone in one step:
the titles it created are soft-deleted again, and the states it set for the
importer are removed."""
from __future__ import annotations

import uuid
from typing import Any

from app.core.db import BUCKET_IMPORT_BATCHES, BUCKET_TITLES, BUCKET_USER_STATE, Store
from app.models import to_iso, utc_now
from app.models.revision import NotFoundError, bump
from app.models.titles import delete_title_tx
from app.models.user_state import key as state_key


def new_batch_id() -> str:
    return uuid.uuid4().hex


def record_created(store: Store, batch_id: str, user_id: int, title_ids: list[str], actor_id: int | None) -> None:
    with store.transaction() as tx:
        record = tx.get(BUCKET_IMPORT_BATCHES, batch_id) or {"id": batch_id, "user_id": user_id, "title_ids": [], "by": actor_id, "at": to_iso(utc_now()), "undone": False}
        record["title_ids"] = list(dict.fromkeys([*record["title_ids"], *title_ids]))
        tx.put(BUCKET_IMPORT_BATCHES, batch_id, record)


def undo_batch(store: Store, batch_id: str, actor_id: int | None) -> int:
    with store.transaction() as tx:
        record = tx.get(BUCKET_IMPORT_BATCHES, batch_id)
        if record is None or record.get("undone"):
            raise NotFoundError("import")
        rev = bump(tx)
        removed = 0
        for title_id in record["title_ids"]:
            title = tx.get(BUCKET_TITLES, title_id)
            if title is not None and title.get("deleted_at") is None:
                delete_title_tx(tx, title_id, actor_id, rev)
                tx.delete(BUCKET_USER_STATE, state_key(record["user_id"], title_id))
                removed += 1
        record["undone"] = True
        tx.put(BUCKET_IMPORT_BATCHES, batch_id, record)
        return removed


def get_batch(store: Store, batch_id: str) -> dict[str, Any] | None:
    return store.get(BUCKET_IMPORT_BATCHES, batch_id)
