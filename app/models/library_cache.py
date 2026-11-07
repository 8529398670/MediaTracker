"""The library, held in memory between writes.

Records are encrypted, so "every title" means decrypting every row. Doing
that on each request would be wasteful when the library changes a few times
an hour, so the process keeps one snapshot and rebuilds it only when
meta.library_rev has moved -- one small read per request to find out. The rev
lives in the database, so a write from another process (`manage`, the
importer) invalidates this one's snapshot just the same.

The snapshot is read-only to its callers: they get the same dicts every
request until the next rebuild, so nothing may mutate them.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.db import BUCKET_TITLES, BUCKET_TYPES, BUCKET_USER_STATE, Store
from app.models import revision


@dataclass
class Snapshot:
    rev: int
    titles: dict[str, dict[str, Any]]
    # user id -> title id -> state
    states: dict[int, dict[str, dict[str, Any]]]
    types: list[dict[str, Any]]
    # title id -> who has watched / is watching / loved / rated it.
    social: dict[str, dict[str, Any]] = field(default_factory=dict)

    def live_titles(self) -> list[dict[str, Any]]:
        return [title for title in self.titles.values() if title.get("deleted_at") is None]

    def states_for(self, user_id: int) -> dict[str, dict[str, Any]]:
        return self.states.get(user_id, {})


_lock = threading.Lock()
_snapshots: dict[str, Snapshot] = {}


def build(store: Store) -> Snapshot:
    rev = revision.current(store)
    titles = {record["id"]: record for _key, record in store.all(BUCKET_TITLES)}
    states: dict[int, dict[str, dict[str, Any]]] = {}
    social: dict[str, dict[str, Any]] = {}
    for _key, state in store.all(BUCKET_USER_STATE):
        user_id, title_id = state["user_id"], state["title_id"]
        states.setdefault(user_id, {})[title_id] = state
        entry = social.setdefault(title_id, {"watched": [], "watching": [], "queued": [], "loved": [], "ratings": {}})
        status = state.get("status")
        if status == "watched":
            entry["watched"].append(user_id)
        elif status == "watching":
            entry["watching"].append(user_id)
        elif status == "queue":
            entry["queued"].append(user_id)
        if state.get("heart"):
            entry["loved"].append(user_id)
        if state.get("rating"):
            entry["ratings"][str(user_id)] = state["rating"]
    types = sorted((record for _key, record in store.all(BUCKET_TYPES) if record.get("deleted_at") is None), key=lambda t: (t.get("position", 0), t["id"]))
    return Snapshot(rev=rev, titles=titles, states=states, types=types, social=social)


def get(store: Store) -> Snapshot:
    """The current snapshot, rebuilt if anything was written since."""
    rev = revision.current(store)
    cache_key = str(store.path)
    snapshot = _snapshots.get(cache_key)
    if snapshot is not None and snapshot.rev == rev:
        return snapshot
    with _lock:
        snapshot = _snapshots.get(cache_key)
        if snapshot is not None and snapshot.rev == revision.current(store):
            return snapshot
        snapshot = build(store)
        _snapshots[cache_key] = snapshot
        return snapshot
