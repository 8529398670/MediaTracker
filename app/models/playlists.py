"""Playlists: a person's named, numbered lists of titles -- "Friday nights",
"Hitchcock in order", "Up next".

A playlist is one record holding its titles as an ordered list of ids. A
title's number is its place in that list, and nothing else stores a
position, so every add, remove or move renumbers the rest by itself. A title
is in a playlist at most once, and in as many playlists as you like.

Every item change returns the list as it was, which is the undo. Moves are
positional ("put it at number 3"), so two devices editing the same playlist
never overwrite each other's work with a stale copy.

They belong to one person, like saved views; an admin reaches someone
else's through ?user=. Deleting is soft and restorable for the usual undo
window.
"""
from __future__ import annotations

from typing import Any

from app.core.db import BUCKET_META, BUCKET_PLAYLISTS, BUCKET_USER_STATE, Store, Transaction
from app.media import normalize
from app.media.normalize import text
from app.models import deleted_long_ago, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models.revision import NotFoundError

Playlist = dict[str, Any]

MAX_PLAYLISTS = 200
MAX_ITEMS = 2000
MIGRATION_KEY = "migration:playlists_v1"


def clean_name(raw: object) -> str:
    name = text(raw, 80)
    if not name:
        raise ValueError("a playlist needs a name")
    return name


def clean_ids(raw: object) -> list[str]:
    """Title ids in the order given, each once."""
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(ident for ident in raw if normalize.valid_title_id(ident)))


def _mine(tx: Transaction, owner_id: int) -> list[Playlist]:
    return [record for _key, record in tx.all(BUCKET_PLAYLISTS) if record["owner_id"] == owner_id and record.get("deleted_at") is None]


def list_playlists(store: Store, owner_id: int) -> list[Playlist]:
    rows = [record for _key, record in store.all(BUCKET_PLAYLISTS) if record["owner_id"] == owner_id and record.get("deleted_at") is None]
    return sorted(rows, key=lambda record: (record.get("position", 0), record["id"]))


def create_tx(tx: Transaction, owner_id: int, name: str, items: list[str]) -> Playlist:
    mine = _mine(tx, owner_id)
    if len(mine) >= MAX_PLAYLISTS:
        raise ValueError("too many playlists")
    ident = tx.next_sequence(BUCKET_PLAYLISTS)
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
    tx.put(BUCKET_PLAYLISTS, ident, record)
    return record


def put_named_tx(tx: Transaction, owner_id: int, name: str, items: list[str]) -> Playlist:
    """Fill this person's playlist of that name, making it if need be -- so
    an import run twice refills one playlist rather than making two."""
    for record in _mine(tx, owner_id):
        if record["name"] == name:
            record["items"] = items[:MAX_ITEMS]
            return _save(tx, record)
    return create_tx(tx, owner_id, name, items)


def create_playlist(store: Store, owner_id: int, name: object, items: object = None) -> Playlist:
    cleaned = clean_name(name)
    with store.transaction() as tx:
        return create_tx(tx, owner_id, cleaned, clean_ids(items))


def _owned(tx: Transaction, playlist_id: int, owner_id: int, live: bool = True) -> Playlist:
    record = tx.get(BUCKET_PLAYLISTS, playlist_id)
    if record is None or record["owner_id"] != owner_id or (live and record.get("deleted_at") is not None):
        raise NotFoundError("playlist")
    return record


def _save(tx: Transaction, record: Playlist) -> Playlist:
    record["updated_at"] = to_iso(utc_now())
    tx.put(BUCKET_PLAYLISTS, record["id"], record)
    return record


def rename_playlist(store: Store, owner_id: int, playlist_id: int, name: object) -> tuple[Playlist, str]:
    """Returns (record, the old name) -- the old name is the undo."""
    cleaned = clean_name(name)
    with store.transaction() as tx:
        record = _owned(tx, playlist_id, owner_id)
        old = record["name"]
        record["name"] = cleaned
        return _save(tx, record), old


def reorder_playlists(store: Store, owner_id: int, ids: list[int]) -> None:
    with store.transaction() as tx:
        for position, playlist_id in enumerate(ids, start=1):
            record = tx.get(BUCKET_PLAYLISTS, playlist_id)
            if record is not None and record["owner_id"] == owner_id:
                record["position"] = position
                tx.put(BUCKET_PLAYLISTS, playlist_id, record)


def delete_playlist(store: Store, owner_id: int, playlist_id: int, actor_id: int) -> None:
    with store.transaction() as tx:
        record = _owned(tx, playlist_id, owner_id, live=False)
        mark_deleted(record, actor_id)
        tx.put(BUCKET_PLAYLISTS, playlist_id, record)


def restore_playlist(store: Store, owner_id: int, playlist_id: int, actor_id: int, actor_is_admin: bool) -> Playlist:
    with store.transaction() as tx:
        record = _owned(tx, playlist_id, owner_id, live=False)
        unmark_deleted(record, actor_id, actor_is_admin)
        tx.put(BUCKET_PLAYLISTS, playlist_id, record)
        return record


# -- items --------------------------------------------------------------------


def _change_items(store: Store, owner_id: int, playlist_id: int, change: Any) -> tuple[Playlist, list[str]]:
    """Run change(items) -> new items on one playlist. Returns (record, the
    items as they were)."""
    with store.transaction() as tx:
        record = _owned(tx, playlist_id, owner_id)
        before = list(record["items"])
        after = change(list(before))
        if after == before:
            return record, before
        if len(after) > MAX_ITEMS:
            raise ValueError("that playlist is full")
        record["items"] = after
        return _save(tx, record), before


def clamp(position: object, length: int) -> int:
    """A 1-based position someone typed, pulled into 1..length."""
    number = normalize.bounded_int(position, -1_000_000, 1_000_000)
    if number is None:
        return length
    return max(1, min(length, number))


def add_items(store: Store, owner_id: int, playlist_id: int, ids: object, position: object = None) -> tuple[Playlist, list[str]]:
    """Put titles in at a 1-based position (the end when none is given).
    Ones already in the playlist stay where they are."""
    wanted = clean_ids(ids)

    def change(items: list[str]) -> list[str]:
        new = [ident for ident in wanted if ident not in items]
        at = len(items) if position is None else clamp(position, len(items) + 1) - 1
        return items[:at] + new + items[at:]

    return _change_items(store, owner_id, playlist_id, change)


def remove_items(store: Store, owner_id: int, playlist_id: int, ids: object) -> tuple[Playlist, list[str]]:
    doomed = set(clean_ids(ids))
    return _change_items(store, owner_id, playlist_id, lambda items: [ident for ident in items if ident not in doomed])


def move_item(store: Store, owner_id: int, playlist_id: int, title_id: object, position: object) -> tuple[Playlist, list[str]]:
    """Put one title at a 1-based position; the ones between shift by one.
    A number past the end means the end, below 1 means the top."""

    def change(items: list[str]) -> list[str]:
        if title_id not in items:
            raise NotFoundError("title in this playlist")
        items.remove(title_id)
        items.insert(clamp(position, len(items) + 1) - 1, title_id)
        return items

    return _change_items(store, owner_id, playlist_id, change)


def set_items(store: Store, owner_id: int, playlist_id: int, ids: object) -> tuple[Playlist, list[str]]:
    """The whole list at once -- what an undo puts back."""
    wanted = clean_ids(ids)
    return _change_items(store, owner_id, playlist_id, lambda _items: wanted)


# -- keeping playlists in step with titles ---------------------------------------


def forget_titles_tx(tx: Transaction, doomed: set[str]) -> None:
    """Purged titles leave every playlist."""
    for key, record in tx.all(BUCKET_PLAYLISTS):
        if any(ident in doomed for ident in record["items"]):
            record["items"] = [ident for ident in record["items"] if ident not in doomed]
            tx.put(BUCKET_PLAYLISTS, key, record)


def merge_titles_tx(tx: Transaction, keep_id: str, drop_ids: list[str]) -> dict[int, list[str]]:
    """Merged copies become the kept title, in the place of whichever came
    first. Returns {playlist id: items before} for the merge's undo."""
    dropped = set(drop_ids)
    before: dict[int, list[str]] = {}
    for key, record in tx.all(BUCKET_PLAYLISTS):
        if not any(ident in dropped for ident in record["items"]):
            continue
        before[key] = list(record["items"])
        record["items"] = list(dict.fromkeys(keep_id if ident in dropped else ident for ident in record["items"]))
        tx.put(BUCKET_PLAYLISTS, key, record)
    return before


def restore_items_tx(tx: Transaction, items_by_playlist: dict[Any, list[str]]) -> None:
    for key, items in items_by_playlist.items():
        record = tx.get(BUCKET_PLAYLISTS, int(key))
        if record is not None:
            record["items"] = items
            tx.put(BUCKET_PLAYLISTS, record["id"], record)


def delete_for_user_tx(tx: Transaction, user_id: int) -> int:
    return tx.delete_where(BUCKET_PLAYLISTS, lambda _key, record: record["owner_id"] == user_id)


def purge_deleted_playlists(store: Store) -> int:
    return store.delete_where(BUCKET_PLAYLISTS, lambda _key, record: deleted_long_ago(record))


# -- the old hand-made queue order -------------------------------------------------


def migrate_queue_order(store: Store, name: str = "Up next") -> int:
    """Up next used to carry a hand-made order (a float "rank" on each
    state). Each person who had one gets it as a playlist, and the rank goes.
    Runs once; returns how many playlists it made."""
    with store.transaction() as tx:
        if tx.get(BUCKET_META, MIGRATION_KEY) is not None:
            return 0
        by_user: dict[int, list[tuple[float, str]]] = {}
        for key, state in tx.all(BUCKET_USER_STATE):
            if "rank" not in state:
                continue
            rank = state.pop("rank")
            if rank is not None and state.get("status") in ("queue", "watching"):
                by_user.setdefault(state["user_id"], []).append((float(rank), state["title_id"]))
            tx.put(BUCKET_USER_STATE, key, state)
        tx.delete_where(BUCKET_META, lambda key, _record: isinstance(key, str) and key.startswith("queue_tail:"))
        for user_id, rows in sorted(by_user.items()):
            rows.sort()
            create_tx(tx, user_id, name, [ident for _rank, ident in rows])
        tx.put(BUCKET_META, MIGRATION_KEY, {"at": to_iso(utc_now()), "made": len(by_user)})
        return len(by_user)
