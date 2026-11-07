"""Per-person settings that should follow them from phone to laptop: how
cards look on each screen, the last query on each screen of the library, and
which saved view a screen opens with.

One record per user. Each section is replaced whole when written, which is
what the client sends anyway, and keeps two devices from interleaving half
a card layout each.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.db import BUCKET_PREFS, Store
from app.models import to_iso, utc_now

SECTIONS = ("cards", "last_query", "default_view", "ui")
# A prefs record is UI state, not content: bounded so a buggy client cannot
# grow it without limit.
MAX_SECTION_BYTES = 64 * 1024


def get_prefs(store: Store, user_id: int) -> dict[str, Any]:
    record = store.get(BUCKET_PREFS, user_id) or {}
    return {section: record.get(section, {}) for section in SECTIONS}


def save_prefs(store: Store, user_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    """changes is {section: {key: value}}; each key given replaces that key
    within its section, and a None value removes it."""
    for section, values in changes.items():
        if section not in SECTIONS or not isinstance(values, dict):
            raise ValueError(f"unknown prefs section {section!r}")
        if len(json.dumps(values)) > MAX_SECTION_BYTES:
            raise ValueError(f"prefs section {section!r} is too large")

    def mutate(record: dict[str, Any]) -> None:
        for section, values in changes.items():
            current = record.setdefault(section, {})
            for name, value in values.items():
                if value is None:
                    current.pop(str(name), None)
                else:
                    current[str(name)] = value
        record["updated_at"] = to_iso(utc_now())

    with store.transaction() as tx:
        record = tx.get(BUCKET_PREFS, user_id) or {}
        mutate(record)
        tx.put(BUCKET_PREFS, user_id, record)
    return get_prefs(store, user_id)


def delete_for_user_tx(tx: Any, user_id: int) -> None:
    tx.delete(BUCKET_PREFS, user_id)
