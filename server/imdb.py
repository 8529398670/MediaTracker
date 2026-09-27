"""IMDb's own rating for a title, from IMDb's own file.

IMDb sells its API to studios and nobody else (see enrich.py), but it also
publishes a handful of plain data files for personal, non-commercial use, and
refreshes them every day.  One of them is nothing but the rating: the title's
id, its average and its number of votes, for every title anyone has rated —
1.7 million lines, 8.6 MB compressed, no key.

That is the whole job, because the ids are already here.  Every Discover film
that Wikidata knows carries its IMDb id in ``certs.json``, and the fill-in
pass puts one on most of the library.  So a card's score is one lookup by id,
and the only network cost is one conditional download a day.

Held as packed arrays rather than a dictionary.  A dictionary of 1.7 million
tuples is well over a hundred megabytes, in a container that has 256 for
everything; three arrays of plain numbers are fifteen.  The file is sorted by
its id *as text*, which is not numeric order across lengths — tt10000000
sorts between tt1000000 and tt1000001 — but it is numeric order within one
length.  So the rows are kept in one bucket per id length, each already in
order as it arrives, and a lookup is a binary search in the right one.

Parsing the file is about ten seconds of this machine's CPU, and the app is
rebuilt and restarted after every change.  So what was parsed is written back
out as the arrays themselves, and a restart reads them in milliseconds.
"""

from __future__ import annotations

import array
import bisect
import email.utils
import gzip
import itertools
import json
import os
import re
import sys
import threading
import time

from config import IMDB_DIR, NET_ENABLED, log, now_iso
from netio import fetch_file

URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"

# The licence for the file asks for this wherever the data is shown.
ATTRIBUTION = ("Information courtesy of IMDb (https://www.imdb.com). "
               "Used with permission.")

# IMDb rebuilds the file once a day. Asking more often only ever gets a 304.
REFRESH_SECONDS = 24 * 3600
# After a download that failed, try again sooner than tomorrow.
RETRY_SECONDS = 3600

# The real file has 1.7 million rows. One with a small fraction of that is an
# error page or a truncated download, and is not allowed to replace it.
MIN_ROWS = 100_000

ID = re.compile(r"^tt(\d{7,10})$")

# The shape of the arrays on disk. `I` is four bytes on every platform this
# runs on, but that is a C compiler's promise and not Python's, so the cache
# says what it was written with and is not read by anything different.
LAYOUT = {"ids": "I", "scores": "B", "votes": "I"}

# A score on its own says less than it looks like it does. A film with a 9.4
# from forty votes has been rated by its crew; one with an 8.5 from half a
# million has been rated by everybody. Ranking by the bare number puts the
# first above the second, so a sort pulls every score toward an ordinary one
# by as many votes as `PRIOR_VOTES` — IMDb's own top-250 formula. Scores here
# are tenths: 65 is 6.5.
PRIOR_VOTES = 1000
PRIOR_SCORE = 65


def weighted(score: int, votes: int, prior_votes: int = PRIOR_VOTES,
             prior_score: int = PRIOR_SCORE) -> float:
    """A score to rank by: the average, discounted for how few voted."""
    votes = max(0, votes)
    return (votes * score + prior_votes * prior_score) / (votes + prior_votes)


def _empty() -> tuple:
    return tuple(array.array(code) for code in LAYOUT.values())


# Read a few megabytes at a time and split each piece in one go. A loop over
# 1.7 million lines is ten to twenty seconds of this machine's CPU; slicing
# columns out of a chunk's tokens is about five, and this runs once a day.
CHUNK = 1 << 22


def parse(path) -> dict[int, tuple]:
    """The file, as ``{id length: (ids, scores, votes)}``.

    A score is kept in tenths so it fits a byte: IMDb prints one decimal
    place, so ``7.4`` is 74 exactly, with no float in between.
    """
    buckets: dict[int, tuple] = {}
    tail = b""
    with gzip.open(path, "rb") as handle:
        if not handle.readline().startswith(b"tconst"):
            raise ValueError("that is not IMDb's ratings file")
        while True:
            chunk = handle.read(CHUNK)
            text = tail + chunk
            if chunk:
                cut = text.rfind(b"\n")
                if cut < 0:
                    tail = text
                    continue
                tail, text = text[cut + 1:], text[:cut]
            else:
                tail = b""
            if text and not _take(buckets, text):
                _take_lines(buckets, text)
            if not chunk:
                break
    # Never seen, but the order is what the lookup stands on, so a file that
    # breaks it is put right rather than searched wrongly.
    for size, (ids, scores, counts) in list(buckets.items()):
        if all(a < b for a, b in zip(ids, itertools.islice(ids, 1, None))):
            continue
        order = sorted(range(len(ids)), key=ids.__getitem__)
        buckets[size] = (array.array("I", (ids[i] for i in order)),
                         array.array("B", (scores[i] for i in order)),
                         array.array("I", (counts[i] for i in order)))
    return buckets


def _take(buckets: dict[int, tuple], text: bytes) -> bool:
    """One chunk of whole lines, a column at a time. False if it will not go.

    Every line is three fields, so the tokens fall into columns by position
    — as long as every line really is three. Anything odd, and the chunk is
    handed to the line-by-line reader instead, which can skip a bad line
    rather than shift every column after it.
    """
    tokens = text.split()
    ids, scores, votes = tokens[0::3], tokens[1::3], tokens[2::3]
    if len(tokens) % 3 or not all(token.startswith(b"tt") for token in ids):
        return False
    sizes = set(map(len, ids))
    try:
        numbers = [int(token[2:]) for token in ids]
        tenths = [int(token.replace(b".", b"")) if b"." in token else int(token) * 10
                  for token in scores]
        counts = list(map(int, votes))
        # Built apart and checked before any of it reaches a bucket, so a
        # value out of range cannot leave a column longer than its neighbours.
        parts = {}
        for size in sizes:
            keep = (range(len(ids)) if len(sizes) == 1
                    else [at for at, token in enumerate(ids) if len(token) == size])
            parts[size - 2] = (array.array("I", [numbers[at] for at in keep]),
                               array.array("B", [tenths[at] for at in keep]),
                               array.array("I", [counts[at] for at in keep]))
    except (ValueError, OverflowError):
        return False
    if any(score > 100 for score in tenths):
        return False
    for size, columns in parts.items():
        bucket = buckets.get(size)
        if bucket is None:
            bucket = buckets[size] = _empty()
        for column, more in zip(bucket, columns):
            column.extend(more)
    return True


def _take_lines(buckets: dict[int, tuple], text: bytes) -> None:
    """The slow way, one line at a time, skipping any that do not read."""
    for line in text.split(b"\n"):
        parts = line.split(b"\t")
        if len(parts) != 3 or not parts[0].startswith(b"tt"):
            continue
        digits, score = parts[0][2:], parts[1]
        try:
            number = int(digits)
            tenths = int(score.replace(b".", b"")) if b"." in score else int(score) * 10
            votes = int(parts[2])
        except ValueError:
            continue
        bucket = buckets.get(len(digits))
        if bucket is None:
            bucket = buckets[len(digits)] = _empty()
        bucket[0].append(number)
        bucket[1].append(min(max(tenths, 0), 100))
        bucket[2].append(min(max(votes, 0), 0xFFFFFFFF))


def _day(header: str) -> str:
    """The date a Last-Modified header names, as 2026-09-26."""
    try:
        return email.utils.parsedate_to_datetime(header).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


class Ratings:
    """The ratings file: looked up in memory, cached on disk, fetched daily.

    Reading never takes a lock. A refresh builds its arrays apart and then
    replaces the whole table in one assignment, so a lookup sees either the
    old table or the new one and never half of each.
    """

    def __init__(self, folder) -> None:
        self.folder = folder
        self.table: dict[int, tuple] = {}
        self.meta: dict = {}
        self.busy = False
        self.error = ""
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    @property
    def bin_path(self):
        return self.folder / "ratings.bin"

    @property
    def meta_path(self):
        return self.folder / "meta.json"

    @property
    def gz_path(self):
        return self.folder / "title.ratings.tsv.gz"

    # -------------------------------------------------------------- reading

    def get(self, imdb_id: object) -> tuple[int, int] | None:
        """``(score in tenths, votes)`` for a title, or None."""
        match = ID.match(str(imdb_id or "").strip().lower())
        if not match:
            return None
        digits = match.group(1)
        bucket = self.table.get(len(digits))
        if not bucket:
            return None
        ids, scores, votes = bucket
        number = int(digits)
        at = bisect.bisect_left(ids, number)
        if at < len(ids) and ids[at] == number:
            return scores[at], votes[at]
        return None

    def many(self, ids) -> dict[str, list[int]]:
        """``{id: [score, votes]}`` for the ones that have a rating."""
        out: dict[str, list[int]] = {}
        for imdb_id in ids:
            found = self.get(imdb_id)
            if found:
                out[str(imdb_id).strip().lower()] = list(found)
        return out

    def titles(self) -> int:
        return sum(len(bucket[0]) for bucket in self.table.values())

    def status(self) -> dict:
        return {"titles": self.titles(), "date": self.meta.get("fileDate", ""),
                "checkedAt": self.meta.get("checkedAtIso", ""),
                "busy": self.busy, "error": self.error,
                "attribution": ATTRIBUTION}

    # ------------------------------------------------------------------ disk

    def load(self) -> bool:
        """Read the arrays back from the last parse. False if there are none.

        Anything that does not add up — a count that disagrees with the
        file's length, arrays of another width or byte order — is treated as
        no cache at all, and the next refresh parses the file again.
        """
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            sizes = {int(k): int(v) for k, v in (meta.get("buckets") or {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return False
        widths = {code: array.array(code).itemsize for code in LAYOUT.values()}
        if meta.get("byteorder") != sys.byteorder or meta.get("widths") != widths:
            return False
        row = sum(widths[code] for code in LAYOUT.values())
        try:
            if self.bin_path.stat().st_size != row * sum(sizes.values()):
                return False
            table: dict[int, tuple] = {}
            with open(self.bin_path, "rb") as handle:
                for size in sorted(sizes):
                    arrays = _empty()
                    for column in arrays:
                        column.fromfile(handle, sizes[size])
                    table[size] = arrays
        except (OSError, EOFError, ValueError):
            return False
        self.table, self.meta = table, meta
        return True

    def save(self, table: dict[int, tuple], meta: dict) -> dict:
        """Write the arrays out, then the note that says how to read them."""
        self.folder.mkdir(parents=True, exist_ok=True)
        meta = {**meta, "byteorder": sys.byteorder,
                "widths": {code: array.array(code).itemsize for code in LAYOUT.values()},
                "buckets": {str(size): len(table[size][0]) for size in sorted(table)}}
        tmp = self.bin_path.with_suffix(".tmp")
        with open(tmp, "wb") as handle:
            for size in sorted(table):
                for column in table[size]:
                    column.tofile(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.bin_path)
        self._write_meta(meta)
        return meta

    def _write_meta(self, meta: dict) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(tmp, self.meta_path)

    # --------------------------------------------------------------- fetching

    def due_in(self) -> float:
        """Seconds until the file is worth asking for again."""
        if not self.table:
            return 0.0
        checked = float(self.meta.get("checkedAt") or 0)
        return max(0.0, checked + REFRESH_SECONDS - time.time())

    def refresh(self) -> bool:
        """Fetch the file if it has changed, and swap it in. True if it had.

        The validators are only sent while there is a table to keep: with no
        cache, a 304 would leave nothing to show.
        """
        if not NET_ENABLED:
            return False
        self.folder.mkdir(parents=True, exist_ok=True)
        have = bool(self.table)
        got = fetch_file(URL, self.gz_path,
                         etag=self.meta.get("etag", "") if have else "",
                         modified=self.meta.get("lastModified", "") if have else "")
        stamp = {"checkedAt": time.time(), "checkedAtIso": now_iso()}
        if got.get("notModified"):
            self.meta = {**self.meta, **stamp}
            self._write_meta(self.meta)
            return False
        if not got:
            raise OSError("the download came back empty")
        try:
            table = parse(self.gz_path)
        finally:
            self.gz_path.unlink(missing_ok=True)
        rows = sum(len(bucket[0]) for bucket in table.values())
        if rows < MIN_ROWS:
            raise ValueError(f"only {rows} rows — not keeping it")
        meta = {"schema": 1, **stamp, "etag": got.get("etag", ""),
                "lastModified": got.get("lastModified", ""),
                "fileDate": _day(got.get("lastModified", ""))}
        self.table, self.meta = table, self.save(table, meta)
        log(f"imdb: {rows} titles rated, file of {meta['fileDate'] or 'unknown date'}")
        return True

    def start(self) -> None:
        """Read the cache now, and keep it fresh from a thread.

        The cache is read here rather than in the thread, so the very first
        request after a restart already has every score.
        """
        with self.lock:
            if self.thread:
                return
            self.load()
            self.thread = threading.Thread(target=self._run, name="imdb", daemon=True)
            self.thread.start()

    def _run(self) -> None:
        while True:
            wait = self.due_in()
            if wait > 0:
                time.sleep(min(wait, REFRESH_SECONDS))
                continue
            if not NET_ENABLED:
                return
            self.busy = True
            try:
                self.refresh()
                self.error = ""
            except Exception as exc:  # noqa: BLE001 — the old table stands
                self.error = f"{type(exc).__name__}: {exc}"
                log(f"imdb: could not refresh the ratings: {self.error}")
            finally:
                self.busy = False
            if self.error:
                time.sleep(RETRY_SECONDS)


STORE = Ratings(IMDB_DIR)
