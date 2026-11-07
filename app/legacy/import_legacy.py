"""`python -m app manage import-legacy <old data dir>`: the old app's library,
people and reference data, brought into this one.

The old app kept one shared status, rating, heart and queue order per title.
Here those are personal, so the old values become the owner's (halo's) own
state -- the queue order as halo's "Up next" playlist -- and everyone else
starts with an empty queue over the same titles. Every old account is recreated by name (halo as the owner/admin, the rest as
users) and gets a fresh login link -- the old links and sessions cannot carry
over, because the old app stored only their hashes.

Safe to run again: titles keep their old ids and are written over, people
are matched by name, files are copied (never moved) and replaced whole. The
database writes happen in one transaction, so a failure leaves nothing half
imported.
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.db import BUCKET_SOURCES, BUCKET_TITLES, BUCKET_TYPES, BUCKET_USER_STATE, BUCKET_USERS, Store
from app.media import normalize
from app.models import playlists, to_iso, users, utc_now
from app.models import user_state as states
from app.models import verdicts
from app.models.revision import bump
from app.models.sources import create_source_tx
from app.models.titles import build, create_title_tx
from app.models.types import ensure_builtin
from app.reference.paths import Paths

OWNER_NAME = "halo"

# The old app's own type ids, and what each is here. Anything else gets a
# label made from its id and is looked up as "other".
KNOWN_TYPES = {
    "music": ("Music", "music", "music-note-beamed"),
    "radio-drama": ("Radio drama", "other", "broadcast"),
    "audiobook": ("Audiobooks", "book", "headphones"),
    "doc": ("Documentaries", "doc", "camera-reels"),
    "stand-up-comedy": ("Stand-up comedy", "other", "mic"),
    "anime": ("Anime", "anime", "stars"),
    "book": ("Books", "book", "book"),
    "game": ("Games", "game", "controller"),
    "podcast": ("Podcasts", "podcast", "mic"),
    "other": ("Other", "other", "collection"),
}


class LegacyError(Exception):
    pass


@dataclass
class Report:
    users_created: list[str] = field(default_factory=list)
    users_matched: list[str] = field(default_factory=list)
    titles: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    types_created: list[str] = field(default_factory=list)
    sources: int = 0
    verdicts: int = 0
    files: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise LegacyError(f"could not read {path}: {error}") from None


def poster_url(old: object) -> str:
    """The old app stored posters as its own proxy path, /api/img?u=<url>."""
    raw = str(old or "")
    if raw.startswith("/api/img?"):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query)
        raw = (query.get("u") or [""])[0]
    return normalize.url(raw)


def title_fields(item: dict[str, Any]) -> dict[str, Any]:
    return normalize.clean_title_fields(
        {
            "title": item.get("title"),
            "year": item.get("year"),
            "type": item.get("type"),
            "tags": item.get("tags"),
            "links": item.get("links"),
            "notes": item.get("notes"),
            "poster_url": poster_url(item.get("poster")),
            "overview": item.get("overview"),
            "runtime": item.get("runtime"),
            "genres": item.get("genres"),
            "creator": item.get("creator"),
            "cast": item.get("cast"),
            "certification": item.get("certification"),
            "source": item.get("source"),
            "source_id": item.get("sourceId"),
            "imdb_id": item.get("imdbId"),
            "wiki_url": item.get("wikiUrl"),
            "apple_tv": item.get("appleTv"),
            "ext_rating": item.get("extRating"),
        }
    )


def import_legacy(store: Store, paths: Paths, old_dir: Path, force: bool = False, dry_run: bool = False, copy_files: bool = True) -> tuple[Report, dict[str, int]]:
    """Returns (report, {old user id: new user id})."""
    library = _read_json(old_dir / "library.json")
    if not isinstance(library, dict) or not isinstance(library.get("items"), list):
        raise LegacyError(f"{old_dir / 'library.json'} is not an old MediaTracker library or export")
    people = (_read_json(old_dir / "users.json") or {}).get("users") or {}
    old_verdicts = (_read_json(old_dir / "verdicts.json") or {}).get("verdicts") or {}
    report = Report()

    existing_titles = store.all(BUCKET_TITLES)
    if existing_titles and not force:
        known = {record["id"] for _key, record in existing_titles}
        if not all(isinstance(item, dict) and item.get("id") in known for item in library["items"]):
            raise LegacyError("the library already has titles that did not come from this import -- re-run with --force to merge into it")

    items = [item for item in library["items"] if isinstance(item, dict) and (item.get("title") or "").strip()]
    if dry_run:
        for item in items:
            report.titles += 1
            report.by_type[item.get("type") or "movie"] = report.by_type.get(item.get("type") or "movie", 0) + 1
            report.by_status[item.get("status") or "queue"] = report.by_status.get(item.get("status") or "queue", 0) + 1
        report.users_created = [record.get("name", "?") for record in people.values()]
        return report, {}

    ensure_builtin(store)
    user_map: dict[str, int] = {}
    with store.transaction() as tx:
        # -- people --------------------------------------------------------
        current = {record["display_name"].strip().lower(): record for _key, record in tx.all(BUCKET_USERS)}
        owner_id = users.owner_id_tx(tx)
        ordered = sorted(people.items(), key=lambda pair: (pair[1].get("name", "").lower() != OWNER_NAME, pair[1].get("createdAt") or ""))
        if not any(record.get("name", "").lower() == OWNER_NAME for _old, record in ordered):
            ordered.insert(0, ("", {"name": OWNER_NAME}))
        for old_id, record in ordered:
            name = (record.get("name") or "").strip()[:80]
            if not name:
                continue
            match = current.get(name.lower())
            if name.lower() == OWNER_NAME:
                if match is None and owner_id is not None:
                    owner = tx.get(BUCKET_USERS, owner_id)
                    if owner is not None and owner["display_name"] == "Admin":
                        # The first-run bootstrap's account, adopted as halo.
                        owner["display_name"] = name
                        tx.put(BUCKET_USERS, owner_id, owner)
                        match = owner
                if match is None:
                    match = users.create_user_tx(tx, name, users.ROLE_ADMIN).to_record()
                    report.users_created.append(name)
                else:
                    report.users_matched.append(name)
            elif match is None:
                match = users.create_user_tx(tx, name, users.ROLE_USER).to_record()
                report.users_created.append(name)
            else:
                report.users_matched.append(name)
            current[name.lower()] = match
            if old_id:
                user_map[old_id] = match["id"]
        halo_id = current[OWNER_NAME]["id"]
        user_map["owner"] = halo_id

        # -- types ---------------------------------------------------------
        found_types = {normalize.type_id(item.get("type")) for item in items} - set(normalize.BUILTIN_TYPES)
        position = max((record.get("position", 0) for _key, record in tx.all(BUCKET_TYPES)), default=1)
        for type_id in sorted(found_types):
            if tx.get(BUCKET_TYPES, type_id) is not None:
                continue
            label, lookup, icon = KNOWN_TYPES.get(type_id, (type_id.replace("-", " ").capitalize(), "other", "collection"))
            position += 1
            tx.put(BUCKET_TYPES, type_id, {"id": type_id, "label": label, "lookup": lookup, "icon": icon, "position": position, "builtin": False, "deleted_at": None, "deleted_by": None, "created_at": to_iso(utc_now())})
            report.types_created.append(type_id)

        # -- titles and halo's state ----------------------------------------
        rev = bump(tx)
        queue_rows: list[tuple[float | None, str, str]] = []
        for item in items:
            fields = title_fields(item)
            if not fields.get("title"):
                report.skipped.append(str(item.get("id")))
                continue
            ident = item.get("id") if normalize.valid_title_id(item.get("id")) else normalize.new_title_id()
            added_by = user_map.get(str(item.get("addedBy") or "")) or halo_id
            record = build(fields, added_by, ident=ident, added_at=normalize.iso(item.get("addedAt")))
            record["updated_at"] = normalize.iso(item.get("updatedAt")) or record["updated_at"]
            if item.get("deleted"):
                record["deleted_at"] = normalize.iso(item.get("deletedAt")) or to_iso(utc_now())
            create_title_tx(tx, record, rev)
            report.titles += 1
            report.by_type[record["type"]] = report.by_type.get(record["type"], 0) + 1

            status = item.get("status") if item.get("status") in normalize.STATUSES else "queue"
            report.by_status[status] = report.by_status.get(status, 0) + 1
            state = {
                "user_id": halo_id,
                "title_id": ident,
                "status": status,
                "rating": normalize.bounded_int(item.get("rating"), 1, 10),
                "heart": bool(item.get("heart")),
                "note": "",
                "watched_at": normalize.iso(item.get("watchedAt")) if status == "watched" else None,
                "updated_at": record["updated_at"],
                "updated_by": halo_id,
                "rev": rev,
            }
            if status in ("queue", "watching"):
                order = normalize.bounded_int(item.get("order"), 0, 1_000_000_000)
                queue_rows.append((float(order) if order is not None else None, record["added_at"] or "", ident))
            tx.put(BUCKET_USER_STATE, states.key(halo_id, ident), state)

        # The old queue becomes halo's "Up next" playlist: the hand-made
        # order first, titles never ordered after it, oldest added first --
        # which is where the old app showed them.
        queue_rows.sort(key=lambda row: (row[0] is None, row[0] if row[0] is not None else 0, row[1]))
        if queue_rows:
            playlists.put_named_tx(tx, halo_id, "Up next", [ident for _order, _added, ident in queue_rows])

        # -- sources and verdicts ---------------------------------------------
        for source in library.get("sources") or []:
            if not isinstance(source, dict):
                continue
            ident = source.get("id") if normalize.valid_title_id(source.get("id")) else None
            if ident and tx.get(BUCKET_SOURCES, ident) is not None:
                continue
            if create_source_tx(tx, source, halo_id, ident=ident, added_at=normalize.iso(source.get("addedAt"))) is not None:
                report.sources += 1
        keys = {str(key): {"v": entry.get("verdict"), "at": entry.get("at")} for key, entry in old_verdicts.items() if isinstance(entry, dict) and entry.get("verdict") in verdicts.VERDICTS}
        if keys:
            verdicts.put_all_tx(tx, halo_id, keys)
            report.verdicts = len(keys)

    if copy_files:
        report.files = copy_reference(old_dir, paths)
    paths.legacy.mkdir(parents=True, exist_ok=True)
    (paths.legacy / "user_map.json").write_text(json.dumps(user_map, indent=1), encoding="utf-8")
    (paths.legacy / "import_report.json").write_text(json.dumps(report.to_dict(), indent=1), encoding="utf-8")
    return report, user_map


def _copy_tree(source: Path, dest: Path) -> int:
    if not source.is_dir():
        return 0
    copied = 0
    for path in source.rglob("*"):
        if not path.is_file() or path.name.startswith(".") or path.name.endswith((".part", ".tmp", ".gz")):
            continue
        target = dest / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".tmp")
        shutil.copy2(path, partial)
        partial.replace(target)
        copied += 1
    return copied


def copy_reference(old_dir: Path, paths: Paths) -> dict[str, int]:
    """The rebuildable public data: the Wikipedia catalogue, its age ratings,
    the IMDb table and the poster cache. Copied, never moved."""
    paths.ensure()
    out = {
        "lists": _copy_tree(old_dir / "lists", paths.lists),
        "imdb": _copy_tree(old_dir / "cache" / "imdb", paths.imdb),
        "images": _copy_tree(old_dir / "cache" / "img", paths.images),
        "certs": 0,
    }
    certs = old_dir / "certs.json"
    if certs.is_file():
        partial = paths.certs.with_name(paths.certs.name + ".tmp")
        shutil.copy2(certs, partial)
        partial.replace(paths.certs)
        out["certs"] = 1
    return out
