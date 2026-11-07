"""The server is the authority on shape.

Whatever a browser, an API key, a provider or the legacy importer hands us is
put through here before it reaches the library: fields clamped, types
coerced, genres folded onto one vocabulary. Nothing downstream re-checks any
of it.

A title is split in two. The *title* fields are shared by the whole family
(what the thing is: its name, year, poster, cast). The *state* fields are one
person's relationship with it (queued, watched, rated, loved). Each has its
own cleaner, and an unknown field is dropped rather than stored.
"""
from __future__ import annotations

import re
import urllib.parse
import uuid
from datetime import datetime
from typing import Any, Callable

from app.media.genres import canon_genres

STATUSES = ("queue", "watching", "watched", "dropped")
BUILTIN_TYPES = ("movie", "tv")

# What a type can be looked up as. A type made up in the app ("radio-drama")
# says which of these it is closest to.
LOOKUP_KINDS = ("movie", "tv", "anime", "doc", "book", "game", "podcast", "music", "other")

# What a type the app made up is called inside: "stand-up-comedy".
TYPE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
APPLE_TV = re.compile(r"^(?:movie|show)/umc\.c[a-z]{2}\.[a-z0-9]{10,40}$")
IMDB_ID = re.compile(r"^tt\d{5,10}$")
TITLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

MAX_TAGS = 40
MAX_LINKS = 40
MAX_CAST = 20
MAX_GENRES = 12


# ---------------------------------------------------------------------------
# scalar cleaners
# ---------------------------------------------------------------------------


def text(value: object, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()[:limit]


def bounded_int(value: object, low: int, high: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def iso(value: object) -> str | None:
    raw = text(value, 40)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.isoformat()


def url(value: object) -> str:
    raw = text(value, 2000)
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    return raw if parsed.scheme in ("http", "https") and parsed.netloc else ""


def type_id(value: object) -> str:
    raw = text(value, 32).lower()
    return raw if TYPE_ID.fullmatch(raw) else "movie"


def apple_tv(value: object) -> str:
    """Where a title is on Apple TV: movie/<id> or show/<id>, the end of a
    tv.apple.com link. Anything else is dropped."""
    raw = text(value, 80)
    return raw if APPLE_TV.match(raw) else ""


def imdb_id(value: object) -> str:
    raw = text(value, 16)
    return raw if IMDB_ID.match(raw) else ""


def tags(values: object) -> list[str]:
    out: list[str] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        clean = re.sub(r"\s+", "-", text(value, 48).lower().lstrip("#"))
        if clean and clean not in out:
            out.append(clean)
        if len(out) >= MAX_TAGS:
            break
    return out


def links(values: object) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for link in values if isinstance(values, (list, tuple)) else []:
        if isinstance(link, str):
            link = {"url": link}
        if not isinstance(link, dict):
            continue
        address = url(link.get("url"))
        if address:
            out.append({"label": text(link.get("label"), 120), "url": address})
        if len(out) >= MAX_LINKS:
            break
    return out


def people(values: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, (list, tuple)) else []:
        name = text(value, 120)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
        if len(out) >= MAX_CAST:
            break
    return out


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------

# Every field a person (or an API key) may set on a title, with its cleaner.
# Book-keeping fields (added_at, updated_by, rev, deleted_at...) are not here:
# the server sets those, never the caller.
TITLE_FIELDS: dict[str, Callable[[object], Any]] = {
    "title": lambda v: text(v, 400),
    "year": lambda v: bounded_int(v, 1870, 2200),
    "type": type_id,
    "tags": tags,
    "links": links,
    "notes": lambda v: text(v, 20000),
    "poster_url": url,
    "overview": lambda v: text(v, 4000),
    "runtime": lambda v: bounded_int(v, 1, 100000),
    "genres": lambda v: canon_genres(v, MAX_GENRES),
    "creator": lambda v: text(v, 300),
    "cast": people,
    "certification": lambda v: text(v, 32),
    "source": lambda v: text(v, 32),
    "source_id": lambda v: text(v, 120),
    "imdb_id": imdb_id,
    "wiki_url": url,
    "apple_tv": apple_tv,
    "ext_rating": lambda v: bounded_int(v, 0, 100),
    "catalogue_key": lambda v: text(v, 300),
}

# The value a field has when nothing is known.
TITLE_EMPTY: dict[str, Any] = {
    "title": "",
    "year": None,
    "type": "movie",
    "tags": [],
    "links": [],
    "notes": "",
    "poster_url": "",
    "overview": "",
    "runtime": None,
    "genres": [],
    "creator": "",
    "cast": [],
    "certification": "",
    "source": "",
    "source_id": "",
    "imdb_id": "",
    "wiki_url": "",
    "apple_tv": "",
    "ext_rating": None,
    "catalogue_key": "",
}

# What the background fill-in may write: provider facts, never a person's
# own words (title, tags, links, notes, type stay theirs).
ENRICH_FIELDS = (
    "year",
    "poster_url",
    "overview",
    "runtime",
    "genres",
    "creator",
    "cast",
    "certification",
    "source",
    "source_id",
    "imdb_id",
    "wiki_url",
    "apple_tv",
    "ext_rating",
)


def clean_title_fields(raw: object) -> dict[str, Any]:
    """Only the known fields the caller sent, each cleaned. A partial update
    sends a few; a create sends whatever it knows and the rest default."""
    if not isinstance(raw, dict):
        return {}
    return {name: clean(raw[name]) for name, clean in TITLE_FIELDS.items() if name in raw}


def new_title_id() -> str:
    return uuid.uuid4().hex


def valid_title_id(value: object) -> bool:
    return isinstance(value, str) and bool(TITLE_ID.match(value))


def is_empty(value: object) -> bool:
    return value in (None, "", [], {})


# ---------------------------------------------------------------------------
# personal state
# ---------------------------------------------------------------------------

STATE_FIELDS: dict[str, Callable[[object], Any]] = {
    "status": lambda v: v if v in STATUSES else None,
    "rating": lambda v: bounded_int(v, 1, 10),
    "heart": bool,
    "note": lambda v: text(v, 4000),
    "watched_at": iso,
}

STATE_EMPTY: dict[str, Any] = {
    "status": None,
    "rating": None,
    "heart": False,
    "note": "",
    "watched_at": None,
}


def clean_state_fields(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {name: clean(raw[name]) for name, clean in STATE_FIELDS.items() if name in raw}


# ---------------------------------------------------------------------------
# types and sources
# ---------------------------------------------------------------------------


def clean_type(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    ident = text(raw.get("id"), 32).lower()
    label = text(raw.get("label"), 40)
    if not TYPE_ID.fullmatch(ident) or not label:
        return None
    lookup = raw.get("lookup")
    return {
        "id": ident,
        "label": label,
        "icon": text(raw.get("icon"), 40),
        "lookup": lookup if lookup in LOOKUP_KINDS else "other",
    }


def clean_source(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    address = url(raw.get("url"))
    if not address:
        return None
    return {
        "url": address,
        "title": text(raw.get("title"), 300),
        "note": text(raw.get("note"), 2000),
        "tags": tags(raw.get("tags"))[:20],
    }
