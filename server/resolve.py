"""One input, one answer.

The importer's job is to turn whatever was pasted into a real title with real
artwork, and to do it without asking anything back. What arrives might be

    The weather girl - 2009
    https://www.imdb.com/title/tt1085515/fullcredits/
    O Brother , Where Art Though
    letterboxd.com/film/weather-girl/

so this module is arranged in two halves. `identify` reads a link and comes
back with an exact identity — an IMDb id, a TMDB id, a Wikipedia article —
and an exact id never needs matching at all. `search` handles everything
else: it asks the providers several ways, scores what comes back — with the
measures in match.py — and picks a winner or admits it has none.

Nothing here writes to the library; it only answers what a title is.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from difflib import SequenceMatcher
from functools import lru_cache

from config import NET_ENABLED, TMDB_KEY, log
from match import (ARTICLE, CERTAIN, FLOOR, STOP_WORDS, confident, fold,
                   rank, similarity)
from netio import BREAKER, fetch_json, fetch_text, proxy_img
from normalize import _s, canon_genres
from providers import (TMDB_GENRES, prov_openlibrary, prov_tvmaze,
                       prov_wikipedia, strip_tags, year_of)
from seed import split_title


# --------------------------------------------------------------------------
# asking TMDB several ways
# --------------------------------------------------------------------------
#
# TMDB's search is close to exact: "The Weather Girl" finds nothing at all
# while "Weather Girl" finds the film, and "The Prince and Me 4" finds nothing
# while "The Prince & Me 4" finds it. One query is therefore not a search, it
# is a coin toss — so the title is asked several ways, cheapest first, and the
# ladder stops as soon as something certain comes back.


# Two things a document wraps round a title, which no provider files it under.
# They shape what is *asked for*, not what counts as a match.
#
#   Practical "chic suspense" pick: The Thomas Crown Affair
#   Planet Earth series
#
# A quoted phrase or a suggesting word before the colon marks the first;
# "Star Wars: A New Hope" has neither and is left alone. "movie" and "film"
# are absent from the second on purpose — "The Lego Movie" is called that.
PROSE_LEAD = re.compile(
    r"^(?=[^:]*(?:[\"“”\']|\b(?:picks?|options?|choices?|recs?|recommendations?"
    r"|suggestions?|alternatives?|notes?|ideas?|watch|try|maybe)\b))"
    r"[^:]{4,60}:\s*(?=\S)", re.I)

MEDIUM_TAIL = re.compile(
    r"\s+(?:the\s+)?(?:tv\s+|television\s+)?(?:series|serial|miniseries|"
    r"mini-series|docuseries|documentary|trilogy|saga|franchise|collection|"
    r"boxset|box\s+set|anthology)$", re.I)


def _trim(pattern: "re.Pattern", text: str) -> str:
    cut = pattern.sub("", str(text or ""), count=1).strip()
    return cut if len(cut) >= 3 else str(text or "")


def strip_prose(text: str) -> str:
    return _trim(PROSE_LEAD, text)


def medium_off(text: str) -> str:
    return _trim(MEDIUM_TAIL, text)


def subtitle_off(text: str) -> str:
    cut = re.split(r"\s*[:–—]\s+|\s+-\s+", str(text or ""), maxsplit=1)[0]
    return cut if len(cut) >= 3 else str(text or "")


def variants(title: str) -> list[str]:
    """The same title spelled the ways a provider might have filed it."""
    out: list[str] = []

    def add(text: str) -> None:
        text = re.sub(r"\s{2,}", " ", str(text or "")).strip(" -–—,:;")
        if len(text) >= 2 and text not in out:
            out.append(text)

    add(title)
    add(ARTICLE.sub("", title))

    # An apostrophe TMDB does not have, or has where this does not:
    # "Your's, Mine, and Ours" is filed as "Yours, Mine and Ours".
    if re.search(r"['’]", title):
        add(re.sub(r"['’]", "", title))

    lead = strip_prose(title)
    if lead != title:
        add(lead)
        add(ARTICLE.sub("", lead))

    bare = medium_off(lead)
    if bare != lead:
        add(bare)
        add(ARTICLE.sub("", bare))

    if "&" in title:
        add(title.replace("&", "and"))
    if re.search(r"\band\b", title, re.I):
        add(re.sub(r"\band\b", "&", title, flags=re.I))

    # Stray punctuation from a document written by hand: "O Brother , Where
    # Art Though" has a space before its comma and TMDB matches neither.
    plain = re.sub(r"[^\w\s'&-]+", " ", title)
    add(plain)
    add(ARTICLE.sub("", plain))

    trimmed = subtitle_off(title)
    if fold(trimmed) != fold(title):
        add(trimmed)
        add(ARTICLE.sub("", trimmed))

    # A four-digit number on the end, which a slug from another site appends
    # to tell two films of one name apart. Asked both ways round, because it
    # is just as likely to be part of the name.
    tail = re.match(r"^(.{2,}?)[\s-]+(?:18|19|20)\d{2}$", title)
    if tail:
        add(tail.group(1))
        add(ARTICLE.sub("", tail.group(1)))

    # The words that carry the title, with the small ones dropped. This is
    # what rescues a misspelling: "Colin in Accounts" finds nothing, and
    # "Colin Accounts" finds "Colin from Accounts".
    words = [w for w in re.sub(r"[^\w\s]+", " ", title).split()
             if w.lower() not in STOP_WORDS]
    if 1 < len(words) < 8:
        add(" ".join(words))

    return out[:9]


def _tmdb(path: str, **params: object) -> dict:
    if not TMDB_KEY:
        return {}
    query = {"api_key": TMDB_KEY, "include_adult": "false"}
    query.update({k: v for k, v in params.items() if v not in (None, "")})
    url = f"https://api.themoviedb.org/3/{path}?" + urllib.parse.urlencode(query)
    try:
        found = fetch_json(url)
    except Exception as exc:                    # a provider is never fatal
        BREAKER.record("tmdb", False)
        log(f"resolve: tmdb {path}: {type(exc).__name__}")
        return {}
    BREAKER.record("tmdb", True)
    return found if isinstance(found, dict) else {}


def tmdb_row(raw: dict, media: str = "") -> dict:
    """One TMDB search result, in the shape the rest of the app speaks."""
    media = raw.get("media_type") or media or "movie"
    if media not in ("movie", "tv"):
        return {}
    poster = raw.get("poster_path")
    return {
        "source": "tmdb",
        "sourceId": f"{media}/{raw.get('id')}",
        "tmdbId": raw.get("id"),
        "type": "tv" if media == "tv" else "movie",
        "title": raw.get("title") or raw.get("name") or "",
        "year": year_of(raw.get("release_date") or raw.get("first_air_date") or ""),
        "poster": proxy_img(f"https://image.tmdb.org/t/p/w342{poster}") if poster else "",
        "overview": _s(raw.get("overview"), 2000),
        "genres": canon_genres(TMDB_GENRES[g] for g in (raw.get("genre_ids") or [])
                               if g in TMDB_GENRES),
        "extRating": int(round((raw.get("vote_average") or 0) * 10)) or None,
        "link": f"https://www.themoviedb.org/{media}/{raw.get('id')}",
        "_pop": raw.get("popularity") or 0,
        "_votes": raw.get("vote_count") or 0,
    }


def tmdb_search(query: str, media: str) -> list[dict]:
    """`media` is "movie", "tv", or "multi" for both at once."""
    rows = (_tmdb(f"search/{media}", query=query).get("results") or [])[:20]
    out = [tmdb_row(r, media) for r in rows]
    return [r for r in out if r and r.get("title")]


def tmdb_detail(media: str, ident: object) -> dict:
    """Everything TMDB holds on one title, in one call."""
    if media not in ("movie", "tv") or not str(ident).isdigit():
        return {}
    raw = _tmdb(f"{media}/{ident}", append_to_response=
                "credits,external_ids,release_dates,content_ratings")
    if not raw.get("id"):
        return {}

    row = tmdb_row(raw, media)
    credits = raw.get("credits") or {}
    directors = [c.get("name") for c in (credits.get("crew") or [])
                 if c.get("job") == "Director"]
    creators = [c.get("name") for c in (raw.get("created_by") or [])]

    # US certification first, then whatever the title actually carries.
    certification = ""
    for group in ("release_dates", "content_ratings"):
        for entry in ((raw.get(group) or {}).get("results") or []):
            for release in (entry.get("release_dates") or [entry]):
                value = release.get("certification") or release.get("rating")
                if not value:
                    continue
                if entry.get("iso_3166_1") == "US":
                    certification = value
                    break
                certification = certification or value
            if certification and entry.get("iso_3166_1") == "US":
                break

    row.update({
        "genres": canon_genres(g.get("name") for g in (raw.get("genres") or [])),
        "runtime": raw.get("runtime") or (raw.get("episode_run_time") or [None])[0],
        "creator": ", ".join([m for m in (directors or creators) if m][:2]),
        "cast": [c.get("name") for c in (credits.get("cast") or [])[:12] if c.get("name")],
        "certification": _s(certification, 32),
        "imdbId": (raw.get("external_ids") or {}).get("imdb_id") or raw.get("imdb_id") or "",
        "overview": _s(raw.get("overview"), 2000),
    })
    return {k: v for k, v in row.items() if v not in (None, "", [])}


def tmdb_find(external_id: str, source: str = "imdb_id") -> dict:
    """An exact identity from another site's id. No matching involved.

    This is the whole reason a pasted IMDb link is more reliable than a typed
    title: TMDB indexes IMDb, TVDB and Wikidata ids, so an id that arrives in
    a URL becomes the right title with no guessing at any point.
    """
    found = _tmdb(f"find/{external_id}", external_source=source)
    for key, media in (("movie_results", "movie"), ("tv_results", "tv")):
        rows = found.get(key) or []
        if rows:
            detail = tmdb_detail(media, rows[0].get("id"))
            return detail or tmdb_row(rows[0], media)
    # An episode link points at its series, which is the thing you track.
    for row in (found.get("tv_episode_results") or []) + (found.get("tv_season_results") or []):
        if row.get("show_id"):
            detail = tmdb_detail("tv", row["show_id"])
            if detail:
                return detail
    return {}


# --------------------------------------------------------------------------
# reading a link
# --------------------------------------------------------------------------
#
# A pasted link is the best input there is, because most sites put an id in
# the URL and TMDB can look several of those up directly. Nothing is matched,
# guessed or scored on this path — the answer is either exact or absent.

RX_IMDB_TITLE = re.compile(r"imdb\.com/(?:[a-z]{2}/)?title/(tt\d{6,10})", re.I)
RX_IMDB_NAME = re.compile(r"imdb\.com/(?:[a-z]{2}/)?name/(nm\d{6,10})", re.I)
RX_IMDB_BARE = re.compile(r"^\s*(tt\d{6,10})\s*$", re.I)
RX_TMDB = re.compile(r"themoviedb\.org/(movie|tv)/(\d+)", re.I)
RX_WIKIPEDIA = re.compile(r"([a-z-]+)\.(?:m\.)?wikipedia\.org/wiki/([^?#]+)", re.I)
RX_WIKIDATA = re.compile(r"wikidata\.org/(?:wiki|entity)/(Q\d+)", re.I)
RX_TVMAZE = re.compile(r"tvmaze\.com/shows/(\d+)", re.I)
RX_TVDB = re.compile(r"thetvdb\.com/(?:series|movies)/([\w-]+)", re.I)
RX_OPENLIB = re.compile(r"openlibrary\.org/works/(OL\d+W)", re.I)

# Sites with no public API and no id worth having: what is wanted from these
# is the name of the thing, and the page says it in its own metadata.
RX_SLUG_SITES = re.compile(
    r"(?:letterboxd\.com/film|rottentomatoes\.com/(?:m|tv)|trakt\.tv/(?:movies|shows)"
    r"|justwatch\.com/[a-z]{2}/(?:movie|tv-show|tv-series)"
    r"|metacritic\.com/(?:movie|tv)|myanimelist\.net/anime/\d+"
    r"|anilist\.co/anime/\d+|goodreads\.com/book/show/[\d.]+"
    r"|tv\.apple\.com/[a-z-]+/(?:movie|show)"
    r"|simkl\.com/\w+/\d+|tvtime\.com/[a-z-]+/(?:show|movie)/\d+)"
    r"/?([^?#/]*)", re.I)

RX_URL = re.compile(r"https?://\S+|(?:www\.)?[a-z0-9-]+\.[a-z]{2,}/\S+", re.I)

# Fragments a slug carries that are not part of the name: the site's own row
# id on the front, a season on the end.
#
# A year on the end is deliberately left alone. Sites append one to tell two
# films of a name apart — letterboxd.com/film/parasite-2019 — but "Blade
# Runner 2049" is called that, and there is no telling which is which from the
# slug. Taking it off answers the first case and answers the second one
# wrongly; leaving it on answers the second and merely fails to answer the
# first, which is the better of the two. `variants` asks without it as well.
SLUG_JUNK = re.compile(r"^(?:\d+-)|(?:-season-\d+)$", re.I)


def deslug(slug: str) -> str:
    """`weather-girl` → `Weather Girl`; `39356-weather-girl` → `Weather Girl`."""
    text = urllib.parse.unquote(str(slug or "")).strip("/")
    text = SLUG_JUNK.sub("", text)
    text = re.sub(r"[-_+]+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def og_tags(url: str) -> dict:
    """A page's own idea of what it is about: og:title, og:type, og:image."""
    page = fetch_text(url)
    if not page:
        return {}
    head = page[:200_000]
    out: dict[str, str] = {}
    for match in re.finditer(
            r"<meta\s+[^>]*?(?:property|name)\s*=\s*[\"']([^\"']+)[\"'][^>]*?"
            r"content\s*=\s*[\"']([^\"']*)[\"']", head, re.I | re.S):
        key = match.group(1).lower()
        if key in ("og:title", "og:type", "og:image", "og:description",
                   "twitter:title", "twitter:image") and key not in out:
            out[key] = html.unescape(match.group(2)).strip()
    if "og:title" not in out:
        match = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
        if match:
            out["og:title"] = html.unescape(strip_tags(match.group(1))).strip()
    return out


# What a page's own title has appended to it, which the film's name does not.
SITE_SUFFIX = re.compile(
    r"\s*[|·•·\-–—]\s*(?:letterboxd|rotten tomatoes|imdb|trakt\.tv|trakt|justwatch"
    r"|metacritic|myanimelist\.net|myanimelist|anilist|goodreads|apple tv"
    r"|the movie database|tmdb|wikipedia|tv time|simkl)[^|]*$", re.I)


def page_title(tags: dict) -> str:
    """The name of the work, out of a page title written for a browser tab."""
    text = tags.get("og:title") or tags.get("twitter:title") or ""
    text = SITE_SUFFIX.sub("", text).strip()
    # "Weather Girl (2009) directed by Blayne Weaver • Reviews, film + cast"
    text = re.split(r"\s+(?:directed by|reviews|cast and crew)\b", text,
                    maxsplit=1, flags=re.I)[0]
    return text.strip(" -–—|·•")


def wikidata_imdb_for(article: str, lang: str = "en") -> str:
    """The IMDb id of a Wikipedia article, straight from Wikidata.

    An exact key rather than a search: Wikidata stores the article as a
    sitelink and the IMDb id as P345, so one call turns a pasted Wikipedia
    URL into the same identity a pasted IMDb URL would have given.
    """
    title = urllib.parse.unquote(article).replace("_", " ")
    try:
        found = fetch_json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "format": "json", "props": "claims",
            "sites": f"{lang}wiki", "titles": title, "languages": "en",
        }))
    except Exception:
        return ""
    for entity in ((found or {}).get("entities") or {}).values():
        for claim in ((entity.get("claims") or {}).get("P345") or []):
            value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(value, str) and value.startswith("tt"):
                return value
    return ""


def _trim_url(url: str) -> str:
    """A URL with the sentence's punctuation taken off the end of it.

    A closing bracket is only punctuation when nothing opened it: Wikipedia's
    own article names end in one — `/wiki/Parasite_(2019_film)` — and taking
    it off leaves a link to nothing.
    """
    while url and url[-1] in ".,;:!?\"'":
        url = url[:-1]
    while url and url[-1] in ")]":
        opener = "(" if url[-1] == ")" else "["
        if url.count(opener) >= url.count(url[-1]):
            break
        url = url[:-1]
    return url


def identify(text: str) -> dict:
    """What a pasted link points at, without asking any provider yet.

    Returns `{"site", "id"|"slug"|"article", "url"}`, or `{}` for anything
    that is not a link this knows.
    """
    raw = str(text or "").strip()
    bare = RX_IMDB_BARE.match(raw)
    if bare:
        return {"site": "imdb", "id": bare.group(1).lower(), "url":
                f"https://www.imdb.com/title/{bare.group(1).lower()}/"}

    found = RX_URL.search(raw)
    if not found:
        return {}
    url = _trim_url(found.group(0))
    if not url.lower().startswith("http"):
        url = "https://" + url

    for pattern, site, field in (
            (RX_IMDB_TITLE, "imdb", "id"),
            (RX_IMDB_NAME, "imdb-person", "id"),
            (RX_WIKIDATA, "wikidata", "id"),
            (RX_TVMAZE, "tvmaze", "id"),
            (RX_OPENLIB, "openlibrary", "id"),
            (RX_TVDB, "tvdb", "slug")):
        match = pattern.search(url)
        if match:
            return {"site": site, field: match.group(1), "url": url}

    match = RX_TMDB.search(url)
    if match:
        return {"site": "tmdb", "media": match.group(1).lower(),
                "id": match.group(2), "url": url}

    match = RX_WIKIPEDIA.search(url)
    if match:
        return {"site": "wikipedia", "lang": match.group(1).lower(),
                "article": match.group(2), "url": url}

    match = RX_SLUG_SITES.search(url)
    if match:
        return {"site": "page", "slug": match.group(1), "url": url}

    return {"site": "page", "slug": urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1],
            "url": url}


# --------------------------------------------------------------------------
# the front door
# --------------------------------------------------------------------------

# Which TMDB index a media kind lives in. "multi" is one call covering both,
# which is what an unknown kind wants — asking movie and tv separately costs
# two calls to answer the same question.
MEDIA_FOR = {"movie": ("movie",), "doc": ("movie",),
             "tv": ("tv",), "anime": ("tv",)}
OTHER_MEDIA = {"movie": "tv", "doc": "tv", "tv": "movie", "anime": "movie"}

# Kinds TMDB has never heard of. Old radio serials, games and podcasts are in
# Wikipedia and nowhere else.
OFF_TMDB = {"book", "game", "podcast", "other"}


# What an article's name has in brackets after it. A film or a programme is
# the thing being looked for; its soundtrack and the play it was made from
# are not, and their articles are named the same way.
WIKI_PAREN = re.compile(r"\s*\(([^)]*)\)\s*$")
WIKI_OK_PAREN = re.compile(
    r"^(?:(?:18|19|20)\d{2}\s+)?(?:film|movie|TV series|television series|"
    r"miniseries|series|anime|documentary|video game|novel|book)$", re.I)


def _spelling_ok(title: str, found: str) -> str:
    """A correction, if that is what it is, with its disambiguator removed."""
    if not found:
        return ""
    match = WIKI_PAREN.search(found)
    if match:
        if not WIKI_OK_PAREN.match(match.group(1).strip()):
            return ""                       # a soundtrack, a play, a person
        found = found[: match.start()].strip()
    if not found or fold(found) == fold(title):
        return ""
    # Close enough to be a misspelling rather than a different work. The
    # sequel guard is deliberately not applied here — this is producing a
    # query, and the answer to it still has to survive ranking.
    if SequenceMatcher(None, fold(title), fold(found)).ratio() >= 0.60:
        return found
    return ""


@lru_cache(maxsize=512)
def _wiki_opensearch(title: str) -> tuple[str, ...]:
    """Article names that begin like this one, however it was spelt.

    Kept, because two rungs of the ladder ask for the same thing: the spelling
    check wants the corrected name and the article-identity bridge wants the
    article. Wikipedia is paced at a call a second, so asking twice for one
    title costs more than everything else on that title put together.
    """
    try:
        found = fetch_json("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "opensearch", "format": "json", "limit": 5,
            "namespace": 0, "search": title[:120],
        }))
    except Exception:
        return ()
    if not isinstance(found, list) or len(found) < 2:
        return ()
    return tuple(t for t in found[1] if isinstance(t, str))


def _wiki_didyoumean(title: str) -> str:
    """Wikipedia's own "did you mean", for a title spelt badly enough that
    nothing else has a hope: "the shwashank redemtion"."""
    try:
        found = fetch_json("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "list": "search", "format": "json", "srlimit": 1,
            "srinfo": "suggestion", "srprop": "", "srsearch": title[:120],
        }))
    except Exception:
        return ""
    info = (((found or {}).get("query") or {}).get("searchinfo") or {})
    return _s(info.get("suggestion"), 200)


def wiki_spelling(title: str, kind: str = "any") -> str:
    """What Wikipedia thinks you meant. The spell-checker in this chain.

    TMDB matches titles nearly exactly, so one letter wrong finds nothing at
    all: "O Brother , Where Art Though" comes back empty, and so does "the
    shwashank redemtion". Wikipedia's search tolerates both, so it is asked
    what the title is actually called and the corrected name goes back to
    TMDB for the artwork.

    Three ways of asking, cheapest and most reliable first, because none of
    them answers every case: prefix search knows "Godfathr" is "The
    Godfather"; full-text search knows "Colin in Accounts" is "Colin from
    Accounts", which prefix search does not; and the spelling suggestion
    catches what neither does. Whatever comes back is only ever used as a
    query — the answer to it is still scored against the title as typed.
    """
    for found in _wiki_opensearch(title):
        fixed = _spelling_ok(title, found)
        if fixed:
            return fixed

    try:
        rows = prov_wikipedia(title, kind if kind in ("movie", "tv", "anime",
                                                      "doc", "book") else "any", 4)
    except Exception:
        rows = []
    for row in rows:
        fixed = _spelling_ok(title, row.get("title") or "")
        if fixed:
            return fixed

    return _spelling_ok(title, _wiki_didyoumean(title))


def via_wikipedia_id(title: str, kind: str) -> dict:
    """The last way in, and the most exact: through the article's identity.

    Some titles cannot be typed. TMDB files WALL·E under an interpunct, and
    no spelling of "Wall-E" finds it — not the hyphen, not a space, not the
    letters run together. Wikipedia does find it, Wikidata holds that
    article's IMDb id, and TMDB looks an IMDb id up directly, so three calls
    get there with no matching at any step.

    What comes back is still scored like anything else: this supplies a
    candidate, not a verdict.
    """
    names: list[str] = []
    try:
        for row in prov_wikipedia(title, kind, 3):
            names.append(row.get("sourceId") or row.get("title") or "")
    except Exception:
        pass
    names += list(_wiki_opensearch(title))[:2]

    seen: set[str] = set()
    for name in names:
        key = fold(name)
        if not name or key in seen:
            continue
        seen.add(key)
        if similarity(title, WIKI_PAREN.sub("", name)) < FLOOR:
            continue
        imdb = wikidata_imdb_for(name.replace(" ", "_"))
        if not imdb:
            continue
        row = tmdb_find(imdb)
        if row:
            row.setdefault("imdbId", imdb)
            return row
        if len(seen) >= 2:
            break
    return {}


def _other_rows(title: str, kind: str) -> list[dict]:
    """The keyless providers, for the kinds TMDB does not carry."""
    rows: list[dict] = []
    for name, call in (("openlibrary", lambda: prov_openlibrary(title, 6)),
                       ("tvmaze", lambda: prov_tvmaze(title, 6)),
                       ("wikipedia", lambda: prov_wikipedia(title, kind, 6))):
        if kind == "book" and name == "tvmaze":
            continue
        if kind != "book" and name == "openlibrary":
            continue
        if kind in OFF_TMDB and name == "tvmaze":
            continue
        if BREAKER.is_open(name):
            continue
        try:
            rows += call()
            BREAKER.record(name, True)
        except Exception:
            BREAKER.record(name, False)
    return rows


# A number on the end of a line, when no year was given any other way. It is
# either the year — "the weather girl 2009", which is how people actually type
# one — or part of the name, "Blade Runner 2049". Nothing about the line says
# which, so both readings are kept and the candidates decide.
TRAILING_YEAR = re.compile(r"^(.{2,}?)[\s\-–—]+((?:18|19|20)\d{2})$")


def readings(title: str, year: int | None) -> list[tuple[str, int | None]]:
    """The ways one line can be read. The first is the literal one."""
    out = [(title, year)]
    if year is None:
        match = TRAILING_YEAR.match(title.strip())
        if match:
            out.append((match.group(1).strip(), int(match.group(2))))
    return out


def search(title: str, year: int | None = None, kind: str = "any",
           limit: int = 8) -> tuple[list[dict], str, tuple[str, int | None]]:
    """Everything that might be this title, best first, how it was found, and
    which reading of the line it was found under.

    Providers are asked in order of what they cost and what they know, and
    the ladder stops the moment something certain comes back — which for
    almost every title is the first call.
    """
    pool: dict[tuple, dict] = {}
    via = "search"
    ways = readings(title, year)
    used = ways[0]

    def absorb(rows: list[dict]) -> None:
        for row in rows:
            if not row or not row.get("title"):
                continue
            pool.setdefault((row.get("source"), row.get("sourceId") or row["title"]), row)

    def ranked() -> list[dict]:
        """The candidates under whichever reading they support best.

        "the weather girl 2009" scores far better read as a title and a year
        than as a title ending in a number; "Blade Runner 2049" scores better
        the other way round. Ranking is free — it is the same pool of
        candidates scored twice — so the line does not have to be guessed at
        before the providers are asked.
        """
        nonlocal used
        rows: list[dict] = []
        for way in ways:
            scored = rank(list(pool.values()), way[0], way[1], kind)
            if scored and (not rows or scored[0]["_score"] > rows[0]["_score"]):
                rows, used = scored, way
        return rows

    def settled(rows: list[dict]) -> bool:
        """Good enough to stop spending provider calls on.

        The year has to agree as well as the name. A perfect name with the
        wrong year is the ordinary case of two different works sharing one
        title, and stopping there is how "Harley Quinn" becomes a direct-to-
        video special instead of the series the year plainly says it is.
        """
        if not rows or rows[0]["_title_score"] < CERTAIN:
            return False
        chosen_title, chosen_year = used
        found = rows[0].get("year")
        if chosen_year and (not found or abs(found - chosen_year) > 1):
            return False
        return confident(rows, chosen_year)

    queries = variants(title)
    on_tmdb = TMDB_KEY and kind not in OFF_TMDB
    media = MEDIA_FOR.get(kind, ("multi",))

    if on_tmdb:
        for query in queries:
            for one in media:
                absorb(tmdb_search(query, one))
            if settled(ranked()):
                return ranked()[:limit], via, used

        # Filed under the wrong medium: a film on the TV list finds nothing
        # in TMDB's film index and everything in its television one. The
        # item's own type is never changed by this — only what is searched.
        #
        # This runs whenever the television index has not settled the question
        # rather than only when it came back empty, because the failure it is
        # there to fix looks like a weak answer, not like no answer: searching
        # television for "An Education" finds a French programme with a
        # similar name, and the film is in the other index.
        if kind in OTHER_MEDIA and not settled(ranked()):
            was = [r["sourceId"] for r in ranked()[:1]]
            for query in queries[:2]:
                absorb(tmdb_search(query, OTHER_MEDIA[kind]))
            if ranked() and [r["sourceId"] for r in ranked()[:1]] != was:
                via = "other-medium"

    # The keyless providers. For a book, a game, or a radio serial from 1932
    # these are not the fallback — they are the only ones that have heard of
    # it, so they are asked before anything is spent on correcting a spelling
    # there would be nowhere to send.
    if not on_tmdb and not settled(ranked()):
        absorb(_other_rows(title, kind))
        if ranked():
            via = ranked()[0].get("source") or via

    # Nothing yet, or nothing convincing. Have the spelling checked and ask
    # again with what comes back — of whichever providers this kind uses.
    if not settled(ranked()):
        fixed = wiki_spelling(title, kind)
        if fixed:
            was = [r["sourceId"] for r in ranked()[:1]]
            if on_tmdb:
                for one in media:
                    absorb(tmdb_search(fixed, one))
                if not ranked() and kind in OTHER_MEDIA:
                    absorb(tmdb_search(fixed, OTHER_MEDIA[kind]))
            else:
                absorb(_other_rows(fixed, kind))
            if ranked() and [r.get("sourceId") for r in ranked()[:1]] != was:
                via = "spelling"

    # Through the Wikipedia article's own identity, for a title TMDB files
    # under a character that cannot be typed.
    if on_tmdb and not settled(ranked()):
        found = via_wikipedia_id(title, kind)
        if found:
            was = [r["sourceId"] for r in ranked()[:1]]
            absorb([found])
            if [r["sourceId"] for r in ranked()[:1]] != was:
                via = "wikipedia-id"

    # And for a film TMDB simply has no artwork for.
    if on_tmdb and not settled(ranked()):
        absorb(_other_rows(title, kind))
        if ranked() and via == "search" and ranked()[0].get("source") != "tmdb":
            via = ranked()[0].get("source") or via

    rows = ranked()
    return rows[:limit], via, used


def _from_link(found: dict, kind: str) -> tuple[dict, str, str]:
    """An exact identity from a pasted link, where one can be had."""
    site = found.get("site")

    if site == "imdb-person":
        return {}, site, ("that link is a person's IMDb page, not a title — "
                          "paste the film or series page instead")

    if site == "imdb":
        row = tmdb_find(found["id"])
        if row:
            row.setdefault("imdbId", found["id"])
            return row, "imdb-id", ""
        return {}, "imdb-id", ""

    if site == "tmdb":
        row = tmdb_detail(found.get("media") or "movie", found["id"])
        return row, "tmdb-id", ""

    if site == "wikidata":
        row = tmdb_find(found["id"], "wikidata_id")
        return row, "wikidata-id", ""

    if site == "wikipedia":
        imdb = wikidata_imdb_for(found["article"], found.get("lang") or "en")
        if imdb:
            row = tmdb_find(imdb)
            if row:
                row.setdefault("imdbId", imdb)
                row.setdefault("wikiUrl", found["url"])
                return row, "wikipedia-id", ""
        return {}, "wikipedia", ""

    if site == "tvmaze":
        try:
            raw = fetch_json(f"https://api.tvmaze.com/shows/{found['id']}?embed=cast") or {}
        except Exception:
            raw = {}
        imdb = (raw.get("externals") or {}).get("imdb") or ""
        if imdb:
            row = tmdb_find(imdb)
            if row:
                row.setdefault("imdbId", imdb)
                return row, "tvmaze-id", ""
        if raw.get("name"):
            image = (raw.get("image") or {}).get("medium") or ""
            return {
                "source": "tvmaze", "sourceId": str(raw.get("id")), "type": "tv",
                "title": raw["name"], "year": year_of(raw.get("premiered") or ""),
                "poster": proxy_img(image) if image else "",
                "overview": _s(strip_tags(raw.get("summary") or ""), 2000),
                "genres": canon_genres(raw.get("genres")),
                "runtime": raw.get("averageRuntime") or raw.get("runtime"),
                "imdbId": imdb, "link": raw.get("url") or found["url"],
                "cast": [(c.get("person") or {}).get("name")
                         for c in ((raw.get("_embedded") or {}).get("cast") or [])[:12]
                         if (c.get("person") or {}).get("name")],
            }, "tvmaze-id", ""
        return {}, "tvmaze", ""

    if site == "openlibrary":
        rows = _other_rows(deslug(found["id"]), "book")
        return (rows[0] if rows else {}), "openlibrary-id", ""

    return {}, site or "page", ""


def _complete(row: dict) -> dict:
    """The winner, with the fields a search result does not carry.

    Search hands back a name, a year and a poster; the cast, the runtime, the
    age rating and the IMDb id take a second call. It is made for the one
    result that is actually going to be used, and for none of the others.
    """
    if row.get("source") != "tmdb" or not row.get("sourceId") or row.get("cast"):
        return row
    media, _, ident = str(row["sourceId"]).partition("/")
    detail = tmdb_detail(media, ident)
    return {**row, **detail} if detail else row


def resolve(text: str, kind: str = "any", limit: int = 8) -> dict:
    """Whatever was pasted, as the title it refers to.

    One entry point for the whole importer: a name, a name and a year, a bare
    IMDb id, or a link to any of a dozen sites. The answer says how it was
    arrived at and whether it is safe to apply without being asked.
    """
    raw = _s(text, 600)
    out = {"input": raw, "kind": kind, "via": "", "best": None,
           "confident": False, "candidates": [], "note": ""}
    if not raw:
        out["note"] = "nothing to look up"
        return out
    if not NET_ENABLED:
        out["note"] = "lookups are switched off in this container"
        return out

    link = identify(raw)
    title, year, _ = split_title(raw)
    # A document's own wrapping comes off the line before anything is asked
    # or compared: a quoted lead-in and a trailing "series" are the document
    # talking, not part of the name.
    title = medium_off(strip_prose(title))

    if link:
        out["url"] = link.get("url")
        row, via, note = _from_link(link, kind)
        out["via"] = via
        if note:
            out["note"] = note
            return out
        if row:
            row = {k: v for k, v in row.items() if v not in (None, "", [])}
            row["_score"] = 1.0
            row["_title_score"] = 1.0
            out.update({"best": row, "confident": True, "candidates": [row],
                        "query": row.get("title", "")})
            return out

        # No id to be had from that link — read the page's own metadata and
        # carry on as if its title had been typed.
        #
        # The URL is the check on what the page claims. A page assembled in
        # the browser has not filled its own title in yet when it is fetched,
        # so what comes back is the site's name — trakt.tv answers "Trakt
        # Web: Track Your Shows & Movies" for every title it has. Its own
        # address says "colin-from-accounts", which is the answer.
        from_url = deslug(link.get("slug") or link.get("article") or "")
        tags = og_tags(link["url"])
        named = page_title(tags)
        if named and from_url and similarity(from_url, named) < 0.5:
            named = ""
        title, year, _ = split_title(named or from_url)
        if not title:
            out["note"] = "that link did not say what it is about"
            return out
        out["via"] = "page"

    if not title:
        out["note"] = "nothing to look up"
        return out

    rows, via, (title, year) = search(title, year, kind, limit)
    # The line as it was actually read: "the weather girl 2009" comes back as
    # the title and the year separately, which is what goes on the card.
    out["query"] = title
    out["year"] = year

    # How it was found, in whichever terms say the most. "search" is the
    # generic answer, so it does not displace "page" — a link that had to be
    # read for its title is the more useful thing to have been told.
    out["via"] = out["via"] if via == "search" and out["via"] else via

    if rows:
        # Completed first, then judged: the cast is part of the evidence, and
        # a search result does not carry one.
        best = _complete(rows[0])
        out["best"] = best
        out["candidates"] = [best] + rows[1:]
        out["confident"] = confident([best] + rows[1:], year)
        if not out["confident"]:
            out["note"] = ("more than one title matches — pick the right one"
                           if len(rows) > 1 else "close, but not certain")
    else:
        out["note"] = "nothing matched that"
    return out
