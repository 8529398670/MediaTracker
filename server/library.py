"""The library file: one JSON document on a mounted volume.

Every read and write goes through `Library`, which owns the lock, the
revision counter, the tombstones and the rolling backups. `LIBRARY` at the
foot of this module is the single instance the rest of the app shares.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import seed
from config import (BACKUP_DIR, BACKUP_EVERY, BACKUP_KEEP, DATA_DIR,
                    LIBRARY_PATH, MAX_ITEMS, MAX_SOURCES, SCHEMA,
                    TOMBSTONE_DAYS, log, now_iso)
from normalize import _int, _iso, _s, normalize_item, normalize_source, normalize_types


# --------------------------------------------------------------------------
# the library file
# --------------------------------------------------------------------------


class Library:
    """One JSON document, guarded by a lock and written atomically.

    ``rev`` increments on every write.  Clients send the revision they based
    their edit on; a mismatch is a 409 and the client merges and retries.
    Deletions leave tombstones so a delete on one device survives a sync
    from another; they are purged after TOMBSTONE_DAYS.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._last_backup = 0.0
        self.data = self._blank()
        self._load()

    @staticmethod
    def _blank() -> dict:
        return {"schema": SCHEMA, "rev": 0, "updatedAt": now_iso(),
                "items": [], "sources": [], "seeds": {}}

    def _load(self) -> None:
        if not self.path.exists():
            log(f"no library at {self.path} — starting a new one")
            self._write(self.data)
            return
        try:
            raw = json.loads(self.path.read_text("utf-8") or "{}")
        except (OSError, ValueError) as exc:
            broken = self.path.with_suffix(f".corrupt-{int(time.time())}.json")
            log(f"!! library is unreadable ({exc}); moving it to {broken.name}")
            try:
                self.path.replace(broken)
            except OSError:
                pass
            self.data = self._blank()
            self._write(self.data)
            return

        now = now_iso()
        items = [i for i in (normalize_item(i, now) for i in raw.get("items") or []) if i]
        sources = [s for s in (normalize_source(s, now) for s in raw.get("sources") or []) if s]
        seeds = raw.get("seeds")
        types = normalize_types(raw.get("types"))
        self.data = {
            "schema": SCHEMA,
            "rev": _int(raw.get("rev"), 0, 2**62) or 0,
            "updatedAt": _iso(raw.get("updatedAt"), now),
            "items": items,
            "sources": sources,
            "seeds": seeds if isinstance(seeds, dict) else {},
        }
        # Absent until the app first writes it: until then the app shows its
        # own starting list, and the providers go by the built-in types.
        if types:
            self.data["types"] = types
        self._purge_tombstones()
        log(f"loaded {len(items)} items, {len(sources)} sources (rev {self.data['rev']})")

    def _purge_tombstones(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_DAYS)).isoformat()
        keep = []
        for item in self.data["items"]:
            if item.get("deleted") and (item.get("deletedAt") or "") < cutoff:
                continue
            keep.append(item)
        self.data["items"] = keep

    def _backup(self) -> None:
        if not self.path.exists():
            return
        if time.time() - self._last_backup < BACKUP_EVERY:
            return
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            (BACKUP_DIR / f"library-{stamp}.json").write_bytes(self.path.read_bytes())
            self._last_backup = time.time()
            old = sorted(BACKUP_DIR.glob("library-*.json"))
            for stale in old[:-BACKUP_KEEP]:
                stale.unlink(missing_ok=True)
        except OSError as exc:
            log(f"backup skipped: {exc}")

    def _write(self, data: dict) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._backup()
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def _commit(self) -> dict:
        self.data["rev"] += 1
        self.data["updatedAt"] = now_iso()
        self._write(self.data)
        return self.data

    # -- reads ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def lookup_for(self, type_id: str) -> str | None:
        """What one of Other's types is looked up as, when the library's own
        list names it. None for a type the list does not have."""
        for entry in self.data.get("types") or []:
            if entry["id"] == type_id:
                return entry["lookup"]
        return None

    def meta(self) -> dict:
        with self.lock:
            live = [i for i in self.data["items"] if not i.get("deleted")]
            return {
                "rev": self.data["rev"],
                "updatedAt": self.data["updatedAt"],
                "items": len(live),
                "sources": len(self.data["sources"]),
            }

    # -- writes --------------------------------------------------------

    def replace(self, payload: dict) -> tuple[bool, dict]:
        """Whole-document write with optimistic concurrency."""
        with self.lock:
            base = payload.get("rev")
            if not payload.get("force") and isinstance(base, int) and base != self.data["rev"]:
                return False, {"error": "conflict", "rev": self.data["rev"],
                               "library": self.snapshot()}
            now = now_iso()
            items = [i for i in (normalize_item(i, now) for i in payload.get("items") or []) if i]
            if len(items) > MAX_ITEMS:
                return False, {"error": "too_many_items", "limit": MAX_ITEMS}
            sources = payload.get("sources")
            if sources is not None:
                clean = [s for s in (normalize_source(s, now) for s in sources) if s]
                self.data["sources"] = clean[:MAX_SOURCES]
            # An older page sends no list, and an empty one is never meant:
            # either way the list already here stands.
            types = normalize_types(payload.get("types"))
            if types:
                self.data["types"] = types
            self.data["items"] = items
            return True, self._commit()

    def upsert(self, raw: dict) -> dict | None:
        with self.lock:
            item = normalize_item(raw)
            if item is None:
                return None
            for index, existing in enumerate(self.data["items"]):
                if existing["id"] == item["id"]:
                    self.data["items"][index] = item
                    break
            else:
                self.data["items"].append(item)
            self._commit()
            return item

    def patch(self, item_id: str, fields: dict) -> dict | None:
        with self.lock:
            for index, existing in enumerate(self.data["items"]):
                if existing["id"] == item_id:
                    merged = dict(existing)
                    merged.update(fields)
                    merged["id"] = item_id
                    merged["updatedAt"] = now_iso()
                    item = normalize_item(merged)
                    if item is None:
                        return None
                    self.data["items"][index] = item
                    self._commit()
                    return item
        return None

    # -- seeding -------------------------------------------------------

    def _merge(self, parsed: dict) -> dict:
        """Fold parsed titles in without doubling anything.

        A title that is already here is not skipped outright: links, tags, a
        missing year and a watched tick are folded into the entry that
        exists.  That is the move-between-documents step, done for you.
        """
        now = now_iso()
        report = {"added": 0, "merged": 0, "skipped": 0, "sources": 0}

        exact: dict[str, dict] = {}
        loose: dict[str, dict] = {}
        for item in self.data["items"]:
            if item.get("deleted"):
                continue
            exact.setdefault(seed.title_key(item["title"], item.get("year")), item)
            loose.setdefault(seed.title_key(item["title"]), item)

        for raw in parsed.get("items") or []:
            match = exact.get(seed.title_key(raw["title"], raw.get("year")))
            if match is None and not raw.get("year"):
                # A title with no year still matches one that has one.
                match = loose.get(seed.title_key(raw["title"]))

            if match is not None:
                touched = False
                for link in raw.get("links") or []:
                    if not any(l["url"] == link["url"] for l in match["links"]):
                        match["links"].append({"label": _s(link.get("label"), 120),
                                               "url": link["url"]})
                        touched = True
                for tag in raw.get("tags") or []:
                    if tag not in match["tags"]:
                        match["tags"].append(tag)
                        touched = True
                if not match.get("year") and raw.get("year"):
                    match["year"] = raw["year"]
                    touched = True
                if raw.get("status") == "watched" and match["status"] != "watched":
                    match["status"] = "watched"
                    match["watchedAt"] = match.get("watchedAt") or now
                    touched = True
                if touched:
                    match["updatedAt"] = now
                    report["merged"] += 1
                else:
                    report["skipped"] += 1
                continue

            item = normalize_item({
                **raw,
                "addedAt": now,
                "updatedAt": now,
                "watchedAt": now if raw.get("status") == "watched" else None,
            }, now)
            if item is None:
                continue
            self.data["items"].append(item)
            exact.setdefault(seed.title_key(item["title"], item.get("year")), item)
            loose.setdefault(seed.title_key(item["title"]), item)
            report["added"] += 1

        known = {s["url"] for s in self.data["sources"]}
        for raw in parsed.get("sources") or []:
            if raw["url"] in known:
                continue
            source = normalize_source({**raw, "addedAt": now}, now)
            if source is None:
                continue
            self.data["sources"].append(source)
            known.add(source["url"])
            report["sources"] += 1

        return report

    def _drop_placeholders(self) -> int:
        """`asdf` holds a spot open in a document; it is not a title."""
        stamp = now_iso()
        dropped = 0
        for index, item in enumerate(self.data["items"]):
            if item.get("deleted") or not seed.is_placeholder(item.get("title", "")):
                continue
            # A tombstone rather than a removal, so a phone still holding the
            # old copy does not push it back on the next sync.
            self.data["items"][index] = {
                **item, "deleted": True, "deletedAt": stamp, "updatedAt": stamp,
            }
            dropped += 1
        return dropped

    def seed_from(self, directory: Path) -> None:
        """Import every .md sitting in *directory*, once per version of it.

        The hash of each file is remembered, so a restart is free and an
        edited document is picked up the next time the server starts.
        """
        with self.lock:
            ledger = self.data.setdefault("seeds", {})
            files = seed.seed_files(directory)
            if not files:
                log(f"seed: no .md files in {directory}")
            changed = False

            for path in files:
                try:
                    text = path.read_text("utf-8", errors="replace")
                except OSError as exc:
                    log(f"seed: cannot read {path.name} ({exc})")
                    continue
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if (ledger.get(path.name) or {}).get("hash") == digest:
                    continue

                opts = seed.defaults_for(path.name)
                parsed = seed.parse_outline(text, type=opts["type"], status=opts["status"])
                report = self._merge(parsed)
                ledger[path.name] = {"hash": digest, "at": now_iso(),
                                     "titles": len(parsed["items"]), **report}
                changed = True
                log(f"seed: {path.name} [{opts['type']}/{opts['status']}] — "
                    f"{report['added']} new, {report['merged']} merged, "
                    f"{report['skipped']} unchanged, {report['sources']} source links"
                    + (f", {parsed['placeholders']} placeholders ignored"
                       if parsed["placeholders"] else ""))

            dropped = self._drop_placeholders()
            if dropped:
                log(f"seed: removed {dropped} placeholder titles already in the library")
                changed = True

            if changed:
                self._commit()

    def patch_many(self, patches: dict[str, dict]) -> int:
        """Apply a batch of field updates in one write.

        Enrichment touches hundreds of titles; committing each one separately
        would rewrite the whole document hundreds of times.
        """
        if not patches:
            return 0
        with self.lock:
            index = {item["id"]: at for at, item in enumerate(self.data["items"])}
            now = now_iso()
            changed = 0
            for item_id, fields in patches.items():
                at = index.get(item_id)
                if at is None:
                    continue
                merged = {**self.data["items"][at], **fields,
                          "id": item_id, "updatedAt": now}
                clean = normalize_item(merged, now)
                if clean is None:
                    continue
                self.data["items"][at] = clean
                changed += 1
            if changed:
                self._commit()
            return changed

    def delete(self, item_id: str, hard: bool = False) -> bool:
        with self.lock:
            for index, existing in enumerate(self.data["items"]):
                if existing["id"] == item_id:
                    if hard:
                        self.data["items"].pop(index)
                    else:
                        stamp = now_iso()
                        self.data["items"][index] = {
                            **existing, "deleted": True,
                            "deletedAt": stamp, "updatedAt": stamp,
                        }
                    self._commit()
                    return True
        return False


LIBRARY = Library(LIBRARY_PATH)
