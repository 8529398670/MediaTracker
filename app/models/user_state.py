"""One person's relationship with one title: on their queue, watching,
watched or dropped; their rating, their heart and their private note.

Keyed "<user id>:<title id>". No record means "not on my list" -- the title
is in the family library, this person has not touched it. A record whose
status is None is the same thing with a heart or a rating left on it.

Up next has no order of its own; a hand-made order is a playlist
(playlists.py).
"""
from __future__ import annotations

from typing import Any

from app.core.db import BUCKET_TITLES, BUCKET_USER_STATE, Store, Transaction
from app.media import normalize
from app.models import to_iso, utc_now
from app.models.revision import NotFoundError, bump, check_expect

State = dict[str, Any]


def key(user_id: int, title_id: str) -> str:
    return f"{user_id}:{title_id}"


def empty(user_id: int, title_id: str) -> State:
    return {"user_id": user_id, "title_id": title_id, **normalize.STATE_EMPTY, "updated_at": None, "updated_by": None, "rev": 0}


def get_state(store: Store, user_id: int, title_id: str) -> State | None:
    return store.get(BUCKET_USER_STATE, key(user_id, title_id))


def apply_tx(
    tx: Transaction, user_id: int, title_id: str, changes: dict[str, Any], actor_id: int | None, rev: int
) -> tuple[State, dict[str, Any]]:
    """Write cleaned changes to one state inside the caller's transaction.
    Returns (state, previous values of what changed)."""
    current = tx.get(BUCKET_USER_STATE, key(user_id, title_id))
    state = current or empty(user_id, title_id)
    before = dict(state)
    state.update(changes)
    # Derived fields, so every door (a card button, a bulk action, an API
    # key, the importer) agrees on them.
    if changes.get("status") == "watched" and not state.get("watched_at") and "watched_at" not in changes:
        state["watched_at"] = to_iso(utc_now())
    previous = {field: before.get(field) for field in normalize.STATE_FIELDS if before.get(field) != state.get(field)}
    if not previous and current is not None:
        return state, {}
    state["updated_at"] = to_iso(utc_now())
    state["updated_by"] = actor_id
    state["rev"] = rev
    tx.put(BUCKET_USER_STATE, key(user_id, title_id), state)
    return state, previous


def set_state(
    store: Store, user_id: int, title_id: str, changes: dict[str, Any], expect: object, actor_id: int | None
) -> tuple[State, dict[str, Any]]:
    with store.transaction() as tx:
        title = tx.get(BUCKET_TITLES, title_id)
        if title is None or title.get("deleted_at") is not None:
            raise NotFoundError()
        current = tx.get(BUCKET_USER_STATE, key(user_id, title_id))
        check_expect(current or empty(user_id, title_id), expect)
        return apply_tx(tx, user_id, title_id, changes, actor_id, bump(tx))


def set_many(
    store: Store, user_id: int, changes_by_title: dict[str, dict[str, Any]], actor_id: int | None
) -> dict[str, dict[str, Any]]:
    """Several states at once (a bulk action, or the undo of one). Returns
    {title id: previous values}. Titles that no longer exist are skipped."""
    out: dict[str, dict[str, Any]] = {}
    with store.transaction() as tx:
        rev = bump(tx)
        for title_id, changes in changes_by_title.items():
            title = tx.get(BUCKET_TITLES, title_id)
            if title is None or title.get("deleted_at") is not None:
                continue
            _state, previous = apply_tx(tx, user_id, title_id, changes, actor_id, rev)
            if previous:
                out[title_id] = previous
    return out


def delete_for_user_tx(tx: Transaction, user_id: int) -> int:
    """Every state a person had -- for when the account itself is deleted."""
    prefix = f"{user_id}:"
    return tx.delete_where(BUCKET_USER_STATE, lambda state_key, _state: isinstance(state_key, str) and state_key.startswith(prefix))
