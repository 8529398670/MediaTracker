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
TOKEN = env("MT_TOKEN")
MAX_BODY = int(env("MT_MAX_BODY", str(32 * 1024 * 1024)))
NET_ENABLED = env_flag("MT_ENABLE_NET", True)
IMG_ALLOW_ANY = env_flag("MT_IMG_ALLOW_ANY", False)
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
