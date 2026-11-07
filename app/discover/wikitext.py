"""Reading Wikipedia's own markup.

Wikipedia publishes the lists this app harvests as wikitext, and wikitext is
a format with a grammar rather than a page that has to be scraped: a table is
a table, a link is a link, and neither changes when someone restyles the
site.  So the whole of the parsing lives here, and it is pure — no network,
no state, no provider.  ``lists.py`` next door does the fetching and knows
what the tables mean.

Three things are hard enough to be worth naming:

*   A cell is separated from the next by ``||``, but ``{{dts|1949|May|3}}``
    and ``[[Adam's Rib|Adam's Rib]]`` are full of pipes that separate
    nothing.  Every split here counts braces and brackets first.
*   ``rowspan`` is how the box-office lists say "and the week after that",
    which is exactly the fact worth having, so the grid is expanded rather
    than read line by line.
*   A film's title is an ``[[article]]``, and the article is worth more than
    the words: it is an exact link, it disambiguates *The Killers* (1946)
    from *The Killers* (1964), and it is the key everything else joins on.
"""

from __future__ import annotations

import re


# --------------------------------------------------------------------------
# depth-aware splitting
# --------------------------------------------------------------------------

_OPEN = {"{{": "}}", "[[": "]]", "{|": "|}"}


def _depths(text: str) -> list[int]:
    """For every character, how many templates/links/tables enclose it."""
    out = [0] * (len(text) + 1)
    depth = 0
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in _OPEN:
            depth += 1
            out[i] = out[i + 1] = depth
            i += 2
            continue
        if pair in ("}}", "]]", "|}"):
            out[i] = out[i + 1] = depth
            depth = max(0, depth - 1)
            i += 2
            continue
        out[i] = depth
        i += 1
    out[len(text)] = depth
    return out


def split_top(text: str, sep: str) -> list[str]:
    """Split on `sep`, but only where nothing encloses it."""
    if sep not in text:
        return [text]
    depth = _depths(text)
    parts, start, i = [], 0, 0
    while i <= len(text) - len(sep):
        if depth[i] == 0 and text.startswith(sep, i):
            parts.append(text[start:i])
            i += len(sep)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


# --------------------------------------------------------------------------
# markup to text
# --------------------------------------------------------------------------

COMMENT = re.compile(r"<!--.*?-->", re.S)
REF = re.compile(r"<ref\b[^>]*?/>|<ref\b.*?</ref\s*>", re.S | re.I)
GALLERY = re.compile(r"<gallery\b.*?</gallery\s*>", re.S | re.I)
TAG = re.compile(r"</?[a-z][a-z0-9]*\b[^>]*>", re.I)
BREAK = re.compile(r"<br\s*/?>", re.I)
FILE_LINK = re.compile(r"^(?:file|image|category):", re.I)

# Templates worth reading rather than dropping. The value is which of the
# template's positional arguments to keep, in order.
KEEP_ARGS = {
    "sortname": (1, 2),         # {{sortname|Michael|Curtiz}}
    "nowrap": (1,),
    "abbr": (1,),
    "tooltip": (1,),
    "small": (1,),
    "sic": (1,),
    "lang": (2,),
    # {{dts|link=off|1949|January|5}} — the date a box-office week ended.
    "dts": (2, 3, 1),
    "date table sorting": (2, 3, 1),
    "start date": (2, 3, 1),
    "film date": (2, 3, 1),
}

NAMED_ARG = re.compile(r"^\s*[A-Za-z0-9_ -]+\s*=")
LITERAL = {"'": "'", "'s": "'s", "spaced ndash": " – ", "ndash": "–",
           "mdash": "—", "snd": " – "}


def _template(body: str) -> str:
    """What one ``{{...}}`` is worth as text — usually nothing."""
    parts = split_top(body, "|")
    name = parts[0].strip().lower()
    if name in LITERAL:
        return LITERAL[name]
    keep = KEEP_ARGS.get(name)
    if keep is None:
        return ""
    positional = [p for p in parts[1:] if not NAMED_ARG.match(p)]
    words = [positional[i - 1].strip() for i in keep
             if 0 < i <= len(positional)]
    return " ".join(w for w in words if w)


def _templates(text: str) -> str:
    """Resolve templates innermost first, so nested ones collapse cleanly."""
    for _ in range(6):
        out = re.sub(r"\{\{([^{}]*)\}\}", lambda m: _template(m.group(1)), text)
        if out == text:
            return out
        text = out
    return re.sub(r"\{\{|\}\}", "", text)


def links(text: str) -> list[tuple[str, str]]:
    """Every ``[[target|label]]`` as (target, label), files and sections out.

    A section link like ``[[Film#Sound|sound]]`` points at an article, so the
    fragment is dropped rather than the link.
    """
    out = []
    for raw in re.findall(r"\[\[([^\[\]]+)\]\]", text):
        target, _, label = raw.partition("|")
        target = target.strip()
        if not target or FILE_LINK.match(target):
            continue
        target = target.split("#")[0].strip()
        if not target:
            continue
        out.append((target, (label.strip() or target)))
    return out


def italic_links(text: str) -> list[tuple[str, str]]:
    """``''[[The Public Enemy]]''`` — the way an article names a film.

    Italics are the house style for a work's title, so in an article of
    prose this separates the films from the magazines and the court cases
    that are linked beside them.
    """
    out = []
    for raw in re.findall(r"''\[\[([^\[\]]+)\]\]''", text):
        target, _, label = raw.partition("|")
        target = target.split("#")[0].strip()
        if not target or FILE_LINK.match(target):
            continue
        out.append((target, (label.strip() or target)))
    return out


def text_of(markup: str) -> str:
    """Wikitext as the words a person would read."""
    s = COMMENT.sub("", str(markup or ""))
    s = REF.sub("", s)
    s = GALLERY.sub("", s)
    s = BREAK.sub(", ", s)
    s = _templates(s)
    s = re.sub(r"\[\[([^\[\]]+)\]\]",
               lambda m: m.group(1).partition("|")[2].strip()
               or m.group(1).split("#")[0].strip(), s)
    s = re.sub(r"\[(?:https?:|//)\S+?\s+([^\]]*)\]", r"\1", s)   # [url label]
    s = re.sub(r"\[(?:https?:|//)\S+?\]", "", s)                  # [url]
    s = TAG.sub("", s)
    s = s.replace("'''", "").replace("''", "")
    s = s.replace("&nbsp;", " ").replace("&ndash;", "–").replace("&amp;", "&")
    s = re.sub(r"\s*,\s*,\s*", ", ", s)
    return re.sub(r"\s+", " ", s).strip().strip("|").strip()


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------

ATTRS = re.compile(r"^[^\[\]{}|]*=[^\[\]{}|]*$")


def _cell(raw: str) -> tuple[str, int, int]:
    """One cell as (wikitext, rowspan, colspan).

    ``| style="width:21%" | Title`` is a cell whose attributes are the half
    before the pipe. The half before is attributes only when it looks like
    attributes: it has an ``=`` in it and no markup, which is what tells it
    from a title that simply contains a pipe.
    """
    rows = cols = 1
    parts = split_top(raw, "|")
    if len(parts) > 1 and ATTRS.match(parts[0].strip()):
        head = parts[0]
        raw = "|".join(parts[1:])
        span = re.search(r"\browspan\s*=\s*\"?(\d+)", head, re.I)
        if span:
            rows = max(1, min(int(span.group(1)), 400))
        span = re.search(r"\bcolspan\s*=\s*\"?(\d+)", head, re.I)
        if span:
            cols = max(1, min(int(span.group(1)), 40))
    return raw.strip(), rows, cols


def _grid(rows: list[list[tuple[str, int, int]]]) -> list[list[str]]:
    """Expand rowspan and colspan so every row has a cell in every column.

    A film that held number one for three weeks is written once with
    ``rowspan="3"``, and those three weeks are the fact worth keeping.
    """
    out: list[list[str]] = [[] for _ in rows]
    carry: dict[int, list] = {}                 # column -> [text, rows left]
    for index, row in enumerate(rows):
        line = out[index]
        source = list(row)
        column = 0
        while source or any(c[1] > 0 for c in carry.values()):
            held = carry.get(column)
            if held and held[1] > 0:
                line.append(held[0])
                held[1] -= 1
                column += 1
                continue
            if not source:
                break
            text, spans, wide = source.pop(0)
            for _ in range(wide):
                line.append(text)
                if spans > 1:
                    carry[column] = [text, spans - 1]
                column += 1
        for column, held in list(carry.items()):
            if held[1] <= 0:
                del carry[column]
    return out


def _headers(heads: list[list[tuple[str, int, int]]]) -> list[str]:
    """One name per column, from however many rows the header was written in.

    Expanded the same way the data is, so a heading spanning two columns
    names both of them and one spanning two rows is not read twice. Where the
    top row has nothing to say about a column, the row under it does.
    """
    if not heads:
        return []
    grid = _grid(heads)
    width = max(len(line) for line in grid)
    out = []
    for column in range(width):
        name = ""
        for line in grid:
            if column < len(line):
                name = text_of(line[column])
                if name:
                    break
        out.append(name)
    return out


def tables(wikitext: str) -> list[dict]:
    """Every wikitable on the page, as {caption, headers, rows, section}.

    Rows are raw wikitext per cell — the caller decides what a column means
    before deciding how much of the markup it wants to keep.
    """
    found: list[dict] = []
    section = ""
    depth = 0
    current: dict | None = None
    rows: list[list[tuple[str, int, int]]] = []
    heads: list[list[tuple[str, int, int]]] = []
    row: list[tuple[str, int, int]] = []
    pure_header = False

    def flush_row() -> None:
        """A row of ``!`` cells before any data is a header row.

        All of them, not just the first: an awards table names the ceremony
        across two columns on one line and splits it on the next, and reading
        only the top line leaves every column after it off by one. A row that
        opens with ``!`` and continues with ``|`` — which is how a ranked list
        writes its rank — is data with a heading in it, not a header.
        """
        nonlocal row, pure_header
        if pure_header and not rows and len(heads) < 4:
            heads.append(row)
        elif row:
            rows.append(row)
        row = []
        pure_header = False

    for raw_line in COMMENT.sub("", wikitext).splitlines():
        line = raw_line.strip()

        if depth == 0:
            head = re.match(r"^(={2,6})\s*(.+?)\s*\1$", line)
            if head:
                section = text_of(head.group(2))
                continue

        if line.startswith("{|"):
            depth += 1
            if depth == 1:
                current = {"caption": "", "section": section}
                rows, heads, row, pure_header = [], [], [], False
            continue

        if depth == 0:
            continue

        if line.startswith("|}"):
            depth -= 1
            if depth == 0 and current is not None:
                flush_row()
                current["headers"] = _headers(heads)
                current["rows"] = _grid(rows)
                found.append(current)
                current = None
            continue

        if depth > 1:                      # a nested table is not a list
            continue

        if line.startswith("|+"):
            current["caption"] = text_of(line[2:])
            continue

        if line.startswith("|-"):
            flush_row()
            continue

        if line.startswith("!"):
            if not row:
                pure_header = True
            for part in split_top(line[1:], "!!"):
                row.append(_cell(part))
            continue

        if line.startswith("|"):
            pure_header = False
            for part in split_top(line[1:], "||"):
                row.append(_cell(part))
            continue

        # A cell's content wrapped onto the next line.
        if row:
            text, spans, wide = row[-1]
            row[-1] = (f"{text}\n{raw_line}".strip(), spans, wide)

    return found


def column(headers: list[str], *names: str) -> int:
    """Which column a header is in, by any of the names it goes by."""
    folded = [re.sub(r"[^a-z ]+", "", h.lower()).strip() for h in headers]
    for name in names:
        for index, header in enumerate(folded):
            if header == name:
                return index
    for name in names:
        for index, header in enumerate(folded):
            if name and name in header:
                return index
    return -1
