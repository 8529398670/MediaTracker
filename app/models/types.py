"""Media types: Movies and TV, plus whatever the family adds ("Radio drama",
"Audiobook", "Stand-up"). Each type is a section of the library with its own
sidebar entry, and says what it is looked up as when a title is added
(lookup: one of normalize.LOOKUP_KINDS).

Movies and TV are built in: they can be renamed but not deleted. A type
still holding titles cannot be deleted either unless the titles are moved to
another type in the same step -- otherwise they would vanish from every
section.
"""
from __future__ import annotations

from typing import Any

from app.core.db import BUCKET_TITLES, BUCKET_TYPES, Store
from app.media import normalize
from app.models import mark_deleted, to_iso, unmark_deleted, utc_now
from app.models.revision import NotFoundError, bump

BUILTIN = (
    {"id": "movie", "label": "Movies", "icon": "film", "lookup": "movie", "position": 0},
    {"id": "tv", "label": "TV", "icon": "tv", "lookup": "tv", "position": 1},
)


class TypeInUseError(Exception):
    def __init__(self, count: int) -> None:
        super().__init__(f"{count} titles still have this type -- choose where they go")
        self.count = count


class BuiltinTypeError(Exception):
    def __init__(self) -> None:
        super().__init__("Movies and TV cannot be deleted")


def ensure_builtin(store: Store) -> None:
    """Movies and TV always exist. Safe on every boot."""
    with store.transaction() as tx:
        changed = False
        for builtin in BUILTIN:
            if tx.get(BUCKET_TYPES, builtin["id"]) is None:
                tx.put(BUCKET_TYPES, builtin["id"], {**builtin, "builtin": True, "deleted_at": None, "deleted_by": None})
                changed = True
        if changed:
            bump(tx)


def list_types(store: Store) -> list[dict[str, Any]]:
    rows = [record for _key, record in store.all(BUCKET_TYPES) if record.get("deleted_at") is None]
    return sorted(rows, key=lambda record: (record.get("position", 0), record["id"]))


def save_type(store: Store, raw: dict[str, Any]) -> dict[str, Any]:
    """Create or update one type. The id never changes once made."""
    clean = normalize.clean_type(raw)
    if clean is None:
        raise ValueError("a type needs an id (a-z, 0-9, -) and a label")
    with store.transaction() as tx:
        existing = tx.get(BUCKET_TYPES, clean["id"])
        if existing is None:
            position = max((record.get("position", 0) for _key, record in tx.all(BUCKET_TYPES)), default=0) + 1
            record = {**clean, "position": position, "builtin": False, "deleted_at": None, "deleted_by": None, "created_at": to_iso(utc_now())}
        else:
            record = {**existing, **clean, "deleted_at": None, "deleted_by": None}
            if existing.get("builtin"):
                record["lookup"] = existing["lookup"]
        if isinstance(raw.get("position"), int):
            record["position"] = raw["position"]
        tx.put(BUCKET_TYPES, record["id"], record)
        bump(tx)
        return record


def delete_type(store: Store, type_id: str, reassign_to: str | None, actor_id: int | None) -> int:
    """Soft-delete a type, moving its titles to reassign_to. Returns how many
    titles moved."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_TYPES, type_id)
        if record is None or record.get("deleted_at") is not None:
            raise NotFoundError("type")
        if record.get("builtin"):
            raise BuiltinTypeError()
        holding = [(key, title) for key, title in tx.all(BUCKET_TITLES) if title.get("type") == type_id and title.get("deleted_at") is None]
        if holding and not reassign_to:
            raise TypeInUseError(len(holding))
        if reassign_to:
            target = tx.get(BUCKET_TYPES, reassign_to)
            if target is None or target.get("deleted_at") is not None or reassign_to == type_id:
                raise NotFoundError("type to move the titles to")
        rev = bump(tx)
        for title_key, title in holding:
            title["type"] = reassign_to
            title["rev"] = rev
            tx.put(BUCKET_TITLES, title_key, title)
        mark_deleted(record, actor_id)
        record["moved_titles_to"] = reassign_to
        record["moved_titles"] = [title_key for title_key, _title in holding]
        tx.put(BUCKET_TYPES, type_id, record)
        return len(holding)


def restore_type(store: Store, type_id: str, actor_id: int, actor_is_admin: bool) -> dict[str, Any]:
    """Undo of delete: the type comes back with the titles it held."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_TYPES, type_id)
        if record is None:
            raise NotFoundError("type")
        unmark_deleted(record, actor_id, actor_is_admin)
        rev = bump(tx)
        for title_key in record.pop("moved_titles", []) or []:
            title = tx.get(BUCKET_TITLES, title_key)
            if title is not None and title.get("type") == record.get("moved_titles_to"):
                title["type"] = type_id
                title["rev"] = rev
                tx.put(BUCKET_TITLES, title_key, title)
        record.pop("moved_titles_to", None)
        tx.put(BUCKET_TYPES, type_id, record)
        return record
