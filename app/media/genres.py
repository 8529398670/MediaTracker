"""The one genre vocabulary.

Six providers name the same genre six ways: TMDB says "Science Fiction" for
film and "Sci-Fi & Fantasy" for television, Wikidata says "science fiction
film", Open Library says "adventure fiction", OMDb says "Sci-Fi". Left alone
they never merge, so a genre filter finds a third of what it should.
Everything is folded to one vocabulary on the way in -- titles, the Discover
catalogue, and whatever the filter sheet offers -- so there is exactly one
list of genres anywhere in the app.
"""
from __future__ import annotations

import re

# An alias may answer with more than one genre: TMDB's television list pairs
# genres that its film list keeps apart, and unpicking them is the whole point.
GENRE_ALIASES: dict[str, list[str]] = {
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
GENRE_SUFFIXES = (" film", " films", " movie", " movies", " genre", " series", " show", " programme", " program", " fiction")

MEANINGLESS = ("film", "fiction", "movie", "unknown", "none")


def _title_word(word: str) -> str:
    """Capitalise without breaking an apostrophe: str.title() gives
    "Children'S". Hyphenated words get both halves -- "Film-Noir"."""

    def once(part: str) -> str:
        for index, char in enumerate(part):
            if char.isalpha():
                return part[:index] + char.upper() + part[index + 1 :]
        return part

    return "-".join(once(part) for part in word.split("-"))


def _alias(key: str) -> list[str] | None:
    for form in (key, key.replace("-", " ")):
        if form in GENRE_ALIASES:
            return list(GENRE_ALIASES[form])
    return None


def canon_genre(raw: object) -> list[str]:
    """One provider's word for a genre, as nought, one or two of ours."""
    text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    text = re.sub(r"\s+", " ", text.strip()[:64].replace("_", " ")).strip(" -/,")
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
    if not key or key in MEANINGLESS:
        return []
    return [" ".join(_title_word(word) for word in key.split(" "))]


def canon_genres(values: object, limit: int = 6) -> list[str]:
    """A provider's whole genre list, folded, de-duplicated and capped."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, (list, tuple)) else []:
        for name in canon_genre(value):
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append(name)
            if len(out) >= limit:
                return out
    return out
