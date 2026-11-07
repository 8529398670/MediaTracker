"""The provider code speaks the old app's field names (imdbId, wikiUrl,
poster...). This is the one place they are translated, in both directions,
and where provider values are cleaned to this app's rules on the way in."""
from __future__ import annotations

from typing import Any

from app.media import normalize

OLD_TO_NEW = {
    "poster": "poster_url",
    "imdbId": "imdb_id",
    "wikiUrl": "wiki_url",
    "appleTv": "apple_tv",
    "sourceId": "source_id",
    "extRating": "ext_rating",
}
NEW_TO_OLD = {new: old for old, new in OLD_TO_NEW.items()}


def to_old(title: dict[str, Any]) -> dict[str, Any]:
    out = {NEW_TO_OLD.get(name, name): value for name, value in title.items()}
    out["poster"] = title.get("poster_url") or ""
    return out


def from_old(found: dict[str, Any]) -> dict[str, Any]:
    """Provider results, renamed and cleaned. Unknown fields are dropped."""
    renamed = {OLD_TO_NEW.get(name, name): value for name, value in (found or {}).items()}
    link = str((found or {}).get("link") or "")
    if not renamed.get("wiki_url") and "wikipedia.org/wiki/" in link:
        renamed["wiki_url"] = link
    return {name: value for name, value in normalize.clean_title_fields(renamed).items() if not normalize.is_empty(value)}


def candidate(row: dict[str, Any]) -> dict[str, Any]:
    """A lookup candidate for the browser: this app's names, a same-origin
    poster path, and the provider's own bits (score, why) passed through."""
    from app.reference.images import CACHE

    title = from_old(row)
    title["title"] = normalize.text(row.get("title"), 400)
    title["type"] = normalize.type_id(row.get("type") or "movie")
    out: dict[str, Any] = {"fields": title}
    out["poster"] = CACHE.path_for(title.get("poster_url") or "")
    for extra in ("imdbScore", "votes", "_score", "_title_score", "why", "source", "kind", "url"):
        if extra in row:
            out[extra.lstrip("_")] = row[extra]
    return out
