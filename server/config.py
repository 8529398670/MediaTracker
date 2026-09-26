"""Settings, paths and the handful of constants everything shares.

Imports nothing of ours, so every other module can import this one.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


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
# Where the app is reached from outside, if it is — the tunnel's address. A
# login link is built on it, so the link works for whoever it is sent to and
# not only on this wifi. Empty: the link is built on wherever the person making
# it is looking at the app from.
PUBLIC_URL = (env("MT_PUBLIC_URL") or "").strip().rstrip("/")
if not re.fullmatch(r"https?://[^/\s]+", PUBLIC_URL):
    PUBLIC_URL = ""
# How long a login link nobody has opened keeps working. The sign-in it makes
# does not expire at all.
try:
    LINK_DAYS = min(3650.0, max(0.01, float(env("MT_LINK_DAYS", "7"))))
except ValueError:
    LINK_DAYS = 7.0
MAX_BODY = int(env("MT_MAX_BODY", str(32 * 1024 * 1024)))
NET_ENABLED = env_flag("MT_ENABLE_NET", True)
IMG_ALLOW_ANY = env_flag("MT_IMG_ALLOW_ANY", False)
# The harvested Wikipedia lists: the raw pages as parsed, and the merge built
# from them. In the data volume, so a rebuilt image keeps them and a century
# of harvesting is paid for once.
LISTS_DIR = DATA_DIR / "lists"
# Artwork is cached in the data volume so it survives a rebuild. Posters are
# drawn in a 52x78 box, so even at three times that for a dense screen they
# are a few kilobytes each; the default budget holds many times the library.
IMG_CACHE_DIR = DATA_DIR / "cache" / "img"
IMG_CACHE_BYTES = int(env("MT_IMG_CACHE_MB", "256")) * 1024 * 1024
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
# same-origin file.  A library item's artwork is pulled through /api/img and
# cached on disk, so it stays same-origin.
#
# Discover's is not, and deliberately: those are forty-five thousand films
# nobody owns yet, and keeping their posters would fill the disk to show
# pictures for rows that are mostly scrolled past.  So the two Wikimedia
# thumbnail hosts are named here and the browser loads those straight, into
# its own cache and nowhere else.  Nothing else is added: not the API host —
# the address lookup goes through this server, so `connect-src` stays 'self'.
CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob: https://thumb.wikimedia.org https://upload.wikimedia.org; "
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
    # Nothing here is for a search engine, the page a stranger gets least of all.
    "X-Robots-Tag": "noindex, nofollow",
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

ITEM_TYPES = {"movie", "tv", "anime", "doc", "book", "game", "audiobook", "podcast", "other"}

# The kinds of search the providers can be asked for. The types in Other are
# the library's own list (``types`` in library.json), made and renamed in the
# app; each one says which of these it is looked up as.
LOOKUP_KINDS = {"movie", "tv", "anime", "doc", "book", "game", "podcast", "other"}
STATUSES = {"queue", "watching", "watched", "dropped"}

# What a kind is to the providers, where that differs from what it is here.
# No catalogue files an audio book apart from the book it was read from, so it
# is looked up as one — Open Library's cover is the audio book's cover.
LOOKUP_AS = {"audiobook": "book"}

MAX_ITEMS = 100_000
MAX_SOURCES = 20_000


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(*parts: object) -> None:
    print(f"[{now_iso()}]", *parts, flush=True)
