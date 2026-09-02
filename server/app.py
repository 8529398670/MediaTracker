#!/usr/bin/env python3
"""Media Tracker — application server.

Two jobs:

  1. Serve the front end.  Everything is gzip-compressed on the wire and
     served with `no-store`, so a refresh always fetches the current file.
  2. Expose a small JSON API over one file on a mounted volume
     (``/data/library.json``), plus a proxy for free metadata providers so
     the browser never talks to third parties directly (no CORS, no leaked
     referrers, and a strict CSP stays intact).

Standard library only, on purpose: the image ships CPython and nothing else.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import os
import re
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import seed

VERSION = "1.1.0"
SCHEMA = 1

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value in (None, "") and name.startswith("MT_"):
        value = os.environ.get("H" + name)      # the old HMT_ prefix still works
    return value if value not in (None, "") else default


def env_flag(name: str, default: bool) -> bool:
    raw = env(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


APP_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> int:
    """Read KEY=VALUE lines from a .env into the environment.

    Parsed rather than executed, and anything already in the environment wins
    — the same two rules dockerRun.sh follows, so starting the server either
    way behaves the same. Inside the container there is no .env: dockerRun.sh
    has already turned it into --env flags, and a file of API keys has no
    business being baked into an image.
    """
    try:
        text = path.read_text("utf-8")
    except OSError:
        return 0

    found = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in os.environ:
            continue
        os.environ[name] = value
        found += 1
    return found


ENV_FILE = Path(env("MT_ENV_FILE") or (APP_ROOT / ".env"))
ENV_COUNT = load_env_file(ENV_FILE)

HOST = env("MT_HOST", "0.0.0.0")
PORT = int(env("MT_PORT", "8080"))
PUBLIC_DIR = Path(env("MT_PUBLIC_DIR", str(APP_ROOT / "public"))).resolve()
DATA_DIR = Path(env("MT_DATA_DIR", str(APP_ROOT / "data"))).resolve()
LIBRARY_PATH = DATA_DIR / "library.json"
BACKUP_DIR = DATA_DIR / "backups"
# The Markdown lists that seed the library.  In the image they are copied to
# /app/seed; running from a checkout they are simply the project root.
SEED_DIR = Path(env("MT_SEED_DIR", str(APP_ROOT))).resolve()
SEED_ENABLED = env_flag("MT_SEED", True)
TOKEN = env("MT_TOKEN")
MAX_BODY = int(env("MT_MAX_BODY", str(32 * 1024 * 1024)))
NET_ENABLED = env_flag("MT_ENABLE_NET", True)
IMG_ALLOW_ANY = env_flag("MT_IMG_ALLOW_ANY", False)
TMDB_KEY = env("TMDB_API_KEY")
OMDB_KEY = env("OMDB_API_KEY")
ENRICH_DELAY = float(env("MT_ENRICH_DELAY", "0.25"))
TOMBSTONE_DAYS = int(env("MT_TOMBSTONE_DAYS", "120"))
BACKUP_KEEP = int(env("MT_BACKUP_KEEP", "40"))
BACKUP_EVERY = int(env("MT_BACKUP_EVERY_SECONDS", "900"))
# Wikimedia and friends ask that a client identify itself and what it is for.
UA = (f"MediaTracker/{VERSION} "
      "(self-hosted personal media library; one user; https://localhost)")

# Inline styles and scripts are disallowed; everything the page needs is a
# same-origin file.  Remote images are pulled through /api/img instead.
CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "manifest-src 'self'; "
    "media-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

BASE_HEADERS = {
    # "nothing is cached" — every response, every time.
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=(), interest-cohort=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": CSP,
}

COMPRESSIBLE = {
    "text/html", "text/css", "text/plain", "text/csv", "text/markdown",
    "text/javascript", "application/javascript", "application/json",
    "image/svg+xml", "application/manifest+json",
}

EXTRA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".webp": "image/webp",
}

ITEM_TYPES = {"movie", "tv", "anime", "doc", "book", "game", "podcast", "other"}
STATUSES = {"queue", "watching", "watched", "dropped"}

MAX_ITEMS = 100_000
MAX_SOURCES = 20_000


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(*parts: object) -> None:
    print(f"[{now_iso()}]", *parts, flush=True)


# --------------------------------------------------------------------------
# normalisation — the server is the authority on shape
# --------------------------------------------------------------------------


def _s(value: object, limit: int, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        value = str(value)
    return value.strip()[:limit]


def _int(value: object, low: int, high: int) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if low <= n <= high else None


def _iso(value: object, fallback: str | None = None) -> str | None:
    text = _s(value, 40)
    if not text:
        return fallback
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return text


def _url(value: object) -> str:
    text = _s(value, 2000)
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return text
    if text.startswith("/api/img?"):  # already proxied
        return text
    return ""


def normalize_item(raw: object, now: str | None = None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    now = now or now_iso()

    title = _s(raw.get("title"), 400)
    item_id = _s(raw.get("id"), 64) or uuid.uuid4().hex
    deleted = bool(raw.get("deleted"))
    if not title and not deleted:
        return None

    links = []
    for link in raw.get("links") or []:
        if isinstance(link, str):
            link = {"url": link}
        if not isinstance(link, dict):
            continue
        url = _url(link.get("url"))
        if not url:
            continue
        links.append({"label": _s(link.get("label"), 120), "url": url})
        if len(links) >= 40:
            break

    tags, seen = [], set()
    for tag in raw.get("tags") or []:
        clean = _s(tag, 48).lower()
        if clean and clean not in seen:
            seen.add(clean)
            tags.append(clean)
        if len(tags) >= 40:
            break

    genres = [_s(g, 48) for g in (raw.get("genres") or [])][:12]

    cast, seen_cast = [], set()
    for person in raw.get("cast") or []:
        name = _s(person, 120)
        key = name.lower()
        if name and key not in seen_cast:
            seen_cast.add(key)
            cast.append(name)
        if len(cast) >= 20:
            break

    item = {
        "id": item_id,
        "title": title,
        "year": _int(raw.get("year"), 1870, 2200),
        "type": raw.get("type") if raw.get("type") in ITEM_TYPES else "movie",
        "status": raw.get("status") if raw.get("status") in STATUSES else "queue",
        "rating": _int(raw.get("rating"), 1, 10),
        "heart": bool(raw.get("heart")),
        "tags": tags,
        "links": links,
        "notes": _s(raw.get("notes"), 20000),
        "poster": _url(raw.get("poster")),
        "overview": _s(raw.get("overview"), 4000),
        "runtime": _int(raw.get("runtime"), 1, 100000),
        "genres": [g for g in genres if g],
        "creator": _s(raw.get("creator"), 300),
        "cast": cast,
        "certification": _s(raw.get("certification"), 32),
        "source": _s(raw.get("source"), 32),
        "sourceId": _s(raw.get("sourceId"), 120),
        "imdbId": _s(raw.get("imdbId"), 32),
        "wikiUrl": _url(raw.get("wikiUrl")),
        "extRating": _int(raw.get("extRating"), 0, 100),
        "order": _int(raw.get("order"), 0, 1_000_000_000),
        "addedAt": _iso(raw.get("addedAt"), now),
        "watchedAt": _iso(raw.get("watchedAt"), None),
        "updatedAt": _iso(raw.get("updatedAt"), now),
        "deleted": deleted,
    }
    if deleted:
        item["deletedAt"] = _iso(raw.get("deletedAt"), now)
    return item


def normalize_source(raw: object, now: str | None = None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url = _url(raw.get("url"))
    if not url:
        return None
    tags = [t for t in (_s(t, 48).lower() for t in (raw.get("tags") or [])) if t][:20]
    return {
        "id": _s(raw.get("id"), 64) or uuid.uuid4().hex,
        "url": url,
        "title": _s(raw.get("title"), 300),
        "note": _s(raw.get("note"), 2000),
        "tags": tags,
        "addedAt": _iso(raw.get("addedAt"), now or now_iso()),
    }


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
        self.data = {
            "schema": SCHEMA,
            "rev": _int(raw.get("rev"), 0, 2**62) or 0,
            "updatedAt": _iso(raw.get("updatedAt"), now),
            "items": items,
            "sources": sources,
            "seeds": seeds if isinstance(seeds, dict) else {},
        }
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


# --------------------------------------------------------------------------
# outbound metadata providers (all free; keys are optional upgrades)
# --------------------------------------------------------------------------

IMG_HOSTS = re.compile(
    r"^(?:[a-z0-9-]+\.)*"
    r"(?:mzstatic\.com|tvmaze\.com|openlibrary\.org|tmdb\.org|media-amazon\.com"
    r"|wikimedia\.org|omdbapi\.com|rawg\.io)$",
    re.I,
)

TMDB_GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
    878: "Science Fiction", 10770: "TV Movie", 53: "Thriller", 10752: "War",
    37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
    10768: "War & Politics",
}

_TAGS = re.compile(r"<[^>]+>")


def strip_tags(text: str) -> str:
    return _TAGS.sub("", text or "").replace("&amp;", "&").replace("&#39;", "'").strip()


class HostPace:
    """A minimum gap between calls to the same host, and backoff after a 429.

    These providers are free and unauthenticated, so politeness is the only
    thing between this and a rate limit — and a rate limit here is invisible,
    because a throttled provider just looks like a title with no data. The
    limits that matter: Wikimedia wants about a call a second, and Apple's
    search endpoint allows roughly twenty a minute.
    """

    LIMITS = {
        "wikidata.org": 1.1,
        "wikipedia.org": 1.1,
        "wikimedia.org": 1.1,
        "itunes.apple.com": 3.0,
        "api.tvmaze.com": 0.6,
        "openlibrary.org": 1.0,
        "www.omdbapi.com": 0.4,
        "api.themoviedb.org": 0.06,
    }

    def __init__(self, default: float = 0.3) -> None:
        self.default = default
        self.next_at: dict[str, float] = {}
        self.penalty: dict[str, float] = {}
        self.lock = threading.Lock()

    def gap(self, host: str) -> float:
        for name, seconds in self.LIMITS.items():
            if host == name or host.endswith("." + name):
                return seconds
        return self.default

    def wait(self, host: str) -> None:
        with self.lock:
            due = max(self.next_at.get(host, 0.0), time.monotonic())
            self.next_at[host] = due + self.gap(host) + self.penalty.get(host, 0.0)
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(min(delay, 60.0))

    def throttled(self, host: str, retry_after: float = 0.0) -> None:
        with self.lock:
            step = min(max(self.penalty.get(host, 0.0) * 2, 1.0), 30.0)
            self.penalty[host] = max(step, min(retry_after, 30.0))
            self.next_at[host] = time.monotonic() + self.penalty[host]

    def eased(self, host: str) -> None:
        with self.lock:
            if host not in self.penalty:
                return
            self.penalty[host] /= 2
            if self.penalty[host] < 0.2:
                del self.penalty[host]


PACE = HostPace()


def fetch_json(url: str, timeout: float = 6.0, limit: int = 4_000_000,
               tries: int = 2) -> object:
    host = urllib.parse.urlsplit(url).hostname or ""
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(max(1, tries)):
        PACE.wait(host)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = json.loads(response.read(limit).decode("utf-8", "replace"))
            PACE.eased(host)
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt + 1 >= tries:
                raise
            try:
                after = float(exc.headers.get("Retry-After") or 0)
            except (TypeError, ValueError):
                after = 0.0
            PACE.throttled(host, after)
    return None


def proxy_img(url: str) -> str:
    if not url:
        return ""
    return "/api/img?u=" + urllib.parse.quote(url, safe="")


def year_of(text: str) -> int | None:
    match = re.search(r"(\d{4})", text or "")
    return int(match.group(1)) if match else None


def prov_tmdb(query: str, kind: str, limit: int) -> list[dict]:
    if not TMDB_KEY:
        return []
    endpoint = {"movie": "search/movie", "tv": "search/tv"}.get(kind, "search/multi")
    url = (f"https://api.themoviedb.org/3/{endpoint}"
           f"?api_key={urllib.parse.quote(TMDB_KEY)}&include_adult=false&query="
           + urllib.parse.quote(query))
    out = []
    for row in (fetch_json(url) or {}).get("results", [])[:limit]:
        media = row.get("media_type") or ("tv" if kind == "tv" else "movie")
        if media not in ("movie", "tv"):
            continue
        poster = row.get("poster_path")
        out.append({
            "source": "tmdb",
            "sourceId": f"{media}/{row.get('id')}",
            "type": "tv" if media == "tv" else "movie",
            "title": row.get("title") or row.get("name") or "",
            "year": year_of(row.get("release_date") or row.get("first_air_date") or ""),
            "poster": proxy_img(f"https://image.tmdb.org/t/p/w342{poster}") if poster else "",
            "overview": _s(row.get("overview"), 2000),
            "genres": [TMDB_GENRES[g] for g in (row.get("genre_ids") or []) if g in TMDB_GENRES],
            "extRating": int(round((row.get("vote_average") or 0) * 10)) or None,
            "link": f"https://www.themoviedb.org/{media}/{row.get('id')}",
        })
    return out


def prov_itunes(query: str, kind: str, limit: int) -> list[dict]:
    entity = {"tv": "tvSeason", "podcast": "podcast", "book": "ebook"}.get(kind, "movie")
    media = {"tv": "tvShow", "podcast": "podcast", "book": "ebook"}.get(kind, "movie")
    url = ("https://itunes.apple.com/search?term=" + urllib.parse.quote(query)
           + f"&media={media}&entity={entity}&limit={limit}&country=US")
    out = []
    for row in (fetch_json(url) or {}).get("results", []):
        art = (row.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
        runtime = row.get("trackTimeMillis")
        out.append({
            "source": "itunes",
            "sourceId": str(row.get("trackId") or row.get("collectionId") or ""),
            "type": {"tvShow": "tv", "podcast": "podcast", "ebook": "book"}.get(media, "movie"),
            "title": row.get("trackName") or row.get("collectionName") or "",
            "year": year_of(row.get("releaseDate") or ""),
            "poster": proxy_img(art),
            "overview": _s(row.get("longDescription") or row.get("description"), 2000),
            "genres": [g for g in [row.get("primaryGenreName")] if g],
            "runtime": round(runtime / 60000) if runtime else None,
            "creator": _s(row.get("artistName"), 200),
            "link": row.get("trackViewUrl") or row.get("collectionViewUrl") or "",
        })
    return out


def prov_tvmaze(query: str, limit: int) -> list[dict]:
    url = "https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(query)
    out = []
    for row in (fetch_json(url) or [])[:limit]:
        show = row.get("show") or {}
        image = (show.get("image") or {}).get("medium") or ""
        rating = (show.get("rating") or {}).get("average")
        out.append({
            "source": "tvmaze",
            "sourceId": str(show.get("id") or ""),
            "type": "anime" if "Anime" in (show.get("genres") or []) else "tv",
            "title": show.get("name") or "",
            "year": year_of(show.get("premiered") or ""),
            "poster": proxy_img(image),
            "overview": _s(strip_tags(show.get("summary") or ""), 2000),
            "genres": show.get("genres") or [],
            "runtime": show.get("averageRuntime") or show.get("runtime"),
            "creator": ((show.get("network") or {}) or {}).get("name") or "",
            "extRating": int(round(rating * 10)) if rating else None,
            "imdbId": (show.get("externals") or {}).get("imdb") or "",
            "link": show.get("officialSite") or show.get("url") or "",
        })
    return out


def prov_openlibrary(query: str, limit: int) -> list[dict]:
    url = ("https://openlibrary.org/search.json?limit=" + str(limit)
           + "&fields=title,author_name,first_publish_year,cover_i,key,subject"
           + "&q=" + urllib.parse.quote(query))
    out = []
    for row in (fetch_json(url) or {}).get("docs", [])[:limit]:
        cover = row.get("cover_i")
        out.append({
            "source": "openlibrary",
            "sourceId": _s(row.get("key"), 80),
            "type": "book",
            "title": row.get("title") or "",
            "year": row.get("first_publish_year"),
            "poster": proxy_img(f"https://covers.openlibrary.org/b/id/{cover}-M.jpg") if cover else "",
            "genres": (row.get("subject") or [])[:4],
            "creator": ", ".join((row.get("author_name") or [])[:2]),
            "link": "https://openlibrary.org" + _s(row.get("key"), 80),
        })
    return out


# "American film director" and "film genre" both contain "film"; neither is
# something you can watch.
WIKI_REJECT = re.compile(
    r"\b(director|actor|actress|screenwriter|filmmaker|producer|composer|"
    r"novelist|author|genre|list of|disambiguation|company|studio|festival|"
    r"award|magazine|band|singer|musician|album|song|character|franchise)\b",
    re.I,
)
WIKI_DISAMBIG = re.compile(
    r"\s*\((?:(?:18|19|20)\d{2}\s+)?(?:film|movie|TV series|television series|"
    r"miniseries|novel|book|video game|serial|radio series)\)\s*$", re.I)

WIKI_KINDS = [
    ("documentar", "doc"), ("anime", "anime"), ("manga", "book"),
    ("television series", "tv"), ("tv series", "tv"), ("sitcom", "tv"),
    ("miniseries", "tv"), ("web series", "tv"), ("television programme", "tv"),
    ("radio", "podcast"), ("podcast", "podcast"), ("video game", "game"),
    ("novel", "book"), ("book", "book"),
    ("film", "movie"), ("movie", "movie"),
]


def prov_wikipedia(query: str, kind: str, limit: int) -> list[dict]:
    """Free, keyless, and unusually good at old films.

    Wikipedia's short descriptions read "1941 film by Preston Sturges", which
    carries the year, the medium and the director in one line.
    """
    url = ("https://en.wikipedia.org/w/rest.php/v1/search/page?limit="
           + str(min(limit * 2, 30)) + "&q=" + urllib.parse.quote(query))
    wanted = {"movie": {"movie", "doc"}, "doc": {"doc", "movie"},
              "tv": {"tv", "anime"}, "anime": {"anime", "tv"},
              "book": {"book"}, "game": {"game"}, "podcast": {"podcast"}}.get(kind)

    out = []
    for page in (fetch_json(url) or {}).get("pages", [])[: limit * 2]:
        desc = _s(page.get("description"), 200)
        if not desc or WIKI_REJECT.search(desc):
            continue
        low = desc.lower()
        media = next((value for token, value in WIKI_KINDS if token in low), None)
        if media is None or (wanted and media not in wanted):
            continue

        thumb = (page.get("thumbnail") or {}).get("url") or ""
        if thumb.startswith("//"):
            thumb = "https:" + thumb
        thumb = re.sub(r"/\d+px-", "/500px-", thumb.split("?")[0])

        year_match = re.search(r"\b((?:18|19|20)\d{2})\b", desc)
        by_match = re.search(r"\bby\s+(.+?)\s*$", desc)
        key = page.get("key") or ""

        out.append({
            "source": "wikipedia",
            "sourceId": key,
            "type": media,
            "title": WIKI_DISAMBIG.sub("", _s(page.get("title"), 300)),
            "year": int(year_match.group(1)) if year_match else None,
            "poster": proxy_img(thumb) if thumb else "",
            "overview": desc,
            "creator": _s(by_match.group(1), 200) if by_match else "",
            "link": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(key),
        })
        if len(out) >= limit:
            break
    return out


def prov_omdb(query: str, kind: str, limit: int) -> list[dict]:
    if not OMDB_KEY:
        return []
    url = (f"https://www.omdbapi.com/?apikey={urllib.parse.quote(OMDB_KEY)}&s="
           + urllib.parse.quote(query))
    if kind in ("movie", "tv"):
        url += "&type=" + ("series" if kind == "tv" else "movie")
    out = []
    for row in (fetch_json(url) or {}).get("Search", [])[:limit]:
        poster = row.get("Poster") or ""
        out.append({
            "source": "omdb",
            "sourceId": row.get("imdbID") or "",
            "type": "tv" if row.get("Type") == "series" else "movie",
            "title": row.get("Title") or "",
            "year": year_of(row.get("Year") or ""),
            "poster": proxy_img(poster) if poster.startswith("http") else "",
            "imdbId": row.get("imdbID") or "",
            "link": f"https://www.imdb.com/title/{row.get('imdbID')}/",
        })
    return out


def lookup(query: str, kind: str, limit: int) -> dict:
    """Fan out to whichever providers suit the media kind, then merge."""
    if not NET_ENABLED:
        return {"query": query, "results": [], "providers": [],
                "note": "network lookups are disabled (MT_ENABLE_NET=0)"}

    plan: list[tuple[str, object]] = []
    if kind in ("movie", "any", "", "doc"):
        plan += [("tmdb", lambda: prov_tmdb(query, "movie" if kind == "movie" else "any", limit)),
                 ("wikipedia", lambda: prov_wikipedia(query, kind or "any", limit)),
                 ("itunes", lambda: prov_itunes(query, "movie", limit)),
                 ("omdb", lambda: prov_omdb(query, "movie", limit))]
    if kind in ("tv", "anime", "any", ""):
        plan += [("tvmaze", lambda: prov_tvmaze(query, limit)),
                 ("tmdb", lambda: prov_tmdb(query, "tv", limit)),
                 ("wikipedia", lambda: prov_wikipedia(query, "tv", limit))]
    if kind == "book":
        plan = [("openlibrary", lambda: prov_openlibrary(query, limit)),
                ("wikipedia", lambda: prov_wikipedia(query, "book", limit))]
    if kind == "podcast":
        plan = [("itunes", lambda: prov_itunes(query, "podcast", limit)),
                ("wikipedia", lambda: prov_wikipedia(query, "podcast", limit))]

    results: list[dict] = []
    used: list[str] = []
    errors: list[str] = []
    seen: set[tuple] = set()

    for name, call in plan:
        if name in used:
            continue
        if BREAKER.is_open(name):
            errors.append(f"{name}: skipped (recent failures)")
            continue
        try:
            rows = call()
        except (urllib.error.URLError, socket.timeout, ValueError, TimeoutError) as exc:
            BREAKER.record(name, False)
            errors.append(f"{name}: {type(exc).__name__}")
            continue
        BREAKER.record(name, True)
        if not rows:
            continue
        used.append(name)
        for row in rows:
            if not row.get("title"):
                continue
            key = (row["title"].strip().lower(), row.get("year"))
            if key in seen:
                continue
            seen.add(key)
            results.append({k: v for k, v in row.items() if v not in (None, "", [])})
        if len(results) >= limit:
            break

    return {"query": query, "kind": kind, "providers": used,
            "errors": errors, "results": results[: limit * 2]}


def lookup_detail(source: str, ref: str) -> dict:
    """Second hop for the richer fields search endpoints leave out."""
    if not NET_ENABLED:
        return {}
    if source == "tmdb" and TMDB_KEY:
        media, _, ident = ref.partition("/")
        if media not in ("movie", "tv") or not ident.isdigit():
            return {}
        url = (f"https://api.themoviedb.org/3/{media}/{ident}"
               f"?api_key={urllib.parse.quote(TMDB_KEY)}"
               "&append_to_response=credits,external_ids")
        row = fetch_json(url) or {}
        crew = (row.get("credits") or {}).get("crew") or []
        directors = [c.get("name") for c in crew if c.get("job") == "Director"]
        creators = [c.get("name") for c in (row.get("created_by") or [])]
        runtime = row.get("runtime")
        if not runtime and row.get("episode_run_time"):
            runtime = (row["episode_run_time"] or [None])[0]
        return {
            "runtime": runtime,
            "genres": [g.get("name") for g in (row.get("genres") or [])][:6],
            "creator": ", ".join((directors or creators)[:2]),
            "imdbId": (row.get("external_ids") or {}).get("imdb_id") or row.get("imdb_id") or "",
            "overview": _s(row.get("overview"), 2000),
        }
    if source == "tvmaze" and ref.isdigit():
        row = fetch_json(f"https://api.tvmaze.com/shows/{ref}?embed=cast") or {}
        return {
            "runtime": row.get("averageRuntime") or row.get("runtime"),
            "genres": row.get("genres") or [],
            "imdbId": (row.get("externals") or {}).get("imdb") or "",
            "overview": _s(strip_tags(row.get("summary") or ""), 2000),
        }
    return {}


# --------------------------------------------------------------------------
# small per-IP rate limiter for the outbound endpoints
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# enrichment — filling in what the documents never carried
# --------------------------------------------------------------------------
#
# The lists that seeded this library are titles and links: no artwork, no
# cast, no ages, and a year on barely half of them.  These providers go and
# find the rest.  None of them is IMDb: IMDb's own API is an AWS Data Exchange
# product priced for studios, and its Parents Guide is a paid add-on to that.
# The closest honest substitutes are the age certification (which TMDB, OMDb
# and Wikidata all carry) and a direct link into IMDb's page for the title,
# which the browser opens itself.
#
# Everything here is best effort.  A provider that fails is skipped, a field
# already filled in is never overwritten, and nothing is invented.

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Wikidata classes worth treating as a film or as a series.
WD_FILM = {"Q11424", "Q24856", "Q202866", "Q506240", "Q20650540", "Q93204"}
WD_SHOW = {"Q5398426", "Q15416", "Q1366112", "Q581714", "Q117467246"}
WD_BOOK = {"Q7725634", "Q571", "Q47461344", "Q8261"}

# The fields enrichment tries to fill, in the order they matter.
ENRICH_FIELDS = ("year", "poster", "cast", "certification", "imdbId",
                 "wikiUrl", "overview", "runtime", "genres", "creator")

# Once these are in hand the chain stops. Chasing a certification that may not
# exist anywhere would spend a provider call on every title for nothing.
#
# `wikiUrl` is here even though TMDB never returns one: without it the chain
# would stop at TMDB — which answers everything else in a single call — and
# never reach the two providers that know which Wikipedia article this is.
ENRICH_CORE = ("year", "poster", "cast", "overview", "wikiUrl")

# What a refresh may overwrite: things a provider gave us, and nothing else.
# `year` is deliberately absent — you can type a year on the card, and a
# refresh must never argue with that. Status, rating, hearts, tags, notes and
# links are yours and are not touched under any mode.
REFRESH_FIELDS = ("poster", "cast", "certification", "imdbId", "wikiUrl",
                  "overview", "runtime", "genres", "creator", "extRating")

# The best artwork available, when there is a key for it.
PREFERRED_POSTER_HOST = "image.tmdb.org"


def poster_host(item: dict) -> str:
    """Which provider an item's artwork actually came from."""
    url = item.get("poster") or ""
    if url.startswith("/api/img?"):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        url = (query.get("u") or [""])[0]
    return (urllib.parse.urlsplit(url).hostname or "") if url else ""


def _fill(patch: dict, found: dict) -> None:
    """Take only what is still missing, and never a blank."""
    for key, value in (found or {}).items():
        if key not in ENRICH_FIELDS or patch.get(key):
            continue
        if value in (None, "", [], 0):
            continue
        patch[key] = value


def _needs(item: dict, patch: dict, fields: tuple = ENRICH_FIELDS) -> list[str]:
    return [f for f in fields if not (patch.get(f) or item.get(f))]


def _wd_claims(entity: dict, prop: str) -> list[object]:
    out = []
    for claim in (entity.get("claims") or {}).get(prop, []):
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is not None:
            out.append(value)
    return out


def _wd_ids(entity: dict, prop: str) -> list[str]:
    return [v["id"] for v in _wd_claims(entity, prop)
            if isinstance(v, dict) and v.get("id")]


def _wd_strings(entity: dict, prop: str) -> list[str]:
    return [v for v in _wd_claims(entity, prop) if isinstance(v, str)]


def _wd_year(entity: dict) -> int | None:
    for value in _wd_claims(entity, "P577"):
        stamp = value.get("time", "") if isinstance(value, dict) else ""
        if len(stamp) > 5 and stamp[1:5].isdigit():
            return int(stamp[1:5])
    return None


def enrich_wikidata(title: str, year: int | None, kind: str) -> dict:
    """Cast, director, age rating and the IMDb id — with no key at all.

    Three small calls to the ordinary Wikidata API rather than one to its
    query service: the query service is frequently rate-limited to a request
    a minute, which is no use for a library of a thousand titles.
    """
    hits = (fetch_json(
        f"{WIKIDATA_API}?action=wbsearchentities&format=json&language=en&uselang=en"
        f"&type=item&limit=8&search={urllib.parse.quote(title[:120])}") or {}).get("search", [])
    if not hits:
        return {}

    entities = (fetch_json(
        f"{WIKIDATA_API}?action=wbgetentities&format=json&languages=en"
        f"&props=claims|sitelinks&sitefilter=enwiki"
        f"&ids={'|'.join(h['id'] for h in hits[:8])}") or {}).get("entities", {})

    wanted = WD_SHOW if kind in ("tv", "anime") else WD_BOOK if kind == "book" else WD_FILM
    best = None
    for hit in hits:
        entity = entities.get(hit["id"])
        if not entity or not set(_wd_ids(entity, "P31")) & wanted:
            continue
        found_year = _wd_year(entity)
        if year:
            # A year we already have settles which "Sense and Sensibility" this
            # is. Without a match we take nothing: the cast of the wrong film
            # is worse than no cast at all.
            if found_year and abs(found_year - year) <= 1:
                best = entity
                break
            continue
        best = entity        # nothing to disambiguate with — take the best hit
        break
    if best is None:
        return {}

    cast_ids = _wd_ids(best, "P161")[:12]
    maker_ids = (_wd_ids(best, "P57") or _wd_ids(best, "P170"))[:2]
    rating_ids = _wd_ids(best, "P1657")[:1]
    genre_ids = _wd_ids(best, "P136")[:4]

    labels: dict[str, str] = {}
    refs = list(dict.fromkeys(cast_ids + maker_ids + rating_ids + genre_ids))
    if refs:
        resolved = (fetch_json(
            f"{WIKIDATA_API}?action=wbgetentities&format=json&languages=en&props=labels"
            f"&ids={'|'.join(refs[:50])}") or {}).get("entities", {})
        labels = {k: ((v.get("labels") or {}).get("en") or {}).get("value", "")
                  for k, v in resolved.items()}

    name = lambda ids: [labels[i] for i in ids if labels.get(i)]  # noqa: E731

    page = ((best.get("sitelinks") or {}).get("enwiki") or {}).get("title") or ""
    wiki = ("https://en.wikipedia.org/wiki/"
            + urllib.parse.quote(page.replace(" ", "_"))) if page else ""

    image = (_wd_strings(best, "P18") or [""])[0]
    poster = ""
    if image:
        poster = proxy_img("https://commons.wikimedia.org/wiki/Special:FilePath/"
                           + urllib.parse.quote(image.replace(" ", "_")) + "?width=400")

    return {
        "year": _wd_year(best),
        "poster": poster,
        "cast": name(cast_ids),
        "creator": ", ".join(name(maker_ids)),
        "certification": (name(rating_ids) or [""])[0],
        "genres": name(genre_ids),
        "imdbId": (_wd_strings(best, "P345") or [""])[0],
        "wikiUrl": wiki,
    }


def enrich_tmdb(title: str, year: int | None, kind: str) -> dict:
    """The best of the lot, and the only one that needs a (free) key."""
    if not TMDB_KEY:
        return {}
    media = "tv" if kind in ("tv", "anime") else "movie"
    key = urllib.parse.quote(TMDB_KEY)
    search = (f"https://api.themoviedb.org/3/search/{media}?api_key={key}"
              f"&include_adult=false&query={urllib.parse.quote(title[:120])}"
              + (f"&{'first_air_date_year' if media == 'tv' else 'year'}={year}" if year else ""))
    results = (fetch_json(search) or {}).get("results") or []
    if not results and year:                       # the year may be the wrong one
        results = (fetch_json(search.rsplit("&", 1)[0]) or {}).get("results") or []
    if not results:
        return {}

    ident = results[0].get("id")
    row = fetch_json(
        f"https://api.themoviedb.org/3/{media}/{ident}?api_key={key}"
        "&append_to_response=credits,external_ids,release_dates,content_ratings") or {}

    crew = (row.get("credits") or {}).get("crew") or []
    makers = [c.get("name") for c in crew if c.get("job") == "Director"] \
        or [c.get("name") for c in (row.get("created_by") or [])]

    # Age certification: US first, then whatever the title actually carries.
    certification = ""
    for entry in ((row.get("release_dates") or {}).get("results") or []):
        for release in entry.get("release_dates") or []:
            if release.get("certification"):
                certification = release["certification"]
                if entry.get("iso_3166_1") == "US":
                    break
        if certification and entry.get("iso_3166_1") == "US":
            break
    for entry in ((row.get("content_ratings") or {}).get("results") or []):
        if entry.get("rating") and (not certification or entry.get("iso_3166_1") == "US"):
            certification = entry["rating"]
            if entry.get("iso_3166_1") == "US":
                break

    runtime = row.get("runtime") or (row.get("episode_run_time") or [None])[0]
    poster = row.get("poster_path")
    return {
        "year": year_of(row.get("release_date") or row.get("first_air_date") or ""),
        "poster": proxy_img(f"https://image.tmdb.org/t/p/w342{poster}") if poster else "",
        "cast": [c.get("name") for c in ((row.get("credits") or {}).get("cast") or [])[:12]
                 if c.get("name")],
        "certification": _s(certification, 32),
        "imdbId": (row.get("external_ids") or {}).get("imdb_id") or row.get("imdb_id") or "",
        "overview": _s(row.get("overview"), 2000),
        "runtime": runtime,
        "genres": [g.get("name") for g in (row.get("genres") or [])][:6],
        "creator": ", ".join([m for m in makers if m][:2]),
        "extRating": int(round((row.get("vote_average") or 0) * 10)) or None,
    }


def enrich_omdb(title: str, year: int | None, imdb_id: str = "") -> dict:
    """IMDb's own numbers, second hand and legitimately — with a free key."""
    if not OMDB_KEY:
        return {}
    key = urllib.parse.quote(OMDB_KEY)
    query = f"i={urllib.parse.quote(imdb_id)}" if imdb_id \
        else f"t={urllib.parse.quote(title[:120])}" + (f"&y={year}" if year else "")
    row = fetch_json(f"https://www.omdbapi.com/?apikey={key}&plot=short&{query}") or {}
    if row.get("Response") != "True":
        return {}
    rated = _s(row.get("Rated"), 32)
    poster = _s(row.get("Poster"), 600)
    minutes = re.match(r"(\d+)", _s(row.get("Runtime"), 20))
    runtime = int(minutes.group(1)) if minutes else None
    try:
        ext = int(round(float(row.get("imdbRating")) * 10))
    except (TypeError, ValueError):
        ext = None
    return {
        "year": year_of(_s(row.get("Year"), 20)),
        "poster": proxy_img(poster) if poster.startswith("http") else "",
        "cast": [n.strip() for n in _s(row.get("Actors"), 400).split(",") if n.strip()],
        "certification": "" if rated in ("N/A", "Not Rated", "Unrated") else rated,
        "imdbId": _s(row.get("imdbID"), 32),
        "overview": "" if row.get("Plot") in (None, "N/A") else _s(row.get("Plot"), 2000),
        "runtime": runtime,
        "genres": [g.strip() for g in _s(row.get("Genre"), 200).split(",") if g.strip()][:6],
        "creator": "" if row.get("Director") in (None, "N/A") else _s(row.get("Director"), 200),
        "extRating": ext,
    }


def enrich_tvmaze(title: str, year: int | None, kind: str) -> dict:
    if kind not in ("tv", "anime"):
        return {}
    hits = fetch_json("https://api.tvmaze.com/search/shows?q="
                      + urllib.parse.quote(title[:120])) or []
    shows = [h.get("show") or {} for h in hits if (h.get("show") or {}).get("id")]
    if not shows:
        return {}
    # "Little House on the Prairie" is a 1974 series and a 2026 one. A year we
    # already have says which; without one, take the best-ranked.
    best = None
    if year:
        best = next((s for s in shows
                     if (year_of(s.get("premiered") or "") or 0) in (year - 1, year, year + 1)), None)
    row = best or shows[0]
    full = fetch_json(f"https://api.tvmaze.com/shows/{row['id']}?embed=cast")
    row = full if isinstance(full, dict) and full.get("id") else row
    image = (row.get("image") or {}).get("medium") or (row.get("image") or {}).get("original") or ""
    cast = [(entry.get("person") or {}).get("name")
            for entry in ((row.get("_embedded") or {}).get("cast") or [])[:12]]
    return {
        "year": year_of(row.get("premiered") or ""),
        "poster": proxy_img(image) if image else "",
        "cast": [c for c in cast if c],
        "imdbId": (row.get("externals") or {}).get("imdb") or "",
        "overview": _s(strip_tags(row.get("summary") or ""), 2000),
        "runtime": row.get("averageRuntime") or row.get("runtime"),
        "genres": row.get("genres") or [],
        "certification": "",
    }


def title_matches(wanted: str, found: str) -> bool:
    """Close enough to be the same work, rather than merely a search hit.

    "Sunrise" is "Sunrise: A Song of Two Humans"; it is not "The Hunger
    Games: Sunrise on the Reaping".
    """
    plain = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()  # noqa: E731
    a, b = plain(wanted), plain(found)
    if not a or not b:
        return False
    return a == b or b.startswith(a + " ") or a.startswith(b + " ")


def best_row(rows: list[dict], title: str, year: int | None) -> dict | None:
    """Pick a search result, or nothing. Never the top hit as a consolation.

    Guessing costs more than it saves: a confident wrong answer puts another
    film's poster and article on the card, and nothing about the card says it
    was a guess.
    """
    if not rows:
        return None
    if year:
        near = [r for r in rows if r.get("year") and abs(r["year"] - year) <= 1]
        exact = next((r for r in near if title_matches(title, r.get("title"))), None)
        # A matching year is a strong signal on its own; take it either way,
        # but if nothing matches the year we know, take nothing.
        return exact or (near[0] if near else None)
    return next((r for r in rows if title_matches(title, r.get("title"))), None)


def enrich_wikipedia(title: str, year: int | None, kind: str) -> dict:
    """Reuses the search provider: unusually good on films before 1970."""
    best = best_row(prov_wikipedia(title, kind, 6), title, year)
    if best is None:
        return {}
    return {"year": best.get("year"), "poster": best.get("poster"),
            "overview": best.get("overview"), "creator": best.get("creator"),
            "wikiUrl": best.get("link")}


def enrich_itunes(title: str, year: int | None, kind: str) -> dict:
    best = best_row(prov_itunes(title, kind, 6), title, year)
    if best is None:
        return {}
    return {"year": best.get("year"), "poster": best.get("poster"),
            "overview": best.get("overview"), "genres": best.get("genres"),
            "runtime": best.get("runtime")}


def enrich_openlibrary(title: str, year: int | None, kind: str) -> dict:
    if kind != "book":
        return {}
    best = best_row(prov_openlibrary(title, 6), title, year)
    if best is None:
        return {}
    return {"year": best.get("year"), "poster": best.get("poster"),
            "creator": best.get("creator"), "overview": best.get("overview")}


# Richest first; the chain stops as soon as nothing is left to fill.
ENRICH_CHAIN = {
    "tv":      ("tmdb", "tvmaze", "wikidata", "wikipedia", "omdb"),
    "anime":   ("tmdb", "tvmaze", "wikidata", "wikipedia"),
    "book":    ("openlibrary", "wikidata", "wikipedia"),
    # Wikipedia leads for film: its one-line descriptions ("1941 film by
    # Preston Sturges") carry the year, and the year is what lets Wikidata
    # tell two films of the same name apart.
    # No iTunes here: Apple's public search endpoint stopped returning films,
    # and each call to it costs three seconds of the rate limit.
    "movie":   ("tmdb", "wikipedia", "wikidata", "omdb"),
    "doc":     ("tmdb", "wikipedia", "wikidata", "omdb"),
    "podcast": ("itunes", "wikidata", "wikipedia"),
    "game":    ("wikidata", "wikipedia"),
    "other":   ("wikipedia", "wikidata"),
}

ENRICH_PROVIDERS = {
    "tmdb": enrich_tmdb,
    "omdb": lambda t, y, k: enrich_omdb(t, y),
    "wikidata": enrich_wikidata,
    "wikipedia": enrich_wikipedia,
    "tvmaze": enrich_tvmaze,
    "itunes": enrich_itunes,
    "openlibrary": enrich_openlibrary,
}


def enrich_item(item: dict, problems: list | None = None,
                replace: tuple = ()) -> dict:
    """Everything we can find for one title, as a patch.

    Normally only blanks are filled. `replace` names the fields this pass is
    allowed to overwrite as well — a field being replaced does not count as
    one we already have, so the chain keeps looking until it has a better
    answer for it.
    """
    title = item.get("title") or ""
    if not title:
        return {}
    kind = item.get("type") or "movie"
    patch: dict = {}
    problems = problems if problems is not None else []
    have = {k: v for k, v in item.items() if k not in replace}

    for name in ENRICH_CHAIN.get(kind, ENRICH_CHAIN["other"]):
        if not _needs(have, patch, ENRICH_CORE):
            break
        if BREAKER.is_open(name):
            continue
        try:
            found = ENRICH_PROVIDERS[name](title, item.get("year") or patch.get("year"), kind)
            BREAKER.record(name, True)
        except (urllib.error.URLError, socket.timeout, TimeoutError,
                ValueError, KeyError, TypeError) as exc:
            # A timeout is the provider's fault and trips the breaker; a bad
            # answer for one title is not.
            offline = isinstance(exc, (urllib.error.URLError, TimeoutError))
            BREAKER.record(name, not offline)
            problems.append(f"{name}: {type(exc).__name__}")
            continue
        _fill(patch, found)
        if found:
            patch.setdefault("source", name)

    # A field is written when it was asked to be replaced, or when the title
    # has nothing there. A provider never blanks anything: _fill drops empties
    # on the way in, so a refresh that finds nothing leaves what was there.
    out = {}
    for key, value in patch.items():
        if key in replace:
            out[key] = value
        elif key in ENRICH_FIELDS + ("source", "extRating") and not item.get(key):
            out[key] = value
    return out


class Enricher:
    """One background pass over the library, pausable and resumable.

    Providers are shared, free and rate limited, so titles are worked through
    one at a time with a pause between them.  Progress is committed as it
    goes: stopping it, or restarting the server, loses nothing.
    """

    def __init__(self, library: "Library") -> None:
        self.library = library
        # Reentrant: start() and stop() report their new state while holding it.
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.stopping = False
        self.reset()

    def reset(self) -> None:
        self.running = False
        self.done = 0
        self.filled = 0
        self.total = 0
        self.errors = 0
        self.current = ""
        self.started = ""
        self.finished = ""
        self.note = ""
        self.trouble = ""
        self.scope = "missing"
        self.replacing = False

    # What each scope goes after, and which fields it may overwrite.
    SCOPES = {
        "missing": (),                      # fill blanks only
        "artwork": (),
        "year": (),
        "all": (),
        "upgrade": ("poster",),             # better artwork, nothing else
        "refresh": REFRESH_FIELDS,          # re-fetch the lot
    }

    def candidates(self, scope: str) -> list[dict]:
        rows = [i for i in self.library.snapshot()["items"] if not i.get("deleted")]
        if scope in ("all", "refresh"):
            return rows
        if scope == "upgrade":
            # Artwork that came from somewhere other than the best source we
            # have a key for. Nothing to upgrade to without one.
            if not TMDB_KEY:
                return []
            return [i for i in rows
                    if i.get("poster") and poster_host(i) != PREFERRED_POSTER_HOST]
        if scope == "artwork":
            return [i for i in rows if not i.get("poster")]
        if scope == "year":
            return [i for i in rows if not i.get("year")]
        return [i for i in rows if _needs(i, {})]

    def status(self) -> dict:
        with self.lock:
            left = max(0, self.total - self.done)
            return {
                "running": self.running,
                "done": self.done,
                "filled": self.filled,
                "total": self.total,
                "current": self.current,
                "startedAt": self.started,
                "finishedAt": self.finished,
                "note": self.note,
                "errors": self.errors,
                "trouble": self.trouble,
                "scope": self.scope,
                "replacing": self.replacing,
                "canUpgrade": bool(TMDB_KEY),
                # Roughly four paced provider calls per title.
                "etaSeconds": int(left * (ENRICH_DELAY + 4.0)) if self.running else 0,
                "providers": {"tmdb": bool(TMDB_KEY), "omdb": bool(OMDB_KEY),
                              "wikidata": True, "wikipedia": True,
                              "tvmaze": True, "itunes": True, "openlibrary": True},
                "network": NET_ENABLED,
            }

    def start(self, scope: str = "missing", limit: int = 0) -> dict:
        with self.lock:
            if self.running:
                return self.status()
            if not NET_ENABLED:
                self.note = "lookups are switched off in this container"
                return self.status()
            replace = self.SCOPES.get(scope, ())
            rows = self.candidates(scope)
            if limit > 0:
                rows = rows[:limit]
            self.reset()
            self.scope = scope
            self.replacing = bool(replace)
            self.running = True
            self.total = len(rows)
            self.started = now_iso()
            self.stopping = False
            self.note = (f"{self.total} titles queued"
                         + (" — replacing what is there" if replace else ""))
            if not rows:
                self.running = False
                self.note = "nothing matches that"
                return self.status()
            self.thread = threading.Thread(
                target=self._work, args=([r["id"] for r in rows], replace),
                daemon=True, name="enrich")
            self.thread.start()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            self.stopping = True
            self.note = "stopping…"
        return self.status()

    def _work(self, ids: list[str], replace: tuple = ()) -> None:
        log(f"enrich: starting on {len(ids)} titles"
            + (f", replacing {', '.join(replace)}" if replace else ""))
        pending: dict[str, dict] = {}
        try:
            for item_id in ids:
                with self.lock:
                    if self.stopping:
                        break
                item = next((i for i in self.library.snapshot()["items"]
                             if i["id"] == item_id), None)
                if item is None or item.get("deleted"):
                    continue
                with self.lock:
                    self.current = item.get("title", "")

                patch, problems = {}, []
                try:
                    patch = enrich_item(item, problems, replace)
                except Exception as exc:                        # never kill the pass
                    problems.append(f"{type(exc).__name__}: {exc}")
                    log(f"enrich: {item.get('title')!r} failed: {type(exc).__name__}: {exc}")

                with self.lock:
                    self.done += 1
                    if patch:
                        self.filled += 1
                    if problems and not patch:
                        self.errors += 1
                        self.trouble = problems[0][:120]
                if patch:
                    pending[item_id] = patch
                if len(pending) >= 8:
                    self.library.patch_many(pending)
                    pending = {}
                time.sleep(ENRICH_DELAY)
        finally:
            if pending:
                self.library.patch_many(pending)
            with self.lock:
                self.running = False
                self.stopping = False
                self.current = ""
                self.finished = now_iso()
                self.note = (f"filled in {self.filled} of {self.done}"
                             + (f", {self.errors} found nothing" if self.errors else ""))
            log(f"enrich: finished — filled in {self.filled} of {self.done}"
                f" ({self.errors} found nothing)")


class RateLimiter:
    def __init__(self, allowance: int, window: float) -> None:
        self.allowance = allowance
        self.window = window
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if len(self.hits) > 4096:
                self.hits.clear()
            bucket = self.hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.allowance:
                return False
            bucket.append(now)
            return True


class Breaker:
    """Stop calling a provider that just timed out.

    Providers are queried in sequence, so one unreachable host would otherwise
    add its full timeout to every single lookup.
    """

    def __init__(self, threshold: int = 2, cooldown: float = 600.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.state: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()

    def is_open(self, name: str) -> bool:
        with self.lock:
            fails, until = self.state.get(name, (0, 0.0))
            if fails >= self.threshold and time.monotonic() < until:
                return True
            return False

    def record(self, name: str, ok: bool) -> None:
        with self.lock:
            if ok:
                self.state.pop(name, None)
                return
            fails = self.state.get(name, (0, 0.0))[0] + 1
            self.state[name] = (fails, time.monotonic() + self.cooldown)


BREAKER = Breaker()
OUTBOUND_LIMIT = RateLimiter(180, 60.0)
LIBRARY = Library(LIBRARY_PATH)
ENRICHER = Enricher(LIBRARY)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def version_string(self) -> str:  # do not advertise Python/BaseHTTP versions
        return "mediatracker"

    def log_message(self, fmt: str, *args: object) -> None:
        if env_flag("MT_ACCESS_LOG", False):
            log(self.address_string(), fmt % args)

    # -- plumbing ------------------------------------------------------

    def _accepts_gzip(self) -> bool:
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def _send(self, status: int, body: bytes | str = b"", ctype: str = "text/plain; charset=utf-8",
              headers: dict | None = None, compress: bool = True) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        out = dict(BASE_HEADERS)
        if headers:
            out.update(headers)
        if compress and len(body) >= 400 and self._accepts_gzip() \
                and ctype.split(";")[0].strip() in COMPRESSIBLE:
            body = gzip.compress(body, 6, mtime=0)
            out["Content-Encoding"] = "gzip"
        out["Vary"] = "Accept-Encoding"
        out["Content-Type"] = ctype
        out["Content-Length"] = str(len(body))
        try:
            self.send_response(status)
            for key, value in out.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _json(self, status: int, payload: object, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _fail(self, status: int, message: str) -> None:
        self._json(status, {"error": message, "status": status})

    def _body(self) -> object | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._fail(400, "bad content-length")
            return None
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self._fail(413, "request body too large")
            return None
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._fail(400, "body must be JSON")
            return None

    def _authorized(self, path: str) -> bool:
        if not TOKEN:
            return True
        if path in ("/api/health", "/favicon.svg"):
            return True
        header = self.headers.get("X-HMT-Token")
        if header and _constant_eq(header, TOKEN):
            return True
        cookies = self.headers.get("Cookie") or ""
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "hmt" and _constant_eq(urllib.parse.unquote(value), TOKEN):
                return True
        return False

    # -- verbs ---------------------------------------------------------

    def do_GET(self) -> None:
        self._route("GET")

    def do_HEAD(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PUT(self) -> None:
        self._route("PUT")

    def do_PATCH(self) -> None:
        self._route("PATCH")

    def do_DELETE(self) -> None:
        self._route("DELETE")

    def do_OPTIONS(self) -> None:
        self._send(204, b"", "text/plain", {"Allow": "GET, HEAD, POST, PUT, PATCH, DELETE"})

    # -- routing -------------------------------------------------------

    def _route(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        # A token in the URL is exchanged once for a session cookie.
        if TOKEN and query.get("k") and _constant_eq(query["k"][0], TOKEN):
            self._send(302, b"", "text/plain", {
                "Location": path or "/",
                "Set-Cookie": (f"hmt={urllib.parse.quote(TOKEN)}; Path=/; HttpOnly; "
                               "SameSite=Strict; Max-Age=31536000"),
            })
            return

        if not self._authorized(path):
            self._fail(401, "a token is required — open the app with ?k=<token>")
            return

        try:
            if path.startswith("/api/"):
                self._api(method, path, query)
            elif method == "GET":
                self._static(path)
            else:
                self._fail(405, "method not allowed")
        except Exception as exc:  # never leak a traceback to the client
            log(f"!! {method} {path}: {type(exc).__name__}: {exc}")
            self._fail(500, "internal error")

    def _api(self, method: str, path: str, query: dict) -> None:
        parts = [p for p in path.split("/") if p][1:]  # drop "api"
        head = parts[0] if parts else ""

        if head == "health":
            self._json(200, {"ok": True, "version": VERSION, **LIBRARY.meta()})
            return

        if head == "config":
            self._json(200, {
                "version": VERSION,
                "schema": SCHEMA,
                "network": NET_ENABLED,
                "providers": {
                    "tmdb": bool(TMDB_KEY), "omdb": bool(OMDB_KEY),
                    "itunes": True, "tvmaze": True, "openlibrary": True, "wikipedia": True,
                },
                "dataPath": str(LIBRARY_PATH),
            })
            return

        if head == "library":
            self._api_library(method, parts, query)
            return

        if head == "enrich":
            if method == "GET":
                self._json(200, ENRICHER.status())
                return
            if method == "POST":
                payload = self._body()
                if payload is None:
                    return
                body = payload if isinstance(payload, dict) else {}
                action = _s(body.get("action"), 16) or "start"
                if action == "stop":
                    self._json(200, ENRICHER.stop())
                    return
                scope = _s(body.get("scope"), 16) or "missing"
                if scope not in Enricher.SCOPES:
                    scope = "missing"
                self._json(200, ENRICHER.start(scope, _int(body.get("limit"), 0, 100000) or 0))
                return
            self._fail(405, "GET or POST")
            return

        if head in ("lookup", "img"):
            if not OUTBOUND_LIMIT.allow(self.client_address[0] if self.client_address else "?"):
                self._fail(429, "slow down")
                return
            if head == "img":
                self._api_img(query)
            elif len(parts) > 1 and parts[1] == "detail":
                source = (query.get("source") or [""])[0][:24]
                ref = (query.get("id") or [""])[0][:64]
                self._json(200, lookup_detail(source, ref))
            else:
                term = (query.get("q") or [""])[0].strip()[:200]
                if not term:
                    self._fail(400, "q is required")
                    return
                kind = (query.get("type") or ["any"])[0][:16]
                limit = max(1, min(_int((query.get("limit") or ["12"])[0], 1, 40) or 12, 40))
                self._json(200, lookup(term, kind, limit))
            return

        self._fail(404, "no such endpoint")

    def _api_library(self, method: str, parts: list[str], query: dict) -> None:
        # /api/library
        if len(parts) == 1:
            if method == "GET":
                self._json(200, LIBRARY.snapshot())
            elif method == "PUT":
                payload = self._body()
                if payload is None:
                    return
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                    self._fail(400, "expected {items: [...]}")
                    return
                ok, result = LIBRARY.replace(payload)
                if not ok:
                    self._json(409 if result.get("error") == "conflict" else 400, result)
                    return
                self._json(200, {"ok": True, "rev": result["rev"], **LIBRARY.meta()})
            else:
                self._fail(405, "GET or PUT")
            return

        # /api/library/items[/<id>]
        if parts[1] == "items":
            item_id = parts[2] if len(parts) > 2 else ""
            if method == "POST" and not item_id:
                payload = self._body()
                if payload is None:
                    return
                item = LIBRARY.upsert(payload if isinstance(payload, dict) else {})
                self._json(201 if item else 400,
                           item or {"error": "an item needs at least a title"})
                return
            if method == "PATCH" and item_id:
                payload = self._body()
                if payload is None:
                    return
                item = LIBRARY.patch(item_id, payload if isinstance(payload, dict) else {})
                self._json(200 if item else 404, item or {"error": "not found"})
                return
            if method == "DELETE" and item_id:
                hard = (query.get("hard") or ["0"])[0] == "1"
                ok = LIBRARY.delete(item_id, hard)
                self._json(200 if ok else 404, {"ok": ok, **LIBRARY.meta()})
                return
            self._fail(405, "POST /items, PATCH /items/<id>, DELETE /items/<id>")
            return

        self._fail(404, "no such endpoint")

    def _api_img(self, query: dict) -> None:
        target = (query.get("u") or [""])[0]
        if not target:
            self._fail(400, "u is required")
            return
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme != "https" or not parsed.netloc:
            self._fail(400, "https urls only")
            return
        if not IMG_ALLOW_ANY and not IMG_HOSTS.match(parsed.hostname or ""):
            self._fail(403, "image host is not allow-listed")
            return
        if not NET_ENABLED:
            self._fail(503, "network lookups are disabled")
            return
        try:
            request = urllib.request.Request(target, headers={"User-Agent": UA, "Accept": "image/*"})
            with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310
                ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    self._fail(415, "not an image")
                    return
                blob = response.read(8 * 1024 * 1024)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError):
            self._fail(502, "could not fetch that image")
            return
        self._send(200, blob, ctype, compress=False)

    # -- static --------------------------------------------------------

    def _static(self, path: str) -> None:
        target = self._resolve(path)
        if target is None:
            # Unknown non-asset path: hand back the app shell.
            if "." not in path.rsplit("/", 1)[-1]:
                target = self._resolve("/index.html")
            if target is None:
                self._fail(404, "not found")
                return
        try:
            body = target.read_bytes()
        except OSError:
            self._fail(404, "not found")
            return
        suffix = target.suffix.lower()
        ctype = EXTRA_TYPES.get(suffix) or mimetypes.guess_type(target.name)[0] \
            or "application/octet-stream"
        self._send(200, body, ctype)

    @staticmethod
    def _resolve(path: str) -> Path | None:
        if "\x00" in path:
            return None
        relative = path.lstrip("/") or "index.html"
        try:
            candidate = (PUBLIC_DIR / relative).resolve()
            candidate.relative_to(PUBLIC_DIR)      # blocks ../ traversal
        except (ValueError, OSError):
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
        return candidate if candidate.is_file() else None


def _constant_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def main() -> int:
    for suffix, ctype in EXTRA_TYPES.items():
        mimetypes.add_type(ctype.split(";")[0], suffix)

    if not PUBLIC_DIR.is_dir():
        log(f"!! public directory not found: {PUBLIC_DIR}")
        return 1

    if SEED_ENABLED:
        try:
            LIBRARY.seed_from(SEED_DIR)
        except Exception as exc:  # a bad document must not stop the server
            log(f"!! seed import failed: {type(exc).__name__}: {exc}")

    httpd = Server((HOST, PORT), Handler)

    def shutdown(signum: int, _frame: object) -> None:
        log(f"signal {signum} — shutting down")
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    meta = LIBRARY.meta()
    log(f"Media Tracker {VERSION}")
    log(f"  listening   http://{HOST}:{PORT}")
    log(f"  public      {PUBLIC_DIR}")
    log(f"  library     {LIBRARY_PATH} ({meta['items']} items, rev {meta['rev']})")
    log(f"  seeds       {SEED_DIR}"
        f" ({'on' if SEED_ENABLED else 'off'}, {len(LIBRARY.data.get('seeds') or {})} imported)")
    log(f"  lookups     {'on' if NET_ENABLED else 'off'}"
        f"{' (tmdb key)' if TMDB_KEY else ''}{' (omdb key)' if OMDB_KEY else ''}")
    log(f"  auth        {'token required' if TOKEN else 'open'}")
    if ENV_COUNT:
        log(f"  settings    {ENV_FILE} ({ENV_COUNT} read)")
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
