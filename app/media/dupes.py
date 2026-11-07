"""Duplicates: the same work twice, under two names.

A title typed as "Sunrise" while the library holds "Sunrise: A Song of Two
Humans", or "The Godfather Part 2" against "The Godfather Part II", is the
same film, and a library of family-typed lists collects plenty of those.
This is the looser comparison, used in two places: to warn before something
is added, and to find what has already been added twice.

It says how sure it is, because the two uses want different things. A
warning before an add can afford to mention the 1994 Little Women when the
2019 one is being added; a list of duplicates to clean up cannot.

The type is ignored on purpose: a film filed under TV is exactly the kind of
duplicate nobody would spot by looking.

Pure: titles in, matches out. The client never re-implements this; it asks.
"""
from __future__ import annotations

import re
import unicodedata
import urllib.parse
from datetime import datetime
from typing import Any, Iterable

CERTAIN = 1.0
LIKELY = 0.9
SIMILAR = 0.8
REMAKE = 0.5

ARTICLES = {"the", "a", "an"}
ROMAN = {"ii": 2, "iii": 3, "iv": 4, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "xi": 11, "xii": 12, "xiii": 13}
# Alone, these are words as often as numerals -- "I, Robot", "Malcolm X" --
# so they count only as the last word of a longer title: "Rocky V", "Part I".
ROMAN_TAIL = {"i": 1, "v": 5, "x": 10}
NUMBER = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
ALIAS = {"pt": "part", "vol": "volume", "ch": "chapter", "ep": "episode"}

# A year on the end is the year, not the title: "The weather girl - 2009",
# "Heat (1995)".
TRAILING_YEAR = re.compile(r"(?:\s*[(\[]\s*(?:18|19|20)\d\d\s*[)\]]|\s+[-–—]\s*(?:18|19|20)\d\d)\s*$")
SUBTITLE = re.compile(r"\s*[:–—]\s*|\s+-\s+")
BARE_YEAR = re.compile(r"^(.*\S)\s+((?:18|19|20)\d\d)$")


def fold(value: object) -> str:
    """A string reduced to what two spellings of it have in common: no
    accents, no case, no punctuation, & as "and"."""
    flat = unicodedata.normalize("NFKD", str(value or ""))
    flat = "".join(char for char in flat if not unicodedata.combining(char)).lower()
    flat = flat.replace("&", " and ").replace("+", " and ")
    flat = re.sub(r"['‘’ʼ`´]", "", flat)
    return " ".join(re.sub(r"[^\w\s]+", " ", flat).split())


def title_words(title: object) -> list[str]:
    """A title as the words that decide whether two are the same: folded, the
    year on the end and the articles gone, numbers written one way."""
    words = fold(TRAILING_YEAR.sub("", str(title or ""))).split()
    out: list[str] = []
    for index, word in enumerate(words):
        if word in ARTICLES:
            continue
        if word in ROMAN:
            out.append(str(ROMAN[word]))
        elif word in ROMAN_TAIL and index == len(words) - 1 and len(words) > 1:
            out.append(str(ROMAN_TAIL[word]))
        elif word in NUMBER:
            out.append(str(NUMBER[word]))
        else:
            out.append(ALIAS.get(word, word))
    return out


def norm_key(title: object) -> str:
    return " ".join(title_words(title))


def _main_title(title: object) -> str:
    raw = TRAILING_YEAR.sub("", str(title or ""))
    cut = SUBTITLE.split(raw, maxsplit=1)[0]
    return norm_key(cut) if cut and len(cut) < len(raw) else ""


def _numbers(words: list[str]) -> str:
    return " ".join(sorted(word for word in words if word.isdigit()))


def _distance(a: str, b: str, limit: int) -> int:
    """Edits between two strings, a swap of neighbours counting as one."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i]
        best = i
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + cost)
            if before is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d = min(d, before[j - 2] + 1)
            row.append(d)
            best = min(best, d)
        if best > limit:
            return limit + 1
        before, previous = previous, row
    return previous[len(b)]


def _jaccard(a: list[str], b: list[str]) -> float:
    x, y = set(a), set(b)
    both = len(x & y)
    return both / ((len(x) + len(y) - both) or 1)


def wiki_key(address: object) -> str:
    raw = str(address or "")
    try:
        raw = urllib.parse.unquote(raw)
    except ValueError:
        pass
    return re.sub(r"^https?://(?:en\.m\.|en\.)?", "", raw.lower()).replace("_", " ")


def _year(value: object) -> int:
    try:
        return int(value or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _years_fit(a: int, b: int) -> bool:
    return not a or not b or abs(a - b) <= 1


def similarity(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, str]:
    """How alike two titles are: (score, why), score 0 when they are not.
    Either side may be a library title or anything with a title and a year."""
    none = (0.0, "")
    # A record id is the strongest thing there is, either way: the same IMDb
    # title is the same film whatever it is called, and two different ones
    # are two films however alike the names.
    if a.get("imdb_id") and b.get("imdb_id"):
        return (CERTAIN, "same_imdb") if a["imdb_id"] == b["imdb_id"] else none
    if a.get("wiki_url") and b.get("wiki_url") and wiki_key(a["wiki_url"]) == wiki_key(b["wiki_url"]):
        return CERTAIN, "same_wikipedia"
    if a.get("source") and a.get("source_id") and a.get("source") == b.get("source") and a.get("source_id") == b.get("source_id"):
        return CERTAIN, "same_record"

    wa, wb = title_words(a.get("title")), title_words(b.get("title"))
    ka, kb = " ".join(wa), " ".join(wb)
    if not ka or not kb:
        return none
    ya, yb = _year(a.get("year")), _year(b.get("year"))

    if ka == kb:
        if ya and yb:
            return (CERTAIN, "same_title_year") if _years_fit(ya, yb) else (REMAKE, "same_title_other_year")
        return LIKELY, "same_title"

    # One is the other with a subtitle. Only with both years there and
    # agreeing: "Alien" and "Alien: Resurrection" share a first half and
    # nothing else.
    if ya and yb and _years_fit(ya, yb):
        ma, mb = _main_title(a.get("title")), _main_title(b.get("title"))
        if (ma and ma == kb) or (mb and mb == ka):
            return LIKELY, "subtitle"

    if not _years_fit(ya, yb):
        return none
    # Rocky II is not Rocky III, however close the spelling.
    if _numbers(wa) != _numbers(wb):
        return none

    longest = max(len(ka), len(kb))
    if min(len(ka), len(kb)) >= 4:
        limit = int(longest * 0.15)
        d = _distance(ka, kb, limit)
        if d <= limit:
            return SIMILAR + 0.1 * (1 - d / longest) * 0.5, "spelled_alike"
    if min(len(wa), len(wb)) >= 3 and _jaccard(wa, wb) >= 0.8:
        return SIMILAR, "same_words"
    return none


def _readings(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Typed with the year on the end and nothing between: "sleepless in
    seattle 1993". Could be the year, could be the name -- Blade Runner 2049
    -- so both readings are tried and the better one kept."""
    out = [candidate]
    bare = None if candidate.get("year") else BARE_YEAR.match(str(candidate.get("title") or "").strip())
    if bare and int(bare.group(2)) <= datetime.now().year + 2:
        out.append({**candidate, "title": bare.group(1), "year": int(bare.group(2))})
    return out


def find_matches(
    candidate: dict[str, Any],
    titles: Iterable[dict[str, Any]],
    minimum: float = SIMILAR,
    limit: int = 4,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    """What in the library looks like candidate, best first:
    [{id, score, why}]. minimum drops to REMAKE for a warning, where the
    other year's film is worth a mention."""
    out = []
    ways = _readings(candidate)
    for title in titles:
        if (exclude and title["id"] in exclude) or title["id"] == candidate.get("id"):
            continue
        best = (0.0, "")
        for way in ways:
            match = similarity(way, title)
            if match[0] > best[0]:
                best = match
        if best[0] >= minimum:
            out.append({"id": title["id"], "score": round(best[0], 4), "why": best[1]})
    out.sort(key=lambda match: -match["score"])
    return out[:limit]


def pair_key(a: str, b: str) -> str:
    return f"{a}:{b}" if a < b else f"{b}:{a}"


def duplicate_groups(titles: list[dict[str, Any]], dismissed: set[str], minimum: float = SIMILAR) -> list[dict[str, Any]]:
    """Every set of titles that look like one another, surest first:
    [{ids, score, why}]. Compared only within blocks that share something --
    an id, a word, the first few letters -- so a thousand titles are not a
    million comparisons."""
    blocks: dict[str, list[dict[str, Any]]] = {}

    def put(key: str, title: dict[str, Any]) -> None:
        if key:
            blocks.setdefault(key, []).append(title)

    for title in titles:
        words = title_words(title.get("title"))
        key = " ".join(words)
        put(f"i:{title['imdb_id']}" if title.get("imdb_id") else "", title)
        put(f"w:{wiki_key(title['wiki_url'])}" if title.get("wiki_url") else "", title)
        put(f"k:{key}" if key else "", title)
        put(f"p:{key.replace(' ', '')[:4]}" if len(key) >= 4 else "", title)
        for word in set(words):
            if len(word) >= 4 and not word.isdigit():
                put(f"t:{word}", title)

    parent = {title["id"]: title["id"] for title in titles}

    def root(ident: str) -> str:
        while parent[ident] != ident:
            parent[ident] = parent[parent[ident]]
            ident = parent[ident]
        return ident

    best: dict[str, tuple[float, str]] = {}
    done: set[str] = set()
    for block in blocks.values():
        if len(block) < 2 or len(block) > 250:
            continue
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                a, b = block[i], block[j]
                pair = pair_key(a["id"], b["id"])
                if pair in done:
                    continue
                done.add(pair)
                if pair in dismissed:
                    continue
                match = similarity(a, b)
                if match[0] < minimum:
                    continue
                best[pair] = match
                parent[root(a["id"])] = root(b["id"])

    members: dict[str, list[str]] = {}
    for title in titles:
        members.setdefault(root(title["id"]), []).append(title["id"])
    groups = []
    for ids in members.values():
        if len(ids) < 2:
            continue
        score, why = 0.0, ""
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                match = best.get(pair_key(ids[i], ids[j]))
                if match and match[0] > score:
                    score, why = match
        groups.append({"ids": ids, "score": round(score, 4), "why": why})
    by_id = {title["id"]: title for title in titles}
    groups.sort(key=lambda group: (-group["score"], norm_key(by_id[group["ids"][0]].get("title"))))
    return groups


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------

FILL_FIELDS = (
    "year", "poster_url", "overview", "runtime", "creator", "certification",
    "imdb_id", "wiki_url", "apple_tv", "ext_rating", "catalogue_key", "genres", "cast",
)

# Further along wins when one person's states for two copies are folded.
STATUS_RANK = {"dropped": 0, "queue": 1, "watching": 2, "watched": 3}


def _blank(value: object) -> bool:
    return value is None or value == "" or value == []


def merged_title_fields(keep: dict[str, Any], others: list[dict[str, Any]]) -> dict[str, Any]:
    """What keep becomes when the others are folded into it: every tag, link
    and note, and any detail it was missing. Only the fields that change."""
    every = [keep, *others]
    out: dict[str, Any] = {}
    tags: list[str] = []
    for title in every:
        for tag in title.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
    if tags != (keep.get("tags") or []):
        out["tags"] = tags
    links = list(keep.get("links") or [])
    for link in (link for title in others for link in title.get("links") or []):
        if not any(existing["url"] == link["url"] for existing in links):
            links.append(link)
    if len(links) != len(keep.get("links") or []):
        out["links"] = links
    notes: list[str] = []
    for title in every:
        note = (title.get("notes") or "").strip()
        if note and note not in notes:
            notes.append(note)
    if notes and "\n\n".join(notes) != (keep.get("notes") or "").strip():
        out["notes"] = "\n\n".join(notes)
    for field in FILL_FIELDS:
        if _blank(keep.get(field)):
            donor = next((title for title in others if not _blank(title.get(field))), None)
            if donor is not None:
                out[field] = donor[field]
    if not keep.get("source"):
        donor = next((title for title in others if title.get("source")), None)
        if donor is not None:
            out["source"] = donor["source"]
            out["source_id"] = donor.get("source_id", "")
    added = sorted(title["added_at"] for title in every if title.get("added_at"))
    if added and added[0] != keep.get("added_at"):
        out["added_at"] = added[0]
    return out


def merged_state(states: list[dict[str, Any]]) -> dict[str, Any]:
    """One person's states for several copies of a work, folded into one:
    the furthest status, the earliest watched date, the highest rating, a
    heart if any had one, every note."""
    present = [state for state in states if state]
    if not present:
        return {}
    best = max(present, key=lambda state: STATUS_RANK.get(state.get("status") or "", -1))
    watched = sorted(state["watched_at"] for state in present if state.get("watched_at"))
    ratings = [state["rating"] for state in present if state.get("rating")]
    notes: list[str] = []
    for state in present:
        note = (state.get("note") or "").strip()
        if note and note not in notes:
            notes.append(note)
    return {
        "status": best.get("status"),
        "watched_at": watched[0] if watched else None,
        "rating": max(ratings) if ratings else None,
        "heart": any(state.get("heart") for state in present),
        "note": "\n\n".join(notes),
    }
