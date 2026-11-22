"""Suggestions: a person's named lists of things they might like -- library
titles, and Discover films not in the library yet. Agents fill them over MCP
("films like Heat you have not imported"), each item with an optional note
saying why; the person imports, watches or skips from there.

The same shape as a playlist (app/models/playlists.py): one record per list,
its items in order, a title's number its place in that order, every change
answering the items as they were (the undo). An item is

    {"ref": "<title id>" | "cat:<catalogue key>", "note": str, "added_at": iso}

A Discover film that is later imported keeps its "cat:" ref: the routes find
its library title by catalogue key when they read the list.
"""
from __future__ import annotations

from typing import Any, Callable

from app.core.db import BUCKET_SUGGESTIONS, Store, Transaction
from app.media import normalize
from app.media.normalize import text
from app.models import deleted_long_ago, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models.playlists import clamp, clean_name
from app.models.revision import NotFoundError
from app.models.users import owner_id_tx

Record = dict[str, Any]
Item = dict[str, Any]

MAX_LISTS = 200
MAX_ITEMS = 2000
NOTE_LIMIT = 200
CATALOGUE = "cat:"


def film_ref(key: str) -> str:
    return CATALOGUE + key


def catalogue_key(ref: str) -> str:
    """The catalogue key of a "cat:" ref, or "" for a library title."""
    return ref[len(CATALOGUE):] if ref.startswith(CATALOGUE) else ""


def valid_ref(ref: object) -> bool:
    if not isinstance(ref, str):
        return False
    if ref.startswith(CATALOGUE):
        return 0 < len(ref) - len(CATALOGUE) <= 300
    return normalize.valid_title_id(ref)


def clean_note(raw: object) -> str:
    return text(raw, NOTE_LIMIT)


def clean_items(raw: object) -> list[Item]:
    """Items as given (an undo sends them back whole), each ref once. A bare
    ref string is an item with no note."""
    if not isinstance(raw, list):
        return []
    out: dict[str, Item] = {}
    now = to_iso(utc_now())
    for entry in raw:
        if isinstance(entry, str):
            entry = {"ref": entry}
        if not isinstance(entry, dict) or not valid_ref(entry.get("ref")) or entry["ref"] in out:
            continue
        out[entry["ref"]] = {"ref": entry["ref"], "note": clean_note(entry.get("note")), "added_at": text(entry.get("added_at"), 40) or now}
    return list(out.values())


def refs(record: Record) -> list[str]:
    return [item["ref"] for item in record["items"]]


def _mine(tx: Transaction, owner_id: int) -> list[Record]:
    return [record for _key, record in tx.all(BUCKET_SUGGESTIONS) if record["owner_id"] == owner_id and record.get("deleted_at") is None]


def list_lists(store: Store, owner_id: int) -> list[Record]:
    rows = [record for _key, record in store.all(BUCKET_SUGGESTIONS) if record["owner_id"] == owner_id and record.get("deleted_at") is None]
    return sorted(rows, key=lambda record: (record.get("position", 0), record["id"]))


def create_tx(tx: Transaction, owner_id: int, name: str, items: list[Item]) -> Record:
    mine = _mine(tx, owner_id)
    if len(mine) >= MAX_LISTS:
        raise ValueError("too many suggestion lists")
    ident = tx.next_sequence(BUCKET_SUGGESTIONS)
    now = to_iso(utc_now())
    record = {
        "id": ident,
        "owner_id": owner_id,
        "name": name,
        "items": items[:MAX_ITEMS],
        "position": max((record.get("position", 0) for record in mine), default=0) + 1,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "deleted_by": None,
    }
    tx.put(BUCKET_SUGGESTIONS, ident, record)
    return record


def create_list(store: Store, owner_id: int, name: object, items: object = None) -> Record:
    cleaned = clean_name(name)
    with store.transaction() as tx:
        return create_tx(tx, owner_id, cleaned, clean_items(items))


def _owned(tx: Transaction, list_id: int, owner_id: int, live: bool = True) -> Record:
    record = tx.get(BUCKET_SUGGESTIONS, list_id)
    if record is None or record["owner_id"] != owner_id or (live and record.get("deleted_at") is not None):
        raise NotFoundError("suggestion list")
    return record


def _save(tx: Transaction, record: Record) -> Record:
    record["updated_at"] = to_iso(utc_now())
    tx.put(BUCKET_SUGGESTIONS, record["id"], record)
    return record


def rename_list(store: Store, owner_id: int, list_id: int, name: object) -> tuple[Record, str]:
    cleaned = clean_name(name)
    with store.transaction() as tx:
        record = _owned(tx, list_id, owner_id)
        old = record["name"]
        record["name"] = cleaned
        return _save(tx, record), old


def reorder_lists(store: Store, owner_id: int, ids: list[int]) -> None:
    with store.transaction() as tx:
        for position, list_id in enumerate(ids, start=1):
            record = tx.get(BUCKET_SUGGESTIONS, list_id)
            if record is not None and record["owner_id"] == owner_id:
                record["position"] = position
                tx.put(BUCKET_SUGGESTIONS, list_id, record)


def delete_list(store: Store, owner_id: int, list_id: int, actor_id: int) -> None:
    with store.transaction() as tx:
        record = _owned(tx, list_id, owner_id, live=False)
        mark_deleted(record, actor_id)
        tx.put(BUCKET_SUGGESTIONS, list_id, record)


def restore_list(store: Store, owner_id: int, list_id: int, actor_id: int, actor_is_admin: bool) -> Record:
    with store.transaction() as tx:
        record = _owned(tx, list_id, owner_id, live=False)
        unmark_deleted(record, actor_id, actor_is_admin, owner_id_tx(tx))
        tx.put(BUCKET_SUGGESTIONS, list_id, record)
        return record


# -- items --------------------------------------------------------------------


def _change_items(store: Store, owner_id: int, list_id: int, change: Callable[[list[Item]], list[Item]]) -> tuple[Record, list[Item]]:
    with store.transaction() as tx:
        record = _owned(tx, list_id, owner_id)
        before = [dict(item) for item in record["items"]]
        after = change([dict(item) for item in before])
        if after == before:
            return record, before
        if len(after) > MAX_ITEMS:
            raise ValueError("that suggestion list is full")
        record["items"] = after
        return _save(tx, record), before


def add_items(store: Store, owner_id: int, list_id: int, wanted: list[str], note: object = None,
              position: object = None, same: Callable[[str], set[str]] | None = None) -> tuple[Record, list[Item]]:
    """Put refs in at a 1-based position (the end by default). A ref already
    there -- itself, or one `same` says is the same film (a library title and
    its catalogue key) -- stays where it is; a note given replaces its note."""
    cleaned_note = clean_note(note)
    wanted = list(dict.fromkeys(ref for ref in wanted if valid_ref(ref)))

    def change(items: list[Item]) -> list[Item]:
        at_ref = {item["ref"]: item for item in items}
        now = to_iso(utc_now())
        new: list[Item] = []
        for ref in wanted:
            matches = {ref} | (same(ref) if same else set())
            existing = next((at_ref[other] for other in matches if other in at_ref), None)
            if existing is not None:
                if cleaned_note:
                    existing["note"] = cleaned_note
                continue
            new.append({"ref": ref, "note": cleaned_note, "added_at": now})
            at_ref[ref] = new[-1]
        at = len(items) if position is None else clamp(position, len(items) + 1) - 1
        return items[:at] + new + items[at:]

    return _change_items(store, owner_id, list_id, change)


def remove_items(store: Store, owner_id: int, list_id: int, doomed_refs: object) -> tuple[Record, list[Item]]:
    doomed = {ref for ref in (doomed_refs if isinstance(doomed_refs, list) else []) if isinstance(ref, str)}
    return _change_items(store, owner_id, list_id, lambda items: [item for item in items if item["ref"] not in doomed])


def move_item(store: Store, owner_id: int, list_id: int, ref: object, position: object) -> tuple[Record, list[Item]]:
    def change(items: list[Item]) -> list[Item]:
        at = next((index for index, item in enumerate(items) if item["ref"] == ref), None)
        if at is None:
            raise NotFoundError("item in this suggestion list")
        item = items.pop(at)
        items.insert(clamp(position, len(items) + 1) - 1, item)
        return items

    return _change_items(store, owner_id, list_id, change)


def set_note(store: Store, owner_id: int, list_id: int, ref: object, note: object) -> tuple[Record, list[Item]]:
    cleaned = clean_note(note)

    def change(items: list[Item]) -> list[Item]:
        for item in items:
            if item["ref"] == ref:
                item["note"] = cleaned
                return items
        raise NotFoundError("item in this suggestion list")

    return _change_items(store, owner_id, list_id, change)


def set_items(store: Store, owner_id: int, list_id: int, items: object) -> tuple[Record, list[Item]]:
    """The whole list at once -- what an undo puts back."""
    wanted = clean_items(items)
    return _change_items(store, owner_id, list_id, lambda _items: wanted)


# -- keeping lists in step with titles ----------------------------------------


def forget_titles_tx(tx: Transaction, doomed: set[str]) -> None:
    for key, record in tx.all(BUCKET_SUGGESTIONS):
        if any(item["ref"] in doomed for item in record["items"]):
            record["items"] = [item for item in record["items"] if item["ref"] not in doomed]
            tx.put(BUCKET_SUGGESTIONS, key, record)


def merge_titles_tx(tx: Transaction, keep_id: str, drop_ids: list[str]) -> dict[int, list[Item]]:
    """Merged copies become the kept title, in the place of whichever came
    first. Returns {list id: items before} for the merge's undo."""
    dropped = set(drop_ids)
    before: dict[int, list[Item]] = {}
    for key, record in tx.all(BUCKET_SUGGESTIONS):
        if not any(item["ref"] in dropped for item in record["items"]):
            continue
        before[key] = [dict(item) for item in record["items"]]
        merged: dict[str, Item] = {}
        for item in record["items"]:
            ref = keep_id if item["ref"] in dropped else item["ref"]
            if ref not in merged:
                merged[ref] = {**item, "ref": ref}
        record["items"] = list(merged.values())
        tx.put(BUCKET_SUGGESTIONS, key, record)
    return before


def restore_items_tx(tx: Transaction, items_by_list: dict[Any, list[Item]]) -> None:
    for key, items in items_by_list.items():
        record = tx.get(BUCKET_SUGGESTIONS, int(key))
        if record is not None:
            record["items"] = items
            tx.put(BUCKET_SUGGESTIONS, record["id"], record)


def delete_for_user_tx(tx: Transaction, user_id: int) -> int:
    return tx.delete_where(BUCKET_SUGGESTIONS, lambda _key, record: record["owner_id"] == user_id)


def purge_deleted_lists(store: Store) -> int:
    return store.delete_where(BUCKET_SUGGESTIONS, lambda _key, record: deleted_long_ago(record))
