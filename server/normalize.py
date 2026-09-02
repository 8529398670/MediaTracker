"""The server is the authority on shape.

Whatever a browser, a document or a provider hands us, it is put through
here before it reaches the library: fields clamped, types coerced, genres
folded onto one vocabulary. Nothing downstream re-checks any of it.
"""

from __future__ import annotations

import re
import urllib.parse
import uuid
from datetime import datetime

from config import ITEM_TYPES, STATUSES, now_iso


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


# --------------------------------------------------------------------------
# genres
# --------------------------------------------------------------------------
#
# Six providers name the same genre six ways: TMDB says "Science Fiction" for
# film and "Sci-Fi & Fantasy" for television, Wikidata says "science fiction
# film", Open Library says "adventure fiction", OMDb says "Sci-Fi".  Left
# alone they never merge, so a genre filter finds a third of what it should.
# Everything is folded to one vocabulary on the way in.

# An alias may answer with more than one genre: TMDB's television list pairs
# genres that its film list keeps apart, and unpicking them is the whole point.
GENRE_ALIASES = {
    "sci-fi": ["Science Fiction"],
    "scifi": ["Science Fiction"],
    "sci fi": ["Science Fiction"],
    # Spelled out, so that stripping the " fiction" suffix off "science
    # fiction film" lands on something rather than on "Science".
    "science fiction": ["Science Fiction"],
    "speculative fiction": ["Science Fiction"],
    "sci-fi & fantasy": ["Science Fiction", "Fantasy"],
    "action & adventure": ["Action", "Adventure"],
    "war & politics": ["War"],
    "romantic comedy": ["Romance", "Comedy"],
    "rom-com": ["Romance", "Comedy"],
    "romcom": ["Romance", "Comedy"],
    "musical": ["Music"],
    "biography": ["Biography"],
    "biographical": ["Biography"],
    "historical": ["History"],
    "history": ["History"],
    "tragedy": ["Drama"],
    "melodrama": ["Drama"],
    "kids": ["Family"],
    "children": ["Family"],
    "children's story": ["Family"],
    "childrens": ["Family"],
    "suspense": ["Thriller"],
    "detective": ["Mystery"],
    "whodunit": ["Mystery"],
    "film noir": ["Crime"],
    "noir": ["Crime"],
    "thriller": ["Thriller"],
    "docudrama": ["Documentary"],
    "tv movie": ["TV Movie"],
    "new-adult": ["Young Adult"],
    "new adult": ["Young Adult"],
    "young adult": ["Young Adult"],
    "coming-of-age": ["Coming of Age"],
    "coming of age": ["Coming of Age"],
}

# Suffixes providers append to a genre that are not part of its name.
# "science fiction" survives: only a trailing word is taken, and only when
# something is left in front of it.
GENRE_SUFFIXES = (" film", " films", " movie", " movies", " genre",
                  " series", " show", " programme", " program", " fiction")


def _title_word(word: str) -> str:
    """Capitalise without breaking an apostrophe: str.title() gives "Children'S".

    Hyphenated words get both halves — "film-noir" is "Film-Noir", not
    "Film-noir".
    """
    def once(part: str) -> str:
        for i, ch in enumerate(part):
            if ch.isalpha():
                return part[:i] + ch.upper() + part[i + 1:]
        return part
    return "-".join(once(p) for p in word.split("-"))


def _alias(key: str) -> list[str] | None:
    """The alias for a genre, spelled with hyphens or without."""
    for form in (key, key.replace("-", " ")):
        if form in GENRE_ALIASES:
            return list(GENRE_ALIASES[form])
    return None


def canon_genre(raw: object) -> list[str]:
    """One provider's word for a genre, as nought, one or two of ours."""
    text = re.sub(r"\s+", " ", _s(raw, 64).replace("_", " ")).strip(" -/,")
    if not text:
        return []
    key = text.lower()
    hit = _alias(key)
    if hit is not None:
        return hit

    # Strip the provider's suffix and try again: "science fiction film" is
    # "science fiction", which is an alias; "adventure fiction" is "adventure".
    for suffix in GENRE_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix) + 1:
            key = key[: -len(suffix)].strip()
            hit = _alias(key)
            if hit is not None:
                return hit
            break

    if not key or key in ("film", "fiction", "movie", "unknown", "none"):
        return []
    return [" ".join(_title_word(w) for w in key.split(" "))]


def canon_genres(values: object, limit: int = 6) -> list[str]:
    """A provider's whole genre list, folded, de-duplicated and capped."""
    out, seen = [], set()
    for value in (values or []):
        for name in canon_genre(value):
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append(name)
            if len(out) >= limit:
                return out
    return out


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

    genres = canon_genres(raw.get("genres"), 12)

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
        "genres": genres,
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
