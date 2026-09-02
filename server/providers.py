"""Outbound metadata providers, and the search across them.

All free; the API keys are optional upgrades. The browser never talks to any
of these directly — it asks us, so there is no CORS to negotiate, no referrer
leaked, and the page's CSP stays as strict as it is.
"""

from __future__ import annotations

import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from config import NET_ENABLED, OMDB_KEY, TMDB_KEY
from netio import BREAKER, fetch_json, proxy_img
from normalize import _s, canon_genres


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
            "genres": canon_genres(TMDB_GENRES[g] for g in (row.get("genre_ids") or [])
                                   if g in TMDB_GENRES),
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
            "genres": canon_genres([row.get("primaryGenreName")]),
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
            "genres": canon_genres(show.get("genres")),
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
            "genres": canon_genres(row.get("subject"), 4),
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
            "genres": canon_genres(g.get("name") for g in (row.get("genres") or [])),
            "creator": ", ".join((directors or creators)[:2]),
            "imdbId": (row.get("external_ids") or {}).get("imdb_id") or row.get("imdb_id") or "",
            "overview": _s(row.get("overview"), 2000),
        }
    if source == "tvmaze" and ref.isdigit():
        row = fetch_json(f"https://api.tvmaze.com/shows/{ref}?embed=cast") or {}
        return {
            "runtime": row.get("averageRuntime") or row.get("runtime"),
            "genres": canon_genres(row.get("genres")),
            "imdbId": (row.get("externals") or {}).get("imdb") or "",
            "overview": _s(strip_tags(row.get("summary") or ""), 2000),
        }
    return {}
