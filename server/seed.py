"""Seed import — parse the Markdown lists sitting next to the app.

This is a straight port of the outline parser in ``public/js/porting.js`` so
that the documents in the project root are folded into the library on
startup, with no paste step.  Keep the two in sync: the browser importer is
still there for pasting something new.

Nothing here touches the library; it only turns text into plain dicts.
``app.py`` owns the merge.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------- filenames

# Watched.md goes last on purpose: by then the other documents have
# contributed the titles, and it only has to flip them to watched.
SEED_ORDER = ("movies.md", "tv shows.md", "tvshows.md", "misc.md", "watched.md")

SEED_DEFAULTS = {
    "movies.md":   {"type": "movie", "status": "queue"},
    "tv shows.md": {"type": "tv",    "status": "queue"},
    "tvshows.md":  {"type": "tv",    "status": "queue"},
    "tv.md":       {"type": "tv",    "status": "queue"},
    "misc.md":     {"type": "other", "status": "queue"},
    "watched.md":  {"type": "movie", "status": "watched"},
}

# Documents that are about the project, not part of the library.
SEED_SKIP = {"readme.md", "changelog.md", "license.md", "contributing.md", "todo.md"}


def defaults_for(name: str) -> dict:
    """Type and status to assume for a file we were not told about."""
    key = Path(name).name.lower()
    if key in SEED_DEFAULTS:
        return dict(SEED_DEFAULTS[key])
    stem = Path(name).stem
    return {"type": type_hint(stem) or "movie", "status": status_hint(stem) or "queue"}


def seed_files(directory: Path) -> list[Path]:
    """Every .md in *directory*, known documents first, then the rest A→Z."""
    try:
        found = [p for p in sorted(directory.iterdir())
                 if p.is_file() and p.suffix.lower() == ".md"
                 and p.name.lower() not in SEED_SKIP]
    except OSError:
        return []

    def rank(path: Path) -> tuple[int, str]:
        key = path.name.lower()
        return (SEED_ORDER.index(key) if key in SEED_ORDER else len(SEED_ORDER), key)

    return sorted(found, key=rank)


# -------------------------------------------------------------- placeholders

# "asdf" and friends are what you type into a document to hold a spot open.
# They are not titles and never become items.
_MASH = re.compile(r"(?:asdf|fdsa|asdg|qwerty|qwer|zxcv|hjkl|asd|sdf|fgh)+\d*")


def is_placeholder(title: str) -> bool:
    squashed = re.sub(r"[^a-z0-9]+", "", str(title or "").lower())
    if not squashed:
        return True
    return _MASH.fullmatch(squashed) is not None


# ------------------------------------------------------------------ patterns

RX_MD_LINK = re.compile(r"\[([^\]]*)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
RX_BARE_URL = re.compile(r"https?://[^\s<>()\[\]\"']+")
RX_BULLET = re.compile(r"^(\s*)(?:[-*+\u2022\u25cf\u25e6]|\d+[.)])\s+(.*)$")
RX_CHECKBOX = re.compile(r"^\[([ xX])\]\s*(.*)$")
RX_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
RX_BOLD_HEAD = re.compile(r"^\*\*(.+?)\*\*:?\s*$")
RX_YEAR_ONLY = re.compile(r"^(?:19|20)\d{2}$")
RX_DECADE = re.compile(r"^(?:19|20)?\d0['\u2019]?s$", re.I)
RX_PAREN_TAIL = re.compile(r"^(.*?)\s*[(\[]([^()\[\]]{1,80})[)\]]\s*$")
RX_YEAR_RANGE = re.compile(r"^((?:18|19|20)\d{2})\s*(?:[-\u2013\u2014]\s*(?:(?:18|19|20)\d{2})?)?$")
RX_YEAR_BARE = re.compile(r"^(?:18|19|20)\d{2}$")

# How Wikipedia disambiguates a title, which is how it arrives when a
# Wikipedia link is pasted: "Parasite (2019 film)".
RX_YEAR_MEDIUM = re.compile(
    r"^((?:18|19|20)\d{2})\s+(?:film|movie|tv series|television series|series"
    r"|miniseries|anime|documentary|video game|novel|book)s?$", re.I)

# A run a document gives as a span: "Yes, Minister - 1980-1984", "Dickinson -
# 2019-21", "Cheers - 1982-present". The first year is the one that identifies
# the title, and the whole span comes off it — matching only the last year
# leaves "Yes, Minister - 1980" as the title and 1984 as the year, which is
# neither the name of anything nor the year it started.
RX_DASH_YEARS = re.compile(
    r"^(.{2,}?)\s*[-\u2013\u2014,]\s*"
    r"((?:18|19|20)\d{2})"
    r"(?:\s*[-\u2013\u2014/]\s*(?:(?:18|19|20)?\d{2}|present|now|date|ongoing|\?+))?"
    r"\s*$", re.I)

# The same span inside brackets: "The Wire (2002-2008)".
RX_PAREN_YEARS = re.compile(
    r"^((?:18|19|20)\d{2})"
    r"\s*[-\u2013\u2014/]\s*(?:(?:18|19|20)?\d{2}|present|now|date|ongoing|\?+)\s*$", re.I)


def clean(text: str) -> str:
    """Undo Google Docs' markdown escaping and its invisible characters."""
    out = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = re.sub(r"[\u200b\u200e\u200f\ufeff]", "", out)
    out = out.replace("\u00a0", " ")
    return re.sub(r"\\([^0-9A-Za-z_\s])", r"\1", out)


TAG_STOP = {
    "movies", "movie", "films", "film", "tv", "tv-shows", "shows", "show", "series",
    "watched", "skipped", "queue", "sources", "source", "list", "lists", "misc",
    "books", "book", "radio", "podcasts", "podcast", "anime", "games", "game",
}


def slug(text: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", str(text).lower()))


def heading_tags(text: str) -> list[str]:
    parts = re.split(r"\s[-\u2013\u2014]\s|[/,]", str(text))
    out = []
    for part in parts:
        tag = slug(part)
        if 1 < len(tag) <= 24 and not tag.isdigit() and tag not in TAG_STOP:
            out.append(tag)
    return out


def type_hint(text: str) -> str | None:
    t = str(text).lower()
    if "anime" in t:
        return "anime"
    if re.search(r"\btv\b|series|shows?\b", t):
        return "tv"
    if "documentar" in t:
        return "doc"
    if re.search(r"podcast|radio", t):
        return "podcast"
    if re.search(r"\bbooks?\b|reading", t):
        return "book"
    if re.search(r"\bgames?\b", t):
        return "game"
    if re.search(r"movies?|films?", t):
        return "movie"
    return None


def status_hint(text: str) -> str | None:
    t = str(text).lower()
    if re.search(r"skip|drop|abandon|nope", t):
        return "dropped"
    if re.search(r"watched|seen|finished|completed", t):
        return "watched"
    if re.search(r"watching|in progress|current", t):
        return "watching"
    if re.search(r"queue|to watch|want|wish|backlog", t):
        return "queue"
    return None


def split_title(raw: str) -> tuple[str, int | None, str]:
    """`Wagon Master (1950) (a note)` → ("Wagon Master", 1950, "a note")."""
    title = re.sub(r"[:;,]\s*$", "", re.sub(r"[*_]+$", "", raw.strip())).strip()
    year: int | None = None
    notes: list[str] = []

    for _ in range(4):
        match = RX_PAREN_TAIL.match(title)
        if not match:
            break
        inner = match.group(2).strip()
        span = (RX_YEAR_RANGE.match(inner) or RX_PAREN_YEARS.match(inner)
                or RX_YEAR_MEDIUM.match(inner))
        if span:
            if year is None:
                year = int(span.group(1))
        elif RX_YEAR_BARE.match(inner):
            if year is None:
                year = int(inner)
        else:
            notes.insert(0, inner)
        title = match.group(1).strip()

    # The span comes off the title whether or not a year has already been
    # found, because it is not part of the name either way: "Yes, Minister -
    # 1980-1984 (1984)" is the programme "Yes, Minister" twice over.
    match = RX_DASH_YEARS.match(title)
    if match:
        title = match.group(1).strip()
        if year is None:
            year = int(match.group(2))

    return re.sub(r"\s{2,}", " ", title).strip(), year, " ".join(notes)


def extract_links(text: str) -> tuple[list[dict], str]:
    links: list[dict] = []

    def take_md(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        links.append({
            "label": "" if re.match(r"^https?:", label, re.I) else label.strip()[:80],
            "url": url,
        })
        return " "

    rest = RX_MD_LINK.sub(take_md, text)

    def take_bare(match: re.Match) -> str:
        url = re.sub(r"[.,;)]+$", "", match.group(0))
        if not any(link["url"] == url for link in links):
            links.append({"label": "", "url": url})
        return " "

    rest = RX_BARE_URL.sub(take_bare, rest)

    seen, unique = set(), []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique.append(link)
    return unique, re.sub(r"\s{2,}", " ", rest).strip()


def parse_outline(text: str, *, type: str = "movie", status: str = "queue",
                  headings_as_tags: bool = True, capture_sources: bool = True,
                  extra_tags: tuple[str, ...] = ()) -> dict:
    """Turn a pasted / stored outline into ``{items, sources, placeholders}``."""
    lines = clean(text).split("\n")
    items: list[dict] = []
    sources: list[dict] = []
    headings: list[str | None] = []
    placeholders = 0
    last: dict | None = None
    last_indent = 0

    def context() -> dict:
        year = None
        kind = type
        state = status
        tags = list(extra_tags)
        for heading in headings:
            if not heading:
                continue
            bare = heading.strip()
            if RX_YEAR_ONLY.match(bare):
                year = int(bare)
                continue
            if RX_DECADE.match(bare):
                continue
            hint = type_hint(bare)
            if hint:
                kind = hint
            hint = status_hint(bare)
            if hint:
                state = hint
            if headings_as_tags:
                tags.extend(heading_tags(bare))
        seen, unique = set(), []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique.append(tag)
        return {"year": year, "type": kind, "status": state, "tags": unique[:8]}

    def set_heading(level: int, value: str) -> None:
        nonlocal last
        del headings[min(len(headings), level):]
        while len(headings) < level:
            headings.append(None)
        headings[level - 1] = value
        last = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        heading = RX_HEADING.match(line)
        if heading:
            set_heading(len(heading.group(1)), heading.group(2))
            continue

        bold = RX_BOLD_HEAD.match(line)
        if bold:
            set_heading(3, bold.group(1))
            continue

        bullet = RX_BULLET.match(line)
        indent = len(bullet.group(1).replace("\t", "    ")) if bullet else 0
        content = bullet.group(2) if bullet else line.strip()

        done = None
        box = RX_CHECKBOX.match(content)
        if box:
            done = box.group(1).lower() == "x"
            content = box.group(2)

        # A bare line that is neither a bullet nor a link is a sub-heading:
        # "Staged - AppleTV" on its own line is how the documents are written.
        if (not bullet and not RX_BARE_URL.search(content)
                and len(content) < 60 and not re.search(r"[.!?]$", content)):
            set_heading(4, content)
            continue

        links, rest = extract_links(content)
        ctx = context()

        if not rest:
            # Link-only line: it belongs to the item above when it is indented.
            if links and last is not None and (indent > last_indent or indent >= 2):
                for link in links:
                    if not any(l["url"] == link["url"] for l in last["links"]):
                        last["links"].append(link)
            elif capture_sources:
                for link in links:
                    if not any(s["url"] == link["url"] for s in sources):
                        sources.append({"url": link["url"], "title": link["label"],
                                        "tags": ctx["tags"][:4]})
            continue

        title, year, notes = split_title(rest)
        if not title or not re.search(r"[a-z0-9]", title, re.I):
            continue
        if is_placeholder(title):
            placeholders += 1
            last = None
            continue

        item = {
            "title": title,
            "year": year or ctx["year"] or None,
            "type": ctx["type"],
            "status": "watched" if done is True else ctx["status"],
            "links": links,
            "tags": ctx["tags"],
            "notes": notes,
        }
        items.append(item)
        last = item
        last_indent = indent

    return {"items": items, "sources": sources, "placeholders": placeholders}


# ------------------------------------------------------------------- merging

def title_key(title: str, year: object = None) -> str:
    base = re.sub(r"^(the|a|an)\s+", "", str(title or "").lower())
    base = re.sub(r"[^a-z0-9]+", " ", base).strip()
    return f"{base}|{year}" if year else base
