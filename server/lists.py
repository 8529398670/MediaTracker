"""The free starting point: Wikipedia's own lists of films, by the year.

Three pages exist for almost every year of American cinema, and between them
they answer the question a metadata provider cannot — *what was there?*

    List of American films of 1949    everything released, with cast and genre
    1949 in film                      the ten that made the most money
    List of 1949 box office …         which film was number one, week by week

They are harvested a page at a time and archived exactly as parsed, under
``data/lists/raw/``.  Nothing is thrown away and nothing is fetched twice: the
merge that follows reads those files, never the network, so the rules for
folding three pages into one film can change without asking Wikipedia again.

The merged result is written a year at a time to ``data/lists/films/1949.json``,
with one lean row per film in ``data/lists/catalogue.json`` beside it: the key,
the year, the score and a folded haystack, which is everything a search or a
filter needs and nothing else.  Both shapes exist for one reason — a century of
these lists is forty-five thousand films and the container has 256 MB.  A query
walks the lean rows, which are small enough to keep in memory, and then reads
the full records for the sixty it is actually going to show.

A fourth kind of source is a *topic*: an ordinary article like `Pre-Code
Hollywood` that is about films rather than a list of them.  There the titles
come from the italic links — Wikipedia's house style for the name of a work —
and each one is checked against its own categories, which is what separates
the films from the magazines and the court cases linked beside them, and
supplies the year while it is there.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import certs
import verdicts
import wiki
from config import LISTS_DIR, NET_ENABLED, log, now_iso
from match import fold
from netio import fetch_json
from normalize import canon_genre

API = "https://en.wikipedia.org/w/api.php"
ARTICLE = "https://en.wikipedia.org/wiki/"

FIRST_YEAR = 1900
LAST_YEAR = datetime.now(timezone.utc).year + 1

RAW_DIR = LISTS_DIR / "raw"
FILMS_DIR = LISTS_DIR / "films"
INDEX_PATH = LISTS_DIR / "index.json"
CATALOGUE_PATH = LISTS_DIR / "catalogue.json"


# --------------------------------------------------------------------------
# the sources
# --------------------------------------------------------------------------

SETS = {
    "american": {
        "label": "Every American film of the year",
        "page": "List of American films of {year}",
        "note": "Title, director, cast, genre and studio for everything released "
                "that year — a few hundred a year, and the spine of the whole thing.",
    },
    "boxoffice": {
        "label": "Number one, week by week",
        "page": "List of {year} box office number-one films in the United States",
        "note": "Which film was top of the US box office each week. A film that "
                "held it for five weeks is a film people actually went to.",
    },
    "yearfilm": {
        "label": "The year in film",
        "page": "{year} in film",
        "note": "The ten highest-grossing films of the year, with what they took, "
                "and who won Best Picture.",
    },
}

# Articles that are about films rather than lists of them. The italic links in
# their prose are the titles they are recommending, which is the whole point.
TOPICS = {
    "pre-code-hollywood": {
        "page": "Pre-Code Hollywood",
        "label": "Pre-Code Hollywood",
        "note": "1929–1934, before the Production Code was enforced.",
    },
    "film-noir": {
        "page": "List of film noir titles",
        "label": "Film noir",
        "note": "The canonical noir list.",
    },
    "screwball": {
        "page": "Screwball comedy",
        "label": "Screwball comedy",
        "note": "The 1930s and 40s comedies of remarriage and fast talking.",
    },
    "new-hollywood": {
        "page": "New Hollywood",
        "label": "New Hollywood",
        "note": "The American auteur years, roughly 1967–1980.",
    },
    "best-picture": {
        "page": "Academy Award for Best Picture",
        "label": "Best Picture winners and nominees",
        "note": "Every film the Academy has put up for the top award.",
    },
    "afi-100": {
        "page": "AFI's 100 Years...100 Movies",
        "label": "AFI's 100 Years…100 Movies",
        "note": "The American Film Institute's canon, both editions.",
    },
    "sight-and-sound": {
        "page": "Sight & Sound",
        "label": "Sight & Sound's greatest films",
        "note": "The critics' poll taken every ten years since 1952.",
    },
}


def source_catalogue() -> dict:
    """What can be harvested, for the front end to offer."""
    return {
        "sets": [{"id": key, **{k: v for k, v in value.items() if k != "page"}}
                 for key, value in SETS.items()],
        "topics": [{"id": key, **value} for key, value in TOPICS.items()],
        "firstYear": FIRST_YEAR,
        "lastYear": LAST_YEAR,
    }


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def _api(params: dict) -> object:
    query = dict(params)
    query.setdefault("format", "json")
    query.setdefault("formatversion", "2")
    return fetch_json(f"{API}?{urllib.parse.urlencode(query)}", timeout=25,
                      limit=8_000_000)


def fetch_wikitext(page: str) -> tuple[str, int, str]:
    """A page's source, as (wikitext, revision, canonical title).

    A page that is not there is not an error worth stopping for — a year the
    box-office lists do not cover simply has no such page.
    """
    payload = _api({"action": "parse", "page": page, "prop": "wikitext|revid",
                    "redirects": "1"})
    if not isinstance(payload, dict) or "parse" not in payload:
        return "", 0, ""
    parse = payload["parse"]
    return (parse.get("wikitext") or "", int(parse.get("revid") or 0),
            parse.get("title") or page)


def article_facts(titles: list[str]) -> dict[str, dict]:
    """Ask Wikipedia what each of these articles is, twenty at a time.

    The categories an article sits in are the cheapest true answer to "is
    this a film, and what year is it": every film article carries
    ``Category:1932 films``, and a magazine, a book or a court case does not.
    The same categories carry the genre, so one round trip for twenty titles
    does the work of three calls each.
    """
    out: dict[str, dict] = {}

    def run(names: list[str]) -> None:
        if not names:
            return
        params = {"action": "query", "prop": "categories", "cllimit": "max",
                  "clshow": "!hidden", "titles": "|".join(names),
                  "redirects": "1"}
        cats: dict[str, list[str]] = {}
        # An article asked for by one name can answer under another, so the
        # redirects and spelling fixes are followed back to what was asked.
        alias: dict[str, str] = {}
        for _ in range(6):
            payload = _api(params)
            if not isinstance(payload, dict):
                break
            answer = payload.get("query") or {}
            for hop in (answer.get("normalized") or []) + (answer.get("redirects") or []):
                alias[str(hop.get("from"))] = str(hop.get("to"))
            for page in answer.get("pages") or []:
                if page.get("missing"):
                    continue
                bucket = cats.setdefault(page.get("title") or "", [])
                for cat in page.get("categories") or []:
                    bucket.append(str(cat.get("title", ""))[9:])
            more = (payload.get("continue") or {}).get("clcontinue")
            if not more:
                break
            params = {**params, "clcontinue": more}

        for name in names:
            landed = name
            for _ in range(4):                    # a redirect to a redirect
                if landed not in alias:
                    break
                landed = alias[landed]
            if landed in cats:
                out[name] = _from_categories(landed, cats[landed])

    batch: list[str] = []
    for name in titles:
        batch.append(name)
        if len(batch) >= 20:
            run(batch)
            batch = []
    run(batch)
    return out


# `Category:1932 films` is on every film article and on nothing else, which
# makes it both the test of whether an article is a film and the answer to
# what year it came out. "Books about film" ends in the word too, and is not
# one — so the year is required, not merely the word.
YEAR_FILMS = re.compile(r"^(\d{4}) (?:[a-z-]+ )?films$")
DECADE_FILMS = re.compile(r"^\d{4}s? ")
SPLIT_GENRE = re.compile(r"\s*[,/;]\s*")

# The app's own genre vocabulary. A category is only worth reading as a genre
# if it lands on one of these: `1930s crime action films` is Crime and Action,
# and `American black-and-white films` is not a genre at all.
FILM_GENRES = {
    "Action", "Adventure", "Animation", "Biography", "Comedy", "Crime",
    "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Music",
    "Mystery", "Romance", "Science Fiction", "Sport", "Sports", "Thriller",
    "War", "Western", "Coming of Age", "Young Adult", "Superhero", "Spy",
    "Disaster", "Heist", "Martial Arts", "Teen", "Erotic", "Satire",
}


def _sweep(phrase: str) -> list[str]:
    """The genres inside a phrase, longest first.

    "crime drama" is Crime and Drama, and one genre called "Crime Drama"
    would never match either; "science fiction" has to stay whole or it
    becomes Science; "american black-and-white" is neither.
    """
    words = DECADE_FILMS.sub("", phrase).replace("-", " ").split()
    out: list[str] = []
    for size in (3, 2, 1):
        for start in range(len(words) - size + 1):
            for genre in canon_genre(" ".join(words[start:start + size])):
                if genre in FILM_GENRES and genre not in out:
                    out.append(genre)
    return out


def genres_from(text: str, strict: bool = False) -> list[str]:
    """A page's genre cell, or a category name, as the app's genres.

    The whole phrase first, since "Film noir" and "Romantic comedy" are known
    compounds that mean something other than their words. Only when that
    lands on nothing the app knows is the phrase taken apart.

    `strict` is for categories, where an unrecognised phrase is not a genre
    that happens to be rare — it is "American black-and-white", and dropping
    it is the point. A genre column says what it means, so there the phrase
    is kept as it was written.
    """
    out: list[str] = []
    for piece in SPLIT_GENRE.split(str(text or "")):
        piece = piece.strip()
        if not piece:
            continue
        whole = canon_genre(piece)
        found = [g for g in whole if g in FILM_GENRES] or _sweep(piece)
        if not found and not strict:
            found = whole
        for genre in found:
            if genre not in out:
                out.append(genre)
    return out[:5]


def _from_categories(title: str, cats: list[str]) -> dict:
    """What an article's categories say it is."""
    years: list[int] = []
    genres: list[str] = []
    for cat in cats:
        low = cat.lower()
        hit = YEAR_FILMS.match(low)
        if hit:
            years.append(int(hit.group(1)))
            continue
        if low.endswith(" films"):
            for genre in genres_from(low[:-6], strict=True):
                if genre not in genres:
                    genres.append(genre)
    return {"article": title, "isFilm": bool(years),
            "year": min(years) if years else None, "genres": genres[:4]}


# --------------------------------------------------------------------------
# turning a page into rows
# --------------------------------------------------------------------------

DISAMBIG = re.compile(r"\s*\((?:[^()]*\b(?:film|movie|serial|miniseries|"
                      r"TV series|19\d\d|20\d\d)\b[^()]*)\)\s*$", re.I)
SPLIT_CAST = re.compile(r"\s*,\s*|\s+and\s+")


ARTICLE_YEAR = re.compile(r"\((?:[^()]*\s)?(1[89]\d\d|20\d\d)(?:\s[^()]*)?\)\s*$")


def display_title(article: str, label: str = "") -> str:
    """The name of the film, without the parenthesis Wikipedia needs."""
    name = (label or article).strip()
    return DISAMBIG.sub("", name).strip() or name


def article_year(article: str) -> int | None:
    """`Joan of Arc (1948 film)` was released in 1948, whoever listed it.

    It turns up on the 1949 box-office list because that is when it was top
    of the box office, and filing it under 1949 would be wrong.
    """
    hit = ARTICLE_YEAR.search(str(article or ""))
    if not hit:
        return None
    year = int(hit.group(1))
    return year if FIRST_YEAR - 20 <= year <= LAST_YEAR else None


# What a list writes in the Title column when it has no title to write: the
# 1946 box-office page says TBD for the sixteen weeks Variety published no
# survey, and sixteen weeks at number one is exactly the wrong answer.
NOT_A_TITLE = {"tbd", "tba", "n/a", "na", "none", "unknown", "no data",
               "not known", "-", "--", "—", "–", "?", ""}


def _first_link(cell: str) -> tuple[str, str]:
    """The film a cell is about, as (article, label).

    Falls back to the cell's plain words when it names something Wikipedia
    has no article for — a list of every film released in a year is full of
    those, and they are still films.
    """
    found = wiki.links(cell)
    if found:
        return found[0]
    text = wiki.text_of(cell)
    return ("", "" if text.strip().lower() in NOT_A_TITLE else text)


def _row(article: str, label: str = "", **fields) -> dict:
    row = {"article": article, "title": display_title(article, label),
           "year": None, "director": "", "cast": [], "genres": [],
           "genreText": "", "studio": "", "notes": "", "rank": None,
           "gross": "", "weeks": 0, "topOfYear": False, "award": ""}
    row.update({k: v for k, v in fields.items() if v not in (None, "", [], 0, False)})
    row["year"] = article_year(article) or row["year"]
    return row


def parse_american(text: str, year: int) -> list[dict]:
    """`List of American films of 1949` — the spine: everything released."""
    rows = []
    for table in wiki.tables(text):
        headers = table["headers"]
        col_title = wiki.column(headers, "title", "film")
        if col_title < 0:
            continue
        # The box-office table at the top of a modern page has a Title column
        # too; it is read by the other recipe, not this one.
        if wiki.column(headers, "rank") >= 0:
            continue
        col_dir = wiki.column(headers, "director", "directed by")
        col_cast = wiki.column(headers, "cast", "cast and crew", "starring")
        col_genre = wiki.column(headers, "genre", "genres")
        col_notes = wiki.column(headers, "notes", "studio", "production company",
                                "distributor")
        for cells in table["rows"]:
            if col_title >= len(cells):
                continue
            article, label = _first_link(cells[col_title])
            name = display_title(article, label)
            if not name or len(name) > 200:
                continue
            pick = lambda i: wiki.text_of(cells[i]) if 0 <= i < len(cells) else ""  # noqa: E731
            genre_text = pick(col_genre)
            cast_text = pick(col_cast)
            # A modern page runs the crew and the cast together in one cell:
            # "Michael Mann (director); … ; Chris Hemsworth, Tang Wei".
            director = pick(col_dir)
            if not director and "(director" in cast_text:
                director = cast_text.split("(director")[0].strip().rstrip(",")
                cast_text = cast_text.split(";")[-1]
            rows.append(_row(
                article or name, label, year=year, director=director,
                cast=[c for c in (p.strip() for p in SPLIT_CAST.split(cast_text))
                      if c and len(c) < 60][:6],
                genres=genres_from(genre_text),
                genreText=genre_text,
                studio=pick(col_notes)[:200],
            ))
    return rows


def parse_boxoffice(text: str, year: int) -> list[dict]:
    """The weekly number one. Weeks held is the popularity signal."""
    tally: dict[str, dict] = {}
    for table in wiki.tables(text):
        col_film = wiki.column(table["headers"], "film", "title")
        if col_film < 0 or wiki.column(table["headers"], "week ending", "week") < 0:
            continue
        for cells in table["rows"]:
            if col_film >= len(cells):
                continue
            article, label = _first_link(cells[col_film])
            # Number one for a week is a film with an article. Anything
            # unlinked here is the page saying it does not know.
            if not article:
                continue
            name = display_title(article, label)
            if not name:
                continue
            key = article
            row = tally.setdefault(key, _row(key, label, year=year))
            row["weeks"] = row.get("weeks", 0) + 1
            # The dagger marks the highest-grossing film of the whole year.
            if "†" in "".join(cells):
                row["topOfYear"] = True
    return sorted(tally.values(), key=lambda r: -r["weeks"])


MONEY = re.compile(r"\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion))?", re.I)


def parse_yearfilm(text: str, year: int) -> list[dict]:
    """`1949 in film` — the ten that took the most, and Best Picture."""
    rows: list[dict] = []
    for table in wiki.tables(text):
        headers = table["headers"]
        col_rank = wiki.column(headers, "rank")
        col_title = wiki.column(headers, "title", "film")
        if col_rank < 0 or col_title < 0:
            continue
        col_money = wiki.column(headers, "domestic rentals", "gross",
                                "domestic gross", "rentals", "worldwide gross")
        col_studio = wiki.column(headers, "distributor", "studio")
        for cells in table["rows"]:
            if col_title >= len(cells):
                continue
            article, label = _first_link(cells[col_title])
            if not article or not display_title(article, label):
                continue
            rank = re.sub(r"\D", "", wiki.text_of(cells[col_rank]))[:3]
            money = ""
            if 0 <= col_money < len(cells):
                hit = MONEY.search(wiki.text_of(cells[col_money]))
                money = hit.group(0) if hit else ""
            rows.append(_row(
                article, label, year=year,
                rank=int(rank) if rank else None, gross=money,
                studio=wiki.text_of(cells[col_studio])
                if 0 <= col_studio < len(cells) else "",
            ))
        break                              # the first ranked table is the one
    rows.extend(_best_picture(text, year))
    return rows


BEST_FILM = re.compile(r"\bbest (?:picture|film|motion picture)\b", re.I)


CEREMONY = re.compile(r"\b(Academy Award|Golden Globe|BAFTA|Palme d'Or|"
                      r"Cannes|New York Film Critics|National Board)", re.I)


def _best_picture(text: str, year: int) -> list[dict]:
    """Whatever the awards table calls Best Picture, if it has one.

    A year's awards table puts one ceremony in each column, so the column a
    winner is in says which award it won — worth carrying, because the
    Academy and the Golden Globes disagree about half the time.
    """
    out = []
    for table in wiki.tables(text):
        if "award" not in (table["section"] + table["caption"]).lower():
            continue
        givers = []
        for header in table["headers"]:
            hit = CEREMONY.search(header)
            givers.append(f"{hit.group(1)} for Best Picture" if hit
                          else "Best Picture")
        for cells in table["rows"]:
            if not cells or not BEST_FILM.search(wiki.text_of(cells[0])):
                continue
            for index, cell in enumerate(cells[1:], start=1):
                for article, label in wiki.links(cell)[:1]:
                    if display_title(article, label):
                        out.append(_row(
                            article, label, year=year,
                            award=givers[index] if index < len(givers)
                            else "Best Picture"))
    return out


def harvest_topic(topic_id: str) -> list[dict]:
    """An article about films: take its italic links and check each one.

    Prose names a work in italics, so ``''[[The Public Enemy]]''`` is a film
    and ``[[Variety (magazine)]]`` beside it is not. The check is the
    article's own categories, which also hand back the year and the genre.
    """
    topic = TOPICS.get(topic_id)
    if not topic:
        return []
    text, revid, title = fetch_wikitext(topic["page"])
    if not text:
        return []

    candidates = topic_candidates(text)
    facts = article_facts(list(candidates)[:600])
    rows = []
    for article, label in candidates.items():
        fact = facts.get(article)
        if not fact or not fact["isFilm"]:
            continue
        rows.append(_row(fact["article"], label, year=fact["year"],
                         genres=fact["genres"]))
    log(f"lists: {title} — {len(rows)} films of {len(candidates)} links")
    return _archive(topic["page"], "topic", 0, revid, title, rows,
                    topic=topic_id)


def topic_candidates(text: str) -> dict[str, str]:
    """Every article a page names as a work, as {article: label}."""
    out: dict[str, str] = {}
    for article, label in wiki.italic_links(text):
        out.setdefault(article, label)
    # A list page states its titles in a table instead; take that column too.
    for table in wiki.tables(text):
        col = wiki.column(table["headers"], "title", "film")
        if col < 0:
            continue
        for cells in table["rows"]:
            if col >= len(cells):
                continue
            for article, label in wiki.links(cells[col])[:1]:
                out.setdefault(article, label)
    return out


PARSERS = {"american": parse_american, "boxoffice": parse_boxoffice,
           "yearfilm": parse_yearfilm}


def harvest(set_id: str, year: int) -> list[dict]:
    """Fetch one year's page of one kind, parse it, and keep it.

    The fetching is here and the reading is above it, so every rule about
    what a column means can be tested against a page saved to disk rather
    than against Wikipedia on the day.
    """
    page = SETS[set_id]["page"].format(year=year)
    text, revid, title = fetch_wikitext(page)
    if not text:
        log(f"lists: no page — {page}")
        return []
    rows = PARSERS[set_id](text, year)
    log(f"lists: {title} — {len(rows)} films")
    return _archive(page, set_id, year, revid, title, rows)


# --------------------------------------------------------------------------
# the archive
# --------------------------------------------------------------------------

def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _read_json(path: Path, fallback: object = None) -> object:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return fallback


def raw_name(set_id: str, year: int, topic: str = "") -> str:
    return f"{set_id}-{topic or year}"


def _archive(page: str, set_id: str, year: int, revid: int, title: str,
             rows: list[dict], topic: str = "") -> list[dict]:
    """Keep the page exactly as it was parsed, then hand the rows on."""
    _write_json(RAW_DIR / f"{raw_name(set_id, year, topic)}.json", {
        "page": page, "title": title, "url": ARTICLE + urllib.parse.quote(
            title.replace(" ", "_")),
        "set": set_id, "topic": topic, "year": year, "revid": revid,
        "fetchedAt": now_iso(), "rows": rows,
    })
    return rows


def load_raw(set_id: str, year: int, topic: str = "") -> dict | None:
    return _read_json(RAW_DIR / f"{raw_name(set_id, year, topic)}.json")


def archived() -> list[dict]:
    """Every page harvested so far, without their rows."""
    out = []
    for path in sorted(RAW_DIR.glob("*.json")):
        page = _read_json(path)
        if not isinstance(page, dict):
            continue
        out.append({k: v for k, v in page.items() if k != "rows"}
                   | {"films": len(page.get("rows") or [])})
    return out


# --------------------------------------------------------------------------
# the merge
# --------------------------------------------------------------------------

def key_of(row: dict) -> str:
    """One film, however many pages mentioned it.

    The Wikipedia article is the identity where there is one — it is what
    tells *The Killers* of 1946 from *The Killers* of 1964, which no amount
    of comparing titles will. A row with no article falls back to its name
    and year.
    """
    article = (row.get("article") or "").strip()
    if article:
        return "w:" + fold(article)
    return "t:" + fold(row.get("title") or "") + "|" + str(row.get("year") or "")


def _blend(into: dict, row: dict, origin: dict) -> None:
    """Fold one page's row into the film it is about."""
    for field in ("director", "studio", "genreText", "gross", "award", "notes"):
        if row.get(field) and not into.get(field):
            into[field] = row[field]
    if row.get("year") and not into.get("year"):
        into["year"] = row["year"]
    if len(row.get("cast") or []) > len(into.get("cast") or []):
        into["cast"] = row["cast"]
    for genre in row.get("genres") or []:
        if genre not in into["genres"]:
            into["genres"].append(genre)
    signals = into["signals"]
    if row.get("weeks"):
        signals["weeks"] = max(signals.get("weeks", 0), row["weeks"])
    if row.get("topOfYear"):
        signals["topOfYear"] = True
    if row.get("rank") and (not signals.get("rank") or row["rank"] < signals["rank"]):
        signals["rank"] = row["rank"]
    if row.get("award"):
        signals["award"] = row["award"]
    if origin.get("topic"):
        topics = signals.setdefault("topics", [])
        if origin["topic"] not in topics:
            topics.append(origin["topic"])
    seen = into["from"]
    stamp = origin["set"] if not origin.get("topic") else f"topic:{origin['topic']}"
    if stamp not in seen:
        seen.append(stamp)


def score(film: dict) -> int:
    """How much of a starting point this one is.

    Not a rating and not a guess at what you will like — that is the next
    tab's job. This is only "how much did the world notice", which is what
    makes a list of four hundred titles a year worth reading at all.
    """
    signals = film.get("signals") or {}
    total = 0
    total += min(int(signals.get("weeks") or 0), 8) * 9
    if signals.get("topOfYear"):
        total += 25
    rank = signals.get("rank")
    if rank:
        total += max(0, 32 - 3 * int(rank))
    if signals.get("award"):
        total += 30
    total += 12 * len(signals.get("topics") or [])
    total += 4 * max(0, len(film.get("from") or []) - 1)
    if film.get("director") and film.get("cast") and film.get("genres"):
        total += 3
    return min(total, 200)


def _shard(year: object) -> Path:
    return FILMS_DIR / f"{year if year else 'undated'}.json"


# The lean version of the catalogue: one short row per film, holding only
# what filtering and ordering need. A century of this is forty-five thousand
# films — reading every year's full records to answer one search would be
# forty-odd megabytes a keystroke, in a container that has 256 of them. So
# the rows below are what a query walks, and the full records are fetched
# only for the sixty that are actually going to be shown.
# Named with the R_ prefix because a bare `TOPICS` here is the module's own
# dictionary of topic articles, and rebinding it to 5 took `/api/lists` out
# entirely — the catalogue call that draws the tabs and the collect sheet.
R_KEY, R_YEAR, R_SCORE, R_HAY, R_GENRES, R_TOPICS, R_FLAGS, R_CAST = range(8)
BOXOFFICE, AWARDED = 1, 2

# The shape of a lean row. A catalogue written by an older build is merged
# again on the next read rather than migrated: the merge takes seconds and
# reads only what is already on disk, so re-deriving is simpler and safer
# than patching rows in place.
LEAN_SHAPE = 2


def _lean(film: dict) -> list:
    signals = film.get("signals") or {}
    flags = 0
    if signals.get("weeks") or signals.get("rank"):
        flags |= BOXOFFICE
    if signals.get("award"):
        flags |= AWARDED
    hay = fold(" ".join([
        film.get("title", ""), film.get("director", ""), film.get("studio", ""),
        film.get("genreText", ""), " ".join(film.get("cast") or []),
        " ".join(film.get("genres") or []),
    ]))
    return [film["key"], film.get("year"), film.get("score", 0), hay,
            [g.lower() for g in film.get("genres") or []],
            list(signals.get("topics") or []), flags,
            # Folded, so "Katharine Hepburn" and "katharine hepburn" are the
            # same person however the row that named her was typed. Kept apart
            # from the haystack because a search for Ford should not have to
            # mean the director when it is the actor that was clicked.
            [fold(name) for name in (film.get("cast") or [])[:12]]]


def rebuild() -> dict:
    """Fold every archived page back into one film list per year.

    Reads only the archive, never the network, so the rules above are free to
    change: rebuilding is seconds, re-fetching a century is an afternoon.

    Done in two passes over spool files rather than in memory. A century of
    these lists is forty-five thousand rows, and holding the archive and the
    merge at once is a hundred megabytes in a container with 256 — so each
    page is read once and its rows written out under the year they belong to,
    and then each year is merged on its own and thrown away.
    """
    spool = LISTS_DIR / ".build"
    _clear_dir(spool)
    spool.mkdir(parents=True, exist_ok=True)

    pages: dict[str, dict] = {}
    for path in sorted(RAW_DIR.glob("*.json")):
        page = _read_json(path)
        if not isinstance(page, dict) or not page.get("rows"):
            continue
        origin = {"set": page.get("set") or "", "topic": page.get("topic") or ""}
        pages[f"{origin['set']}:{origin['topic'] or page.get('year')}"] = {
            "title": page.get("title"), "fetchedAt": page.get("fetchedAt"),
            "films": len(page["rows"])}

        # One page's rows, filed under the years they are actually about: a
        # 1948 film can be number one on the 1949 page.
        byyear: dict[object, list[str]] = {}
        for row in page["rows"]:
            year = row.get("year") or page.get("year") or None
            byyear.setdefault(year, []).append(
                json.dumps({"row": row, "origin": origin}, ensure_ascii=False))
        for year, lines in byyear.items():
            with open(spool / f"{year or 'undated'}.jsonl", "a",
                      encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        page.clear()

    FILMS_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    lean: list[list] = []
    keep = set()

    for path in sorted(spool.glob("*.jsonl")):
        stem = path.stem
        year = int(stem) if stem.isdigit() else None
        films = _merge_year(path, year)
        _write_json(_shard(year), {"year": year, "builtAt": now_iso(),
                                   "films": films})
        keep.add(_shard(year).name)
        counts[stem] = len(films)
        lean.extend(_lean(film) for film in films)
        path.unlink(missing_ok=True)

    # A page deleted from the archive must not leave its year behind.
    for stale in FILMS_DIR.glob("*.json"):
        if stale.name not in keep:
            stale.unlink(missing_ok=True)
    _clear_dir(spool)

    lean.sort(key=lambda r: (-r[R_SCORE], r[R_HAY]))
    _write_json(CATALOGUE_PATH, {"builtAt": now_iso(), "shape": LEAN_SHAPE,
                                 "films": lean})
    index = {"builtAt": now_iso(), "years": counts, "pages": pages}
    _write_json(INDEX_PATH, index)
    _CACHE.clear()
    log(f"lists: merged {len(lean)} films across {len(counts)} years"
        f" from {len(pages)} pages")
    return index


def _merge_year(path: Path, year: object) -> list[dict]:
    """One year's spooled rows, folded into one record per film."""
    bucket: dict[str, dict] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parcel = json.loads(line)
            except ValueError:
                continue
            row, origin = parcel["row"], parcel["origin"]
            key = key_of(row)
            film = bucket.get(key)
            if film is None:
                article = row.get("article") or ""
                film = bucket[key] = {
                    "key": key, "article": article,
                    "title": row.get("title") or "", "year": year,
                    "url": (ARTICLE + urllib.parse.quote(
                        article.replace(" ", "_"))) if article else "",
                    "director": "", "cast": [], "genres": [], "genreText": "",
                    "studio": "", "gross": "", "award": "", "notes": "",
                    "signals": {}, "from": [],
                }
            _blend(film, row, origin)

    films = list(bucket.values())
    for film in films:
        film["score"] = score(film)
    films.sort(key=lambda f: (-f["score"], fold(f["title"])))
    return films


def _clear_dir(path: Path) -> None:
    try:
        for child in path.iterdir():
            child.unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        pass


# --------------------------------------------------------------------------
# reading it back
# --------------------------------------------------------------------------

_CACHE: dict[object, tuple[float, list[dict]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 14
_LEAN: tuple[float, list[list]] = (0.0, [])


def catalogue() -> list[list]:
    """The lean rows, re-read only when the merge has been rebuilt."""
    global _LEAN
    try:
        stamp = CATALOGUE_PATH.stat().st_mtime
    except OSError:
        return []
    with _CACHE_LOCK:
        if _LEAN[0] == stamp:
            return _LEAN[1]
    payload = _read_json(CATALOGUE_PATH, {}) or {}
    rows = payload.get("films") or []
    # Written by a build that knew fewer fields. Merging again is cheap and
    # reads only the archive, so the catalogue heals itself rather than
    # answering queries with rows that cannot satisfy them.
    if rows and payload.get("shape") != LEAN_SHAPE:
        log(f"lists: catalogue is shape {payload.get('shape')}, rebuilding")
        try:
            rebuild()
            payload = _read_json(CATALOGUE_PATH, {}) or {}
            rows = payload.get("films") or []
            stamp = CATALOGUE_PATH.stat().st_mtime
        except OSError as exc:
            log(f"lists: could not rebuild: {exc}")
    with _CACHE_LOCK:
        _LEAN = (stamp, rows)
    return rows


def year_films(year: object) -> list[dict]:
    """One year's merged films, from a small cache of parsed shards."""
    path = _shard(year)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    with _CACHE_LOCK:
        hit = _CACHE.get(year)
        if hit and hit[0] == stamp:
            return hit[1]
    payload = _read_json(path, {}) or {}
    films = payload.get("films") or []
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)), None)
        _CACHE[year] = (stamp, films)
    return films


def full_records(rows: list[list]) -> list[dict]:
    """The whole record for each lean row, in the order given.

    Grouped by year first, so one page of results costs the one or two year
    files it actually spans rather than one file per film.
    """
    wanted: dict[object, set] = {}
    for row in rows:
        wanted.setdefault(row[R_YEAR], set()).add(row[R_KEY])
    found: dict[str, dict] = {}
    for year, keys in wanted.items():
        for film in year_films(year):
            if film["key"] in keys:
                found[film["key"]] = film
    return [found[row[R_KEY]] for row in rows if row[R_KEY] in found]


def coverage() -> dict:
    index = _read_json(INDEX_PATH, {}) or {}
    return {"builtAt": index.get("builtAt", ""),
            "years": index.get("years") or {},
            "pages": index.get("pages") or {},
            "films": sum(int(n) for n in (index.get("years") or {}).values())}


# `notable` needs no sorting: the catalogue is written in that order.
SORTS = {
    "notable": None,
    "title": lambda r: r[R_HAY],
    "year": lambda r: (-(r[R_YEAR] or 0), -r[R_SCORE]),
    "year-asc": lambda r: ((r[R_YEAR] or 9999), -r[R_SCORE]),
}


def wanted_genres(value: object) -> list[str]:
    """However the genres arrived, as a folded list without repeats.

    One `genre=crime,drama`, several `genre=` parameters or a list all mean
    the same thing, and the lean rows hold the names lowercased, so this is
    also where the case a badge was clicked with stops mattering.
    """
    if isinstance(value, str):
        value = value.split(",")
    out: list[str] = []
    for name in value or []:
        name = str(name).strip().lower()
        if name and name not in out:
            out.append(name)
    return out[:12]


def wanted_ratings(value: object) -> list[str]:
    """However the ratings arrived, as a list without repeats.

    The same shape as the genres above, with two ids that are not ratings:
    `none` for what Wikidata says has none, and `unknown` for what has not
    been asked about yet. They are the two thirds of a century of films that
    a picker offering only G through R would silently lose.
    """
    if isinstance(value, str):
        value = value.split(",")
    out: list[str] = []
    for name in value or []:
        name = str(name).strip()
        special = name.lower()
        name = special if special in (certs.NONE, certs.UNKNOWN) else certs.clean(name)
        if name and name not in out:
            out.append(name)
    return out[:12]


def _rating_ids(key: str, answers: dict) -> list[str]:
    """What a film counts as, on the rating scale.

    Three states and not two: rated, known to have none, and never asked —
    told apart here because a filter that folded the last two together would
    call a pass that has not run yet an answer.
    """
    entry = answers.get(key)
    if entry is None:
        return [certs.UNKNOWN]
    return entry[certs.E_RATINGS] or [certs.NONE]


def query(year_from: int = 0, year_to: int = 0, text: str = "",
          topic: str = "", genres: object = (), genre_mode: str = "any",
          actor: str = "", only: str = "", skipped: str = "hide",
          ratings: object = (), sort: str = "notable",
          limit: int = 60, offset: int = 0) -> dict:
    """The merged catalogue, filtered and paged.

    Walks the lean rows, which are in memory, and then reads the full records
    for the page being returned and nothing else.

    Genres combine two ways and the difference is the whole point of asking
    for more than one: `any` is the wider net — crime *or* western, three
    thousand films — and `all` is the narrower one — the crime films that are
    also westerns, of which there are eleven.

    The same walk counts the facets, which is what makes the picker honest:
    each genre is offered with the number of films it would actually find
    under the year and topic showing, and each year with how many it holds
    under the genres showing. A count is worked out with its own filter
    lifted, so the numbers say what *choosing* this would give rather than
    collapsing to what is already chosen.

    Ratings combine one way only. A film holds one or two of them rather than
    the five or six a genre list runs to, so `all of these` would be asking
    for the films that are both G and R — and G *or* PG is what a person
    picking two of them means.

    A film that has been skipped is gone from every one of those numbers, not
    merely from the rows — the point of skipping is that the page gets
    smaller. `skipped="only"` is the other side of it: the same catalogue,
    filtered the same way, but only the ones passed over, so a verdict can be
    looked at again and taken back.
    """
    needle = fold(text)
    wanted = wanted_genres(genres)
    every = genre_mode == "all"
    rated = wanted_ratings(ratings)
    # Copied once rather than looked up under a lock per row: a fill pass may
    # be writing to it while this walk is reading it.
    answers = certs.STORE.snapshot()
    # An actor is matched against the billed cast alone, not the haystack:
    # searching for Ford turns up John Ford's films, and the point of clicking
    # a name on a row is that it means the person standing in the picture.
    billed = fold(actor)
    passed = verdicts.STORE.keys("skip")
    want_skipped = skipped == "only"

    hits: list[list] = []
    genre_counts: dict[str, int] = {}
    year_counts: dict[str, int] = {}
    rating_counts: dict[str, int] = {}

    for row in catalogue():
        if skipped != "all" and (row[R_KEY] in passed) != want_skipped:
            continue
        if topic and topic not in row[R_TOPICS]:
            continue
        if only == "boxoffice" and not row[R_FLAGS] & BOXOFFICE:
            continue
        if only == "awarded" and not row[R_FLAGS] & AWARDED:
            continue
        if needle and needle not in row[R_HAY]:
            continue
        if billed and not any(billed in name for name in _cast_of(row)):
            continue

        year = row[R_YEAR] or 0
        in_years = ((not year_from or year >= year_from)
                    and (not year_to or year <= year_to))
        mine = row[R_GENRES]
        in_genres = (not wanted
                     or (all(g in mine for g in wanted) if every
                         else any(g in mine for g in wanted)))
        certified = _rating_ids(row[R_KEY], answers)
        in_ratings = not rated or any(r in rated for r in certified)

        # Each count is worked out with its own filter lifted and the other
        # two applied, so a number says what *choosing* it would give.
        if in_genres and in_ratings:
            key = str(year) if year else "0"
            year_counts[key] = year_counts.get(key, 0) + 1
        if in_years and in_ratings:
            for genre in mine:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
        if in_years and in_genres:
            for rating in certified:
                rating_counts[rating] = rating_counts.get(rating, 0) + 1
        if in_years and in_genres and in_ratings:
            hits.append(row)

    order = SORTS.get(sort)
    if order:
        hits.sort(key=order)
    limit = max(1, min(limit, 300))
    # The rating travels with the row rather than only with the poster call
    # that follows it: having just filtered by PG-13, seeing it appear on the
    # row a beat after the row is the wrong way round. Copied rather than set
    # on the record, which is the shard cache's and shared with every query.
    page = []
    for film in full_records(hits[offset:offset + limit]):
        found = (answers.get(film["key"]) or ["", []])[certs.E_RATINGS]
        page.append({**film, "ratings": found,
                     "rating": found[0] if found else ""})
    return {"total": len(hits), "offset": offset,
            "films": page,
            "genres": wanted, "genreMode": "all" if every else "any",
            "actor": actor, "ratings": rated,
            "facets": {"genres": genre_facet(genre_counts),
                       "years": year_counts,
                       "ratings": rating_facet(rating_counts)},
            "verdicts": verdicts.STORE.counts(),
            "coverage": coverage()}


def _cast_of(row: list) -> list:
    """A row's billed cast, tolerating one written before there was a field."""
    return row[R_CAST] if len(row) > R_CAST else []


def genre_facet(counts: dict[str, int]) -> list[dict]:
    """The genres present, biggest first, with the spelling to show a person.

    The lean rows keep them folded so a filter never has to care about case;
    a picker does, so the label is put back here rather than in the browser.
    """
    return [{"id": name, "label": name.title(), "count": count}
            for name, count in sorted(counts.items(),
                                      key=lambda kv: (-kv[1], kv[0]))]


def rating_facet(counts: dict[str, int]) -> list[dict]:
    """The ratings present, on the scale rather than biggest first.

    Unlike the genres this one is not sorted by count. G, PG, PG-13, R is a
    scale a person already reads in that order, and shuffling it so that R
    leads because there are more of them makes the picker harder to read, not
    easier. The two that are not ratings go last, where they read as the
    remainder they are.
    """
    def place(name: str) -> tuple:
        if name in (certs.NONE, certs.UNKNOWN):
            return (2, name == certs.UNKNOWN, name)
        if name in certs.ORDER:
            return (0, certs.ORDER.index(name), name)
        return (1, 0, name)

    return [{"id": name, "label": certs.LABELS.get(name, name), "count": counts[name]}
            for name in sorted(counts, key=place)]


# --------------------------------------------------------------------------
# artwork
# --------------------------------------------------------------------------

# What can be said about a film beyond what the year lists printed: its
# poster, its IMDb id and its age rating.
#
# Wikipedia's own page image for an article, which for a film article is
# almost always the poster.
#
# Only the *address* is learned here, and only in memory. The picture itself
# is never fetched by this process and never written to disk: the browser
# loads it straight from Wikimedia and keeps it in its own cache, which is
# the only copy that exists. That is deliberate — a century of these lists is
# forty-five thousand films, and forty-five thousand posters is the one thing
# that certainly does not fit in a container with 256 MB and a data directory
# meant to hold a library, not a picture archive.
#
# A film with no free image is remembered as having none, so a row that came
# up blank once costs nothing the second time it is scrolled past.

FACT_BATCH = 50                      # titles one round of calls will take
FACT_MAX = 6000                      # rows kept before the slate is wiped

_FACTS: dict[str, dict] = {}
_FACTS_LOCK = threading.Lock()

BLANK = {"thumb": "", "imdb": "", "rating": ""}


def _from_store(name: str, thumb: str = "") -> dict:
    """One row's facts, with the two durable ones read off the disk."""
    imdb, ratings = certs.STORE.get(key_of({"article": name}))
    return {"thumb": thumb, "imdb": imdb, "rating": ratings[0] if ratings else "",
            "ratings": ratings}


def facts(articles: list[str], size: int = 200) -> dict[str, dict]:
    """Poster, IMDb id and age rating for each of these articles.

    Fifty films cost two calls at most: one to Wikipedia for the page images
    and one to Wikidata for the identifiers.  Only the poster is always the
    first of those — the identifiers are kept in ``certs.json``, so a film the
    rating pass has already asked about costs nothing here, and once that pass
    has run the second call stops happening at all.

    An article that answers with nothing is remembered as having nothing,
    which is what stops it being asked twice.
    """
    wanted: list[str] = []
    out: dict[str, dict] = {}
    with _FACTS_LOCK:
        for name in articles:
            name = str(name or "").strip()
            if not name:
                continue
            if name in _FACTS:
                out[name] = _FACTS[name]
            elif name not in wanted:
                wanted.append(name)

    if not wanted:
        return out
    # With lookups switched off there is still the rating and the IMDb id for
    # everything the pass reached before they were, which is the whole point
    # of writing them down. Only the poster needs the network.
    if not NET_ENABLED:
        for name in wanted:
            out[name] = _from_store(name)
        return out

    for start in range(0, len(wanted), FACT_BATCH):
        batch = wanted[start:start + FACT_BATCH]
        # Either half failing leaves the other half's answers standing: a row
        # with a poster and no rating is still a better row.
        try:
            thumbs = page_images(batch, size)
        except Exception as exc:
            log(f"lists: page images failed: {type(exc).__name__}: {exc}")
            thumbs = {}
        asking = [name for name in batch
                  if not certs.STORE.known(key_of({"article": name}))]
        if asking:
            try:
                learn(asking)
            except Exception as exc:
                # Not written down: a blip is not the same answer as "no
                # rating", and recording it as one would be permanent.
                log(f"lists: wikidata failed: {type(exc).__name__}: {exc}")
        with _FACTS_LOCK:
            # Bounded rather than evicted one at a time: this is a convenience
            # that costs two calls to rebuild, so the simplest cap will do.
            if len(_FACTS) >= FACT_MAX:
                _FACTS.clear()
            for name in batch:
                _FACTS[name] = _from_store(name, thumbs.get(name, ""))
                out[name] = _FACTS[name]
    return out


def learn(articles: list[str]) -> int:
    """Ask Wikidata about these films and write down what it says.

    Including when it says nothing: a film with no rating is most of a century
    of them, and not recording that is what would make every pass ask about
    every film again. Answers, so the caller can say how many it found.
    """
    found = identifiers(articles)
    rated = 0
    for name in articles:
        known = found.get(name) or {}
        ratings = known.get("ratings") or []
        rated += 1 if ratings else 0
        certs.STORE.put(key_of({"article": name}), known.get("imdb", ""), ratings)
    certs.STORE.flush()
    return rated


# --------------------------------------------------------------------------
# the identifiers
# --------------------------------------------------------------------------

# Wikidata holds the IMDb id (P345) and the MPAA rating (P1657) for a film,
# and the article name is the way in: every film article is the sitelink of
# exactly one Wikidata item, so fifty article names are fifty items without
# having to identify anything.
#
# Asked through the query service rather than `wbgetentities`, and the size is
# the whole reason: `wbgetentities` has no way to ask for two properties, so
# ten films came back as 1.8 MB of every claim anyone ever made about them.
# The same fifty films through a query that names the two properties are 13 KB
# and a quarter of a second — and the rating arrives as the word a person
# reads, "PG-13", instead of an item id that would need looking up in turn.
SPARQL = "https://query.wikidata.org/sparql"

# The sitelink Wikidata stores is the article URL encoded exactly this way,
# and matching it is the whole join — get it wrong and the query is valid,
# fast and empty. Checked against the live service: an apostrophe and an
# ampersand *are* encoded (`Adam%27s_Rib`, `Bill_%26_Ted...`), a bracket, a
# comma, a slash and a colon are not (`Jaws_(film)`, `Fahrenheit_9/11`,
# `Mission:_Impossible_(film)`), and an accent is UTF-8 percent-encoded.
ARTICLE_SAFE = "()_-.,!~*/:"


def identifiers(names: list[str]) -> dict[str, dict]:
    """The IMDb id and age ratings for each article that has them.

    Ratings plural, and that is not pedantry: a film re-rated after a cut
    carries both, and the query answers with one row per value. The one shown
    is the first on the scale, which is the one it is rated now; all of them
    are kept, so a search for what was once X still finds it.
    """
    urls = {}
    for name in names:
        quoted = urllib.parse.quote(name.replace(" ", "_"), safe=ARTICLE_SAFE)
        urls[f"https://en.wikipedia.org/wiki/{quoted}"] = name

    query = (
        "SELECT ?article ?imdb ?ratingLabel WHERE {\n"
        "  VALUES ?article {\n"
        + "".join(f"    <{url}>\n" for url in urls)
        + "  }\n"
        "  ?article schema:about ?film .\n"
        "  OPTIONAL { ?film wdt:P345 ?imdb . }\n"
        "  OPTIONAL { ?film wdt:P1657 ?rating . }\n"
        '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }\n'
        "}"
    )
    payload = fetch_json(
        f"{SPARQL}?format=json&query={urllib.parse.quote(query)}",
        timeout=25, limit=4_000_000)
    if not isinstance(payload, dict):
        return {}

    out: dict[str, dict] = {}
    for row in ((payload.get("results") or {}).get("bindings") or []):
        url = (row.get("article") or {}).get("value") or ""
        name = urls.get(url)
        if not name:
            continue
        # One row per value, so a film with two ratings arrives as two rows
        # and the second must join the first rather than replace it.
        found = out.setdefault(name, {"imdb": "", "rating": "", "ratings": []})
        found["imdb"] = found["imdb"] or _s_value(row.get("imdb"))
        # `clean` drops the item id the label service answers with when an
        # item has no English label, which is not a rating anyone can read.
        rating = certs.clean(_s_value(row.get("ratingLabel")))
        if rating and rating not in found["ratings"]:
            found["ratings"].append(rating)
    for found in out.values():
        found["ratings"] = certs.in_order(found["ratings"])
        found["rating"] = found["ratings"][0] if found["ratings"] else ""
    return out


def _s_value(cell: object) -> str:
    return str((cell or {}).get("value") or "")[:24] if isinstance(cell, dict) else ""


def page_images(names: list[str], size: int = 200) -> dict[str, str]:
    """Fifty articles, one call, answered under the names that were asked.

    Same redirect-following as the category lookup: an article asked for by
    one name answers under another, and the caller only knows the first.
    """
    payload = _api({"action": "query", "prop": "pageimages",
                    "piprop": "thumbnail",
                    "pithumbsize": max(80, min(int(size), 400)),
                    "titles": "|".join(names), "redirects": "1"})
    if not isinstance(payload, dict):
        return {}
    answer = payload.get("query") or {}

    alias: dict[str, str] = {}
    for hop in (answer.get("normalized") or []) + (answer.get("redirects") or []):
        alias[str(hop.get("from"))] = str(hop.get("to"))

    thumb: dict[str, str] = {}
    for page in answer.get("pages") or []:
        source = ((page.get("thumbnail") or {}).get("source") or "")
        if source:
            thumb[str(page.get("title") or "")] = source

    out: dict[str, str] = {}
    for name in names:
        landed = name
        for _ in range(4):            # a redirect to a redirect
            if landed in thumb or landed not in alias:
                break
            landed = alias[landed]
        if landed in thumb:
            out[name] = thumb[landed]
    return out


# --------------------------------------------------------------------------
# the background pass
# --------------------------------------------------------------------------

class Harvester:
    """One pass over a range of years, pausable and resumable.

    Wikimedia asks for about a call a second, so a century of three pages a
    year is a job measured in minutes rather than seconds. It runs in the
    background, archives each page the moment it is parsed, and rebuilds the
    merge at the end — stopping it early loses only the page in flight.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.stopping = False
        self.reset()

    def reset(self) -> None:
        self.running = False
        self.done = 0
        self.total = 0
        self.films = 0
        self.errors = 0
        self.current = ""
        self.started = ""
        self.finished = ""
        self.note = ""

    def status(self) -> dict:
        with self.lock:
            left = max(0, self.total - self.done)
            return {
                "running": self.running, "done": self.done, "total": self.total,
                "films": self.films, "errors": self.errors,
                "current": self.current, "startedAt": self.started,
                "finishedAt": self.finished, "note": self.note,
                # Wikimedia's own pacing is the whole cost: about a second a
                # page, and a topic pays another for every twenty titles.
                "etaSeconds": int(left * 2.4) if self.running else 0,
                "network": NET_ENABLED,
                "coverage": coverage(),
            }

    def start(self, sets: list[str], years: list[int], topics: list[str]) -> dict:
        with self.lock:
            if self.running:
                return self.status()
            if not NET_ENABLED:
                self.note = "lookups are switched off in this container"
                return self.status()
            jobs = [(s, y, "") for y in years for s in sets if s in PARSERS]
            jobs += [("topic", 0, t) for t in topics if t in TOPICS]
            self.reset()
            if not jobs:
                self.note = "nothing to fetch"
                return self.status()
            self.running = True
            self.total = len(jobs)
            self.started = now_iso()
            self.stopping = False
            self.note = f"{len(jobs)} pages queued"
            self.thread = threading.Thread(target=self._work, args=(jobs,),
                                           daemon=True, name="lists")
            self.thread.start()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            self.stopping = True
            self.note = "stopping…"
        return self.status()

    def _work(self, jobs: list[tuple]) -> None:
        log(f"lists: harvesting {len(jobs)} pages")
        try:
            for set_id, year, topic in jobs:
                with self.lock:
                    if self.stopping:
                        break
                    self.current = (TOPICS[topic]["label"] if topic
                                    else SETS[set_id]["page"].format(year=year))
                rows: list[dict] = []
                try:
                    rows = (harvest_topic(topic) if topic
                            else harvest(set_id, year))
                except Exception as exc:            # one bad page, not the pass
                    log(f"lists: {self.current!r} failed:"
                        f" {type(exc).__name__}: {exc}")
                    with self.lock:
                        self.errors += 1
                with self.lock:
                    self.done += 1
                    self.films += len(rows)
                time.sleep(0.05)
        finally:
            with self.lock:
                self.current = "merging…"
            try:
                rebuild()
            except Exception as exc:
                log(f"lists: merge failed: {type(exc).__name__}: {exc}")
            with self.lock:
                self.running = False
                self.stopping = False
                self.current = ""
                self.finished = now_iso()
                self.note = (f"{self.films} films from {self.done} pages"
                             + (f", {self.errors} could not be read"
                                if self.errors else ""))
            log(f"lists: finished — {self.note}")


HARVESTER = Harvester()


# --------------------------------------------------------------------------
# the rating pass
# --------------------------------------------------------------------------

CERT_BATCH = 50                      # films one Wikidata query will take


class Certifier:
    """One pass over the catalogue, asking Wikidata what each film was rated.

    The rating is the one thing on a row that Wikipedia's year lists never
    print, so unlike everything else in Discover it cannot be filtered by
    until it has been fetched — and fetching it for one screenful at a time,
    which is what browsing does, can never make a filter honest.  So this is
    the whole catalogue, fifty films to a query, written to disk as it goes.

    Twenty-eight thousand films is about a quarter of an hour, because
    Wikidata is asked at a call a second like every other Wikimedia host.
    Newest year first, deliberately: the MPA did not exist before November
    1968, so the years where an answer is likely are done while somebody is
    watching, and the long tail of films that were never rated at all runs on
    afterwards.  Stopping it early loses only the query in flight; what has
    been written stays written and the next pass carries on from there.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.stopping = False
        self.reset()

    def reset(self) -> None:
        self.running = False
        self.done = 0
        self.total = 0
        self.found = 0
        self.errors = 0
        self.current = ""
        self.started = ""
        self.finished = ""
        self.note = ""

    def status(self) -> dict:
        with self.lock:
            left = max(0, self.total - self.done)
            running, done, total = self.running, self.done, self.total
            found, errors = self.found, self.errors
            state = {"current": self.current, "startedAt": self.started,
                     "finishedAt": self.finished, "note": self.note}
        # What is left to ask about, which is the number the picker cares
        # about: a rating filter is only as true as the films it has read.
        # Distinct keys and not rows — a film the year lists filed under both
        # its release and a re-release is two rows and one thing to ask about,
        # and counting it twice here would leave the number stuck above zero
        # with nothing left to do.
        films = len({row[R_KEY] for row in catalogue()
                     if str(row[R_KEY]).startswith("w:")})
        counts = certs.STORE.counts()
        return {"running": running, "done": done, "total": total,
                "found": found, "errors": errors, **state,
                # A query is fifty films and about a second and a half of it,
                # nearly all of it Wikidata's own pacing.
                "etaSeconds": int(left * 1.6 / CERT_BATCH) if running else 0,
                "network": NET_ENABLED,
                "films": films, "asked": counts["asked"], "rated": counts["rated"],
                "unknown": max(0, films - counts["asked"])}

    def start(self, scope: str = "missing") -> dict:
        with self.lock:
            if self.running:
                return self.status()
            if not NET_ENABLED:
                self.note = "lookups are switched off in this container"
                return self.status()
            again = scope == "all"
            todo = len({row[R_KEY] for row in catalogue()
                        if str(row[R_KEY]).startswith("w:")
                        and (again or not certs.STORE.known(row[R_KEY]))})
            self.reset()
            if not todo:
                self.note = "every film collected has been asked about"
                return self.status()
            self.running = True
            self.total = todo
            self.started = now_iso()
            self.stopping = False
            self.note = f"{todo} films to ask about"
            self.thread = threading.Thread(target=self._work, args=(again,),
                                           daemon=True, name="certs")
            self.thread.start()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            self.stopping = True
            self.note = "stopping…"
        return self.status()

    def _years(self) -> list[object]:
        """The years collected, newest first, undated ones last."""
        years = sorted((int(y) for y in (coverage().get("years") or {})
                        if str(y).isdigit()), reverse=True)
        return [*years, "undated"]

    def _work(self, again: bool) -> None:
        log(f"lists: rating {self.total} films")
        try:
            for year in self._years():
                if self._batch_year(year, again):
                    break
        finally:
            certs.STORE.flush(force=True)
            with self.lock:
                self.running = False
                self.stopping = False
                self.current = ""
                self.finished = now_iso()
                self.note = (f"{self.found} of {self.done} films have a rating"
                             + (f", {self.errors} could not be asked about"
                                if self.errors else ""))
            log(f"lists: rating pass finished — {self.note}")

    def _batch_year(self, year: object, again: bool) -> bool:
        """One year, fifty films to a query. True if it was told to stop."""
        pending = [film["article"] for film in year_films(year)
                   if film.get("article")
                   and (again or not certs.STORE.known(film["key"]))]
        for start in range(0, len(pending), CERT_BATCH):
            batch = pending[start:start + CERT_BATCH]
            with self.lock:
                if self.stopping:
                    return True
                self.current = f"{year} — {batch[0]}"
            try:
                found = learn(batch)
            except Exception as exc:        # one bad query, not the pass
                log(f"lists: rating {year} failed: {type(exc).__name__}: {exc}")
                with self.lock:
                    self.errors += 1
                continue
            with self.lock:
                self.done += len(batch)
                self.found += found
        return False


CERTIFIER = Certifier()
