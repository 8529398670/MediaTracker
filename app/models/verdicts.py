"""Discover verdicts: what one person has said about a film in the
catalogue that is not in the library -- "skip" (not interested, stop showing
it), "seen" (watched it, before this app). One record per person, read in
one get, because the Discover query needs all of them at once.
"""
from __future__ import annotations

from typing import Any

from app.core.db import BUCKET_VERDICTS, Store, Transaction
from app.media.normalize import text
from app.models import to_iso, utc_now
from app.models.revision import ConflictError

VERDICTS = ("skip", "seen")


def get_verdicts(store: Store, user_id: int) -> dict[str, dict[str, Any]]:
    return (store.get(BUCKET_VERDICTS, user_id) or {}).get("keys", {})


def set_verdict(store: Store, user_id: int, catalogue_key: str, verdict: str | None, expect: object = ...) -> str | None:
    """Set or clear (None) one verdict. Returns the verdict it replaced.
    expect, when given, is the verdict the caller believes is there."""
    catalogue_key = text(catalogue_key, 300)
    if not catalogue_key:
        raise ValueError("no catalogue key")
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    with store.transaction() as tx:
        record = tx.get(BUCKET_VERDICTS, user_id) or {"keys": {}}
        previous = (record["keys"].get(catalogue_key) or {}).get("v")
        if expect is not ... and expect != previous:
            raise ConflictError({"verdict": previous})
        if verdict is None:
            record["keys"].pop(catalogue_key, None)
        else:
            record["keys"][catalogue_key] = {"v": verdict, "at": to_iso(utc_now())}
        tx.put(BUCKET_VERDICTS, user_id, record)
        return previous


def put_all_tx(tx: Transaction, user_id: int, keys: dict[str, dict[str, Any]]) -> None:
    tx.put(BUCKET_VERDICTS, user_id, {"keys": keys})


def delete_for_user_tx(tx: Transaction, user_id: int) -> None:
    tx.delete(BUCKET_VERDICTS, user_id)
