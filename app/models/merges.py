"""Merging duplicates: fold several titles into the one being kept.

The kept title gains every tag, link and note and any detail it lacked;
each person's states for all the copies fold into one state on the kept title
(dupes.merged_state); the others are soft-deleted with merged_into pointing
at it. All of that happens in one transaction, and a snapshot of everything
it touched is stored, so the whole merge can be undone as one step.

"These are not duplicates" is remembered here too, shared by the family, so
the same pair is not offered again on any device.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.core.db import BUCKET_DUPE_DISMISSALS, BUCKET_MERGES, BUCKET_TITLES, BUCKET_USER_STATE, Store
from app.media import dupes
from app.models import playlists, to_iso, utc_now
from app.models.revision import ConflictError, NotFoundError, bump
from app.models.titles import delete_title_tx
from app.models.user_state import key as state_key


def merge(store: Store, keep_id: str, drop_ids: list[str], actor_id: int | None) -> dict[str, Any]:
    drop_ids = [ident for ident in dict.fromkeys(drop_ids) if ident != keep_id]
    if not drop_ids:
        raise ValueError("nothing to merge into it")
    with store.transaction() as tx:
        keep = tx.get(BUCKET_TITLES, keep_id)
        if keep is None or keep.get("deleted_at") is not None:
            raise NotFoundError()
        others = []
        for ident in drop_ids:
            record = tx.get(BUCKET_TITLES, ident)
            if record is None or record.get("deleted_at") is not None:
                raise NotFoundError()
            others.append(record)

        involved = {keep_id, *drop_ids}
        states_by_user: dict[int, dict[str, dict[str, Any]]] = {}
        states_before: dict[str, Any] = {}
        for key, state in tx.all(BUCKET_USER_STATE):
            if state.get("title_id") in involved:
                states_by_user.setdefault(state["user_id"], {})[state["title_id"]] = state
                states_before[key] = dict(state)

        rev = bump(tx)
        keep_before = dict(keep)
        changes = dupes.merged_title_fields(keep, others)
        keep.update(changes)
        keep["updated_at"] = to_iso(utc_now())
        keep["updated_by"] = actor_id
        keep["rev"] = rev
        tx.put(BUCKET_TITLES, keep_id, keep)

        for user_id, by_title in states_by_user.items():
            folded = dupes.merged_state(list(by_title.values()))
            target = by_title.get(keep_id) or {"user_id": user_id, "title_id": keep_id}
            target.update(folded)
            target["updated_at"] = to_iso(utc_now())
            target["updated_by"] = actor_id
            target["rev"] = rev
            tx.put(BUCKET_USER_STATE, state_key(user_id, keep_id), target)
            for ident in by_title:
                if ident != keep_id:
                    tx.delete(BUCKET_USER_STATE, state_key(user_id, ident))
            if keep_id not in by_title:
                states_before[state_key(user_id, keep_id)] = None

        for ident in drop_ids:
            delete_title_tx(tx, ident, actor_id, rev, merged_into=keep_id)

        merge_id = uuid.uuid4().hex
        tx.put(
            BUCKET_MERGES,
            merge_id,
            {
                "id": merge_id,
                "keep_id": keep_id,
                "keep_before": keep_before,
                "keep_after_rev": rev,
                "drop_ids": drop_ids,
                "states_before": states_before,
                "playlists_before": playlists.merge_titles_tx(tx, keep_id, drop_ids),
                "by": actor_id,
                "at": to_iso(utc_now()),
                "undone": False,
            },
        )
        return {"merge_id": merge_id, "title": keep, "changed": sorted(changes)}


def undo_merge(store: Store, merge_id: str) -> dict[str, Any]:
    """Put everything back as it was before the merge -- refused (409) if the
    kept title was edited since, because that edit would be lost."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_MERGES, merge_id)
        if record is None or record.get("undone"):
            raise NotFoundError("merge")
        keep = tx.get(BUCKET_TITLES, record["keep_id"])
        if keep is None or keep.get("rev") != record["keep_after_rev"]:
            raise ConflictError(keep)
        rev = bump(tx)
        before = dict(record["keep_before"])
        before["rev"] = rev
        tx.put(BUCKET_TITLES, record["keep_id"], before)
        for ident in record["drop_ids"]:
            title = tx.get(BUCKET_TITLES, ident)
            if title is not None:
                title.update({"deleted_at": None, "deleted_by": None, "merged_into": None, "rev": rev})
                tx.put(BUCKET_TITLES, ident, title)
        for key, state in record["states_before"].items():
            if state is None:
                tx.delete(BUCKET_USER_STATE, key)
            else:
                state["rev"] = rev
                tx.put(BUCKET_USER_STATE, key, state)
        playlists.restore_items_tx(tx, record.get("playlists_before") or {})
        record["undone"] = True
        tx.put(BUCKET_MERGES, merge_id, record)
        return before


def dismissed_pairs(store: Store) -> set[str]:
    return {str(key) for key, _record in store.all(BUCKET_DUPE_DISMISSALS)}


def dismiss(store: Store, ids: list[str], actor_id: int | None) -> list[str]:
    """Remember that these titles are not the same work. Returns the pair
    keys written, which are also what an undo removes."""
    written = []
    with store.transaction() as tx:
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                pair = dupes.pair_key(a, b)
                if tx.get(BUCKET_DUPE_DISMISSALS, pair) is None:
                    tx.put(BUCKET_DUPE_DISMISSALS, pair, {"by": actor_id, "at": to_iso(utc_now())})
                    written.append(pair)
    return written


def undismiss(store: Store, pairs: list[str]) -> None:
    with store.transaction() as tx:
        for pair in pairs:
            tx.delete(BUCKET_DUPE_DISMISSALS, pair)
