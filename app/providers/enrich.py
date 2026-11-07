"""Filling in a title: poster, overview, cast, genres, runtime, age rating,
IMDb and Wikipedia links, from whichever provider knows.

Ported from the old app with its chain intact (see ENRICH_CHAIN): it encodes
which provider answers which medium best. Two things changed at the edges:
it runs on this app's network layer (compat.py / net.py), and it is handed a
title in this app's shape and gives its answer back the same way
(fields.py), written with titles.fill_title -- which fills blanks only, or
overwrites provider facts on a refresh, and stands aside if anyone edited the
title meanwhile. A person's own title, tags, notes and links are never
touched; a corrected spelling the old app used to write over the title is
dropped for the same reason.
"""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.parse

from app.media.genres import canon_genres
from app.media.outline import split_title
from app.providers.compat import BREAKER, KEYS, LOOKUP_AS, fetch_json, log, proxy_img
from app.providers.compat import text as _s
from app.providers.compat import url as _url
from app.providers.resolve import _complete, confident, search
from app.providers.sources import prov_itunes, prov_openlibrary, prov_wikipedia, strip_tags, year_of


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
        "genres": canon_genres(name(genre_ids)),
        "imdbId": (_wd_strings(best, "P345") or [""])[0],
        "wikiUrl": wiki,
    }


def enrich_resolve(title: str, year: int | None, kind: str) -> dict:
    """The importer's own matcher, put to work on a title already in hand.

    This is the same code path a paste goes through, so a title that the
    importer can resolve is a title this pass can fill in — asking TMDB
    several ways, checking the spelling against Wikipedia, and looking in the
    other medium when a film has been filed under television.

    Nothing is returned unless the match is a confident one. A card with no
    artwork is a gap; a card with another film's artwork is a lie, and there
    is nothing on it to say which it is.
    """
    if not KEYS.tmdb:
        return {}
    rows, _, (title, year) = search(title, year, kind, 6)
    if not rows:
        return {}

    # Completed before it is judged, because the cast is part of the evidence:
    # deciding whether every word of "Shockproof - Patricia Night" is
    # accounted for needs to know who was in it, and a search result does not
    # say. The title has to be handed over too — without it the check has
    # nothing to compare against but the answer itself, which always agrees.
    best = _complete(rows[0])
    if not confident([best] + rows[1:], year):
        return {}

    return {k: v for k, v in best.items()
            if not k.startswith("_") and v not in (None, "", [])}


def enrich_tmdb(title: str, year: int | None, kind: str) -> dict:
    """The best of the lot, and the only one that needs a (free) key."""
    if not KEYS.tmdb:
        return {}
    media = "tv" if kind in ("tv", "anime") else "movie"
    key = urllib.parse.quote(KEYS.tmdb)
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
        "genres": canon_genres(g.get("name") for g in (row.get("genres") or [])),
        "creator": ", ".join([m for m in makers if m][:2]),
        "extRating": int(round((row.get("vote_average") or 0) * 10)) or None,
    }


def enrich_omdb(title: str, year: int | None, imdb_id: str = "") -> dict:
    """IMDb's own numbers, second hand and legitimately — with a free key."""
    if not KEYS.omdb:
        return {}
    key = urllib.parse.quote(KEYS.omdb)
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
        "genres": canon_genres(_s(row.get("Genre"), 200).split(",")),
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
        "genres": canon_genres(row.get("genres")),
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


def enrich_wikidata_imdb(imdb_id: str) -> dict:
    """The article for a title whose IMDb id we already hold.

    Wikipedia's own search is the weak link in this chain: it wants an article
    title, and the article is called "Giant (1956 film)" while this library
    calls it "Giant". Searching finds The Iron Giant, or nothing, and a title
    that never matches never gets a link no matter how often the pass reruns.

    An IMDb id is an exact key instead. Wikidata stores it as P345 and its
    search understands `haswbstatement:`, so two calls turn an id into the
    article with no guessing at all — which is why this runs before the
    provider that guesses.
    """
    if not imdb_id:
        return {}
    hit = fetch_json(WIKIDATA_API + "?" + urllib.parse.urlencode({
        "action": "query", "list": "search", "format": "json",
        "srsearch": f"haswbstatement:P345={imdb_id}", "srlimit": 1,
    }))
    rows = ((hit or {}).get("query") or {}).get("search") or []
    qid = _s((rows[0] if rows else {}).get("title"), 24)
    if not qid.startswith("Q"):
        return {}
    entity = fetch_json(WIKIDATA_API + "?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": qid, "props": "sitelinks/urls",
        "sitefilter": "enwiki", "format": "json",
    }))
    links = (((entity or {}).get("entities") or {}).get(qid) or {}).get("sitelinks") or {}
    return {"wikiUrl": _url((links.get("enwiki") or {}).get("url"))}


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
    # `resolve` leads wherever TMDB has anything to say: it is the only
    # provider here that asks more than once, and a title the others miss
    # because of a stray comma or a year that was never right is a title it
    # still finds. `wikidata_imdb` sits directly after whatever supplies the
    # IMDb id, because an exact id beats a title search every time.
    "tv":      ("resolve", "tvmaze", "wikidata_imdb", "wikidata", "wikipedia", "omdb"),
    "anime":   ("resolve", "tvmaze", "wikidata_imdb", "wikidata", "wikipedia"),
    "book":    ("openlibrary", "wikidata", "wikipedia"),
    # Wikipedia leads for film: its one-line descriptions ("1941 film by
    # Preston Sturges") carry the year, and the year is what lets Wikidata
    # tell two films of the same name apart.
    # No iTunes here: Apple's public search endpoint stopped returning films,
    # and each call to it costs three seconds of the rate limit.
    "movie":   ("resolve", "wikidata_imdb", "wikipedia", "wikidata", "omdb"),
    "doc":     ("resolve", "wikidata_imdb", "wikipedia", "wikidata", "omdb"),
    "podcast": ("itunes", "wikidata", "wikipedia"),
    "game":    ("wikidata", "wikipedia"),
    "other":   ("wikipedia", "wikidata"),
}

# Where to look when a title turns out to be filed under the wrong medium.
OTHER_MEDIUM = {"movie": "tv", "doc": "tv", "tv": "movie", "anime": "movie"}

# What each provider can answer with — the keys of the dict its enrich_*
# returns. Keep this in step with those functions.
#
# It is here so a pass after one particular field can skip the providers that
# have never carried it. Wikipedia and Open Library return no genre at all,
# and Wikipedia costs two rate-limited calls per title — twice that once the
# other medium is tried as well. On a genre pass over a thousand titles that
# is hours spent on a guaranteed miss.
PROVIDER_FIELDS = {
    "resolve":     {"year", "poster", "cast", "certification", "imdbId",
                    "overview", "runtime", "genres", "creator", "extRating"},
    "tmdb":        {"year", "poster", "cast", "certification", "imdbId",
                    "overview", "runtime", "genres", "creator", "extRating"},
    "omdb":        {"year", "poster", "cast", "certification", "imdbId",
                    "overview", "runtime", "genres", "creator", "extRating"},
    "wikidata":    {"year", "poster", "cast", "certification", "genres",
                    "imdbId", "wikiUrl", "creator"},
    # One thing only, so it is skipped entirely unless a wiki link is wanted.
    "wikidata_imdb": {"wikiUrl"},
    "tvmaze":      {"year", "poster", "cast", "certification", "imdbId",
                    "overview", "runtime", "genres"},
    "itunes":      {"year", "poster", "overview", "runtime", "genres"},
    "wikipedia":   {"year", "poster", "overview", "creator", "wikiUrl"},
    "openlibrary": {"year", "poster", "overview", "creator"},
}

# Every provider is called the same way — (title, year, kind, imdb id) — and
# ignores the arguments it has no use for. OMDb and Wikidata both answer far
# better from an id than from a name, so both are handed it.
ENRICH_PROVIDERS = {
    "resolve": lambda t, y, k, i: enrich_resolve(t, y, k),
    "tmdb": lambda t, y, k, i: enrich_tmdb(t, y, k),
    "omdb": lambda t, y, k, i: enrich_omdb(t, y, i),
    "wikidata": lambda t, y, k, i: enrich_wikidata(t, y, k),
    "wikidata_imdb": lambda t, y, k, i: enrich_wikidata_imdb(i),
    "wikipedia": lambda t, y, k, i: enrich_wikipedia(t, y, k),
    "tvmaze": lambda t, y, k, i: enrich_tvmaze(t, y, k),
    "itunes": lambda t, y, k, i: enrich_itunes(t, y, k),
    "openlibrary": lambda t, y, k, i: enrich_openlibrary(t, y, k),
}


def enrich_item(item: dict, problems: list | None = None,
                replace: tuple = (), want: tuple = ENRICH_CORE, lookup: str = "") -> dict:
    """Everything we can find for one title, as a patch.

    Normally only blanks are filled. `replace` names the fields this pass is
    allowed to overwrite as well — a field being replaced does not count as
    one we already have, so the chain keeps looking until it has a better
    answer for it.

    `want` is what the chain is actually out to get: it stops as soon as it
    holds all of them.  A pass after one particular field has to say so, or
    the chain answers the core in a single TMDB call and goes home with the
    field the pass was for still empty.
    """
    title = item.get("title") or ""
    if not title:
        return {}

    # A title carried in from a document may still have its year stuck to the
    # end of it — "Yes, Minister - 1980" — and no provider has heard of that.
    # The stored title is left exactly as it is; only what is searched for is
    # cleaned up. A year found in the title is trusted over the stored one,
    # since a span written "1980-1984" was read from the wrong end.
    kind = item.get("type") or "movie"
    kind = lookup or LOOKUP_AS.get(kind, kind)
    searchable, in_title, _ = split_title(title)
    if searchable and searchable != title:
        title = searchable
    patch: dict = {}
    problems = problems if problems is not None else []
    have = {k: v for k, v in item.items() if k not in replace}

    # The year to search on. One still glued to the title wins over the one on
    # the item, because a span written "1980-1984" was read from the wrong end
    # by the parser that stored it. What gets written is decided at the foot of
    # this function as usual: a year already on the item is left alone.
    year_hint = in_title or item.get("year")
    if in_title and not item.get("year"):
        patch["year"] = in_title

    # What the record is actually called. Only the resolver's answer counts:
    # it is the one provider here that will not answer unless it is sure, and
    # a name is not a blank to be filled but a correction to be made.
    corrected: list[str] = []

    def walk(as_kind: str, skip: tuple = ()) -> None:
        for name in ENRICH_CHAIN.get(as_kind, ENRICH_CHAIN["other"]):
            if name in skip:
                continue
            left = _needs(have, patch, want)
            if not left:
                return
            if BREAKER.is_open(name):
                continue
            can = PROVIDER_FIELDS.get(name, set())
            # Nothing this pass is after — skip it, unless it can supply the
            # year and the year is still unknown. The year is what lets the
            # providers further down the chain tell two works of the same
            # name apart, so it is worth a call even when it is not the point.
            if not (can & set(left)) and not (
                    "year" in can and not (year_hint or patch.get("year"))):
                continue
            try:
                found = ENRICH_PROVIDERS[name](
                    title, year_hint or patch.get("year"), as_kind,
                    item.get("imdbId") or patch.get("imdbId") or "")
                BREAKER.record(name, True)
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError,
                    ValueError, KeyError, TypeError) as exc:
                # A timeout is the provider's fault and trips the breaker; a
                # bad answer for one title is not.
                offline = isinstance(exc, (urllib.error.URLError, TimeoutError))
                BREAKER.record(name, not offline)
                problems.append(f"{name}: {type(exc).__name__}")
                continue
            _fill(patch, found)
            if found and name == "resolve" and found.get("title"):
                corrected.append(found["title"])
            if found:
                patch.setdefault("source", name)

    walk(kind)

    # Films and television are searched in different places — TMDB has a
    # /search/movie and a /search/tv and neither answers for the other, and
    # TVmaze and Wikidata only know one apiece. So a film filed under TV finds
    # nothing at all, and the lists this library was seeded from have plenty
    # of both filed the wrong way round.
    #
    # Rather than argue with how a title is filed, ask the other side before
    # giving up. This only runs when the declared kind came back without what
    # the pass was after, so it never overrides an answer, only a blank. The
    # item's own type is left exactly as it is: that is yours to set.
    if _needs(have, patch, want) and kind in OTHER_MEDIUM:
        # `resolve` is left out of the second pass: asking the other medium is
        # something it does for itself, so running it again here is the same
        # dozen calls a second time for the same answer. On a title that is in
        # none of the providers — a document line that was never a film — that
        # doubling was the difference between twenty seconds and a minute.
        walk(OTHER_MEDIUM[kind], skip=("resolve",))

    # A field is written when it was asked to be replaced, or when the title
    # has nothing there. A provider never blanks anything: _fill drops empties
    # on the way in, so a refresh that finds nothing leaves what was there.
    out = {}
    for key, value in patch.items():
        if key in replace:
            out[key] = value
        elif key in ENRICH_FIELDS + ("source", "extRating") and not item.get(key):
            out[key] = value

    # And the name, when the record says it differently. A list written by
    # hand is full of "Jossie and the Pussy Cats" and "Champagne for Ceasar",
    # and having found the film there is no reason to keep the misspelling —
    # the whole point of identifying it is to know what it is called. Written
    # only alongside something else, so a title is never rewritten on the
    # strength of a match that produced nothing.
    if out and corrected and corrected[0] != item.get("title"):
        out["title"] = corrected[0]
    return out


# ---------------------------------------------------------------------------
# this app's side
# ---------------------------------------------------------------------------

def lookup_kind(type_id: str, types: list[dict]) -> str:
    for entry in types:
        if entry.get("id") == type_id:
            return entry.get("lookup") or type_id
    return LOOKUP_AS.get(type_id, type_id)


def find_for(title: dict, types: list[dict], refresh: bool = False) -> dict:
    """What the providers know about one title, in this app's field names."""
    from app.providers import fields

    item = fields.to_old(title)
    replace = REFRESH_FIELDS if refresh else ()
    patch = enrich_item(item, replace=replace, want=ENRICH_FIELDS if refresh else ENRICH_CORE, lookup=lookup_kind(title.get("type") or "movie", types))
    return fields.from_old(patch)


def enrich_and_save(store, title: dict, refresh: bool = False) -> dict:  # type: ignore[no-untyped-def]
    """Find and write; returns the previous values of what changed."""
    from app.models import library_cache, titles
    from app.providers import fields

    if not KEYS.network:
        return {}
    found = find_for(title, library_cache.get(store).types, refresh)
    if not found:
        return {}
    overwrite = tuple(fields.OLD_TO_NEW.get(name, name) for name in REFRESH_FIELDS) if refresh else ()
    return titles.fill_title(store, title["id"], found, title.get("updated_at"), overwrite=overwrite)
