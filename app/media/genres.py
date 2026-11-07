"""The one genre vocabulary.

Six providers name the same genre six ways: TMDB says "Science Fiction" for
film and "Sci-Fi & Fantasy" for television, Wikidata says "science fiction
film", Open Library says "adventure fiction", OMDb says "Sci-Fi". Left alone
they never merge, so a genre filter finds a third of what it should.

There are three layers, and all three live here:

  GENRES            what a title stores, a closed list. Everything is folded
                    onto it on the way in: titles, the Discover catalogue,
                    whatever a person types. A word that lands on nothing is
                    dropped; tags are the place for anything free-form.
  GENRE_PARENTS     a specific genre that also counts as a broader one: a
                    film noir turns up under Crime as well.
  GENRE_COMPOUNDS   the names people actually use for a pair. Providers hand
                    back the ingredients, not the dish: no film database
                    carries "Romantic Comedy", they all say Romance and
                    Comedy side by side. So the pair is never stored, it is
                    worked out from what is, which is why it works at once on
                    a library that was filled in years ago.

Two questions come out of that. terms() is everything a title can be found by,
for filters and search: picking Comedy still finds a romantic comedy. labels()
is what a card shows, the shortest honest reading. The browser asks the same
two questions in static/js/media/genres.js, with the rules sent to it in the
library payload, so the tables exist only here.
"""
from __future__ import annotations

import re

# Raise this when a change to the tables below should reach titles already
# stored; app/models/titles.py refolds them on the next start.
VOCABULARY_VERSION = 1

GENRES: tuple[str, ...] = (
    "Action", "Adventure", "Animation", "Anime", "Biography", "Comedy",
    "Coming of Age", "Crime", "Disaster", "Documentary", "Drama", "Epic",
    "Erotic", "Exploitation", "Family", "Fantasy", "Film Noir", "Heist",
    "History", "Horror", "Martial Arts", "Music", "Musical", "Mystery", "News",
    "Propaganda", "Reality", "Romance", "Satire", "Science Fiction", "Soap",
    "Sports", "Spy", "Superhero", "Talk", "Teen", "Thriller", "TV Movie",
    "War", "Western", "Young Adult",
)

GENRE_PARENTS: dict[str, str] = {
    "Film Noir": "Crime",
    "Musical": "Music",
}

# Most used first: a card reads the table in this order and spends each genre
# once, so Romance, Comedy and Drama is a Romantic Comedy and a Drama. Adding
# a line is all a new compound needs. The same name may have two recipes.
GENRE_COMPOUNDS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("Romantic Comedy", ("Romance", "Comedy")),
    ("Comedy Drama", ("Comedy", "Drama")),
    ("Musical Comedy", ("Musical", "Comedy")),
    ("Musical Comedy", ("Music", "Comedy")),
    ("Romantic Drama", ("Romance", "Drama")),
    ("Crime Drama", ("Crime", "Drama")),
    ("War Drama", ("War", "Drama")),
    ("Historical Drama", ("History", "Drama")),
    ("Thriller Drama", ("Thriller", "Drama")),
    ("Musical Drama", ("Musical", "Drama")),
    ("Musical Drama", ("Music", "Drama")),
    ("Adventure Drama", ("Adventure", "Drama")),
    ("Biographical Drama", ("Biography", "Drama")),
    ("Crime Comedy", ("Crime", "Comedy")),
    ("Crime Thriller", ("Crime", "Thriller")),
    ("Mystery Drama", ("Mystery", "Drama")),
    ("Musical Romance", ("Musical", "Romance")),
    ("Musical Romance", ("Music", "Romance")),
    ("Mystery Thriller", ("Mystery", "Thriller")),
    ("Mystery Comedy", ("Mystery", "Comedy")),
    ("Fantasy Comedy", ("Fantasy", "Comedy")),
    ("Crime Mystery", ("Crime", "Mystery")),
    ("Fantasy Drama", ("Fantasy", "Drama")),
    ("Romantic Fantasy", ("Romance", "Fantasy")),
    ("Western Comedy", ("Western", "Comedy")),
    ("Historical Romance", ("History", "Romance")),
    ("Sports Drama", ("Sports", "Drama")),
    ("Action Adventure", ("Action", "Adventure")),
    ("Western Drama", ("Western", "Drama")),
    ("Fantasy Adventure", ("Fantasy", "Adventure")),
    ("Action Drama", ("Action", "Drama")),
    ("Family Comedy", ("Family", "Comedy")),
    ("Coming of Age Drama", ("Coming of Age", "Drama")),
    ("Adventure Comedy", ("Adventure", "Comedy")),
    ("Sci-Fi Horror", ("Science Fiction", "Horror")),
    ("Horror Comedy", ("Horror", "Comedy")),
)

# Other words for a genre in GENRES. An alias may answer with more than one:
# TMDB's television list pairs genres that its film list keeps apart, and
# unpicking them is the whole point.
GENRE_ALIASES: dict[str, list[str]] = {
    "sci-fi": ["Science Fiction"],
    "scifi": ["Science Fiction"],
    "sci fi": ["Science Fiction"],
    "speculative fiction": ["Science Fiction"],
    "sci-fi & fantasy": ["Science Fiction", "Fantasy"],
    "action & adventure": ["Action", "Adventure"],
    "war & politics": ["War"],
    "romantic comedy": ["Romance", "Comedy"],
    "rom-com": ["Romance", "Comedy"],
    "romcom": ["Romance", "Comedy"],
    "romantic": ["Romance"],
    "dramedy": ["Comedy", "Drama"],
    "animated": ["Animation"],
    "cartoon": ["Animation"],
    "musicals": ["Musical"],
    "operetta": ["Musical"],
    "biographical": ["Biography"],
    "biopic": ["Biography"],
    "bio pic": ["Biography"],
    "historical": ["History"],
    "sport": ["Sports"],
    "espionage": ["Spy"],
    "supernatural": ["Fantasy"],
    "sexploitation": ["Exploitation"],
    "tragedy": ["Drama"],
    "melodrama": ["Drama"],
    "dreama": ["Drama"],
    "kids": ["Family"],
    "children": ["Family"],
    "children's": ["Family"],
    "children's story": ["Family"],
    "childrens": ["Family"],
    "suspense": ["Thriller"],
    "detective": ["Mystery"],
    "whodunit": ["Mystery"],
    "noir": ["Film Noir"],
    "docudrama": ["Documentary"],
    "new-adult": ["Young Adult"],
    "new adult": ["Young Adult"],
}

_NAMES = {name.lower(): name for name in GENRES}
# Every name a filter can hold, for putting the capitals back on a folded one.
SPELLING = {**_NAMES, **{label.lower(): label for label, _parts in GENRE_COMPOUNDS}}


def _known(phrase: str) -> list[str]:
    """A phrase that is a genre or an alias of one, as it stands."""
    for form in (phrase, phrase.replace("-", " ")):
        if form in GENRE_ALIASES:
            return list(GENRE_ALIASES[form])
        if form in _NAMES:
            return [_NAMES[form]]
    return []


def _sweep(phrase: str) -> list[str]:
    """The genres inside a phrase, longest first.

    "crime drama film" is Crime and Drama; "science fiction" has to be read
    whole, because Science is nothing; "american black-and-white" is neither,
    and comes back empty.
    """
    words = phrase.replace("-", " ").split()
    out: list[str] = []
    for size in (3, 2, 1):
        for start in range(len(words) - size + 1):
            for genre in _known(" ".join(words[start : start + size])):
                if genre not in out:
                    out.append(genre)
    return out


def canon_genre(raw: object) -> list[str]:
    """One provider's word for a genre, as none, one or several of ours."""
    text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    text = re.sub(r"[\s–—_]+", " ", text.strip()[:64]).strip(" -/,").lower()
    return _known(text) or _sweep(text)


def canon_genres(values: object, limit: int = 6) -> list[str]:
    """A provider's whole genre list, folded, de-duplicated and capped."""
    out: list[str] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        for name in canon_genre(value):
            if name in out:
                continue
            out.append(name)
            if len(out) >= limit:
                return out
    return out


def terms(genres: list[str]) -> list[str]:
    """Everything a title can be found by: what it stores, what that counts
    as, and every compound the two add up to."""
    out = list(genres)
    for name in genres:
        parent = GENRE_PARENTS.get(name)
        if parent and parent not in out:
            out.append(parent)
    have = set(out)
    for label, parts in GENRE_COMPOUNDS:
        if have.issuperset(parts) and label not in out:
            out.append(label)
    return out


def rules() -> dict[str, object]:
    """The tables, as the browser takes them."""
    return {"parents": GENRE_PARENTS, "compounds": [[label, list(parts)] for label, parts in GENRE_COMPOUNDS]}
