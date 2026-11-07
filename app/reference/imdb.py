"""IMDb's own rating for a title, from IMDb's own file.

IMDb publishes a handful of plain data files for personal, non-commercial
use, refreshed daily. One is nothing but the rating: id, average, votes, for
every rated title -- 1.7 million lines, about 9 MB compressed, no key. The
library carries IMDb ids on most titles, so a card's score is one lookup by
id, and the only network cost is one conditional download a day
(app/jobs/imdb_job.py).

Held as packed arrays, not a dictionary: a dict of 1.7 million tuples is
over a hundred megabytes; three arrays of plain numbers are fifteen. The file
is sorted by id *as text*, which is numeric order within one id length, so
rows are kept in one bucket per length and a lookup is a binary search.
Parsing takes seconds, so what was parsed is written back out as the arrays
themselves and a restart reads them in milliseconds.
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
import time
from pathlib import Path
from typing import Any, Iterable

URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"

# The licence for the file asks for this wherever the data is shown.
ATTRIBUTION = "Information courtesy of IMDb (https://www.imdb.com). Used with permission."

# The real file has 1.7 million rows; a small fraction of that is an error
# page or a truncated download, and is not allowed to replace it.
MIN_ROWS = 100_000

ID = re.compile(r"^tt(\d{7,10})$")
LAYOUT = {"ids": "I", "scores": "B", "votes": "I"}
CHUNK = 1 << 22

# A 9.4 from forty votes has been rated by the crew; an 8.5 from half a
# million by everybody. Sorting pulls every score toward an ordinary one by
# PRIOR_VOTES -- IMDb's own top-250 formula. Scores are tenths: 65 is 6.5.
PRIOR_VOTES = 1000
PRIOR_SCORE = 65


def weighted(score: int, votes: int) -> float:
    votes = max(0, votes)
    return (votes * score + PRIOR_VOTES * PRIOR_SCORE) / (votes + PRIOR_VOTES)


def _empty() -> tuple[array.array, array.array, array.array]:
    return tuple(array.array(code) for code in LAYOUT.values())  # type: ignore[return-value]


def parse(path: Path) -> dict[int, tuple]:
    """The file, as {id length: (ids, scores, votes)}."""
    buckets: dict[int, tuple] = {}
    tail = b""
    with gzip.open(path, "rb") as handle:
        if not handle.readline().startswith(b"tconst"):
            raise ValueError("that is not IMDb's ratings file")
        while True:
            chunk = handle.read(CHUNK)
            data = tail + chunk
            if chunk:
                cut = data.rfind(b"\n")
                if cut < 0:
                    tail = data
                    continue
                tail, data = data[cut + 1 :], data[:cut]
            else:
                tail = b""
            if data and not _take(buckets, data):
                _take_lines(buckets, data)
            if not chunk:
                break
    for size, (ids, scores, counts) in list(buckets.items()):
        if all(a < b for a, b in zip(ids, itertools.islice(ids, 1, None))):
            continue
        order = sorted(range(len(ids)), key=ids.__getitem__)
        buckets[size] = (
            array.array("I", (ids[i] for i in order)),
            array.array("B", (scores[i] for i in order)),
            array.array("I", (counts[i] for i in order)),
        )
    return buckets


def _take(buckets: dict[int, tuple], data: bytes) -> bool:
    tokens = data.split()
    ids, scores, votes = tokens[0::3], tokens[1::3], tokens[2::3]
    if len(tokens) % 3 or not all(token.startswith(b"tt") for token in ids):
        return False
    sizes = set(map(len, ids))
    try:
        numbers = [int(token[2:]) for token in ids]
        tenths = [int(token.replace(b".", b"")) if b"." in token else int(token) * 10 for token in scores]
        counts = list(map(int, votes))
        parts = {}
        for size in sizes:
            keep = range(len(ids)) if len(sizes) == 1 else [at for at, token in enumerate(ids) if len(token) == size]
            parts[size - 2] = (
                array.array("I", [numbers[at] for at in keep]),
                array.array("B", [tenths[at] for at in keep]),
                array.array("I", [counts[at] for at in keep]),
            )
    except (ValueError, OverflowError):
        return False
    if any(score > 100 for score in tenths):
        return False
    for size, columns in parts.items():
        bucket = buckets.setdefault(size, _empty())
        for column, more in zip(bucket, columns):
            column.extend(more)
    return True


def _take_lines(buckets: dict[int, tuple], data: bytes) -> None:
    for line in data.split(b"\n"):
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
        bucket = buckets.setdefault(len(digits), _empty())
        bucket[0].append(number)
        bucket[1].append(min(max(tenths, 0), 100))
        bucket[2].append(min(max(votes, 0), 0xFFFFFFFF))


def _day(header: str) -> str:
    try:
        return email.utils.parsedate_to_datetime(header).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


class Ratings:
    """Looked up in memory, cached on disk. Reading never takes a lock: a
    refresh builds its arrays apart and swaps the whole table in one
    assignment, so a lookup sees the old table or the new one, never half."""

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder
        self.table: dict[int, tuple] = {}
        self.meta: dict[str, Any] = {}

    @property
    def bin_path(self) -> Path:
        assert self.folder is not None
        return self.folder / "ratings.bin"

    @property
    def meta_path(self) -> Path:
        assert self.folder is not None
        return self.folder / "meta.json"

    def get(self, imdb_id: object) -> tuple[int, int] | None:
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

    def count(self) -> int:
        return sum(len(bucket[0]) for bucket in self.table.values())

    def status(self) -> dict[str, Any]:
        return {
            "titles": self.count(),
            "file_date": self.meta.get("fileDate", ""),
            "checked_at": self.meta.get("checkedAtIso", ""),
            "attribution": ATTRIBUTION,
        }

    def load(self) -> bool:
        """Read the arrays back from the last parse; False if there are none
        or they do not add up (another width or byte order, a short file)."""
        if self.folder is None:
            return False
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

    def save(self, table: dict[int, tuple], meta: dict[str, Any]) -> dict[str, Any]:
        assert self.folder is not None
        self.folder.mkdir(parents=True, exist_ok=True)
        meta = {
            **meta,
            "byteorder": sys.byteorder,
            "widths": {code: array.array(code).itemsize for code in LAYOUT.values()},
            "buckets": {str(size): len(table[size][0]) for size in sorted(table)},
        }
        partial = self.bin_path.with_suffix(".tmp")
        with open(partial, "wb") as handle:
            for size in sorted(table):
                for column in table[size]:
                    column.tofile(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, self.bin_path)
        self.write_meta(meta)
        return meta

    def write_meta(self, meta: dict[str, Any]) -> None:
        partial = self.meta_path.with_suffix(".tmp")
        partial.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(partial, self.meta_path)

    def due(self, refresh_hours: int) -> bool:
        if not self.table:
            return True
        checked = float(self.meta.get("checkedAt") or 0)
        return time.time() - checked >= refresh_hours * 3600

    def refresh(self, fetch_file: Any) -> bool:
        """Fetch the file if it changed and swap it in; True if it had.
        fetch_file is providers.net.fetch_file (passed in, so this module has
        no network import and the tests can hand it a fake)."""
        assert self.folder is not None
        self.folder.mkdir(parents=True, exist_ok=True)
        have = bool(self.table)
        gz = self.folder / "title.ratings.tsv.gz"
        got = fetch_file(URL, gz, etag=self.meta.get("etag", "") if have else "", modified=self.meta.get("lastModified", "") if have else "")
        stamp = {"checkedAt": time.time(), "checkedAtIso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if got.get("not_modified"):
            self.meta = {**self.meta, **stamp}
            self.write_meta(self.meta)
            return False
        if not got:
            raise OSError("the download came back empty")
        try:
            table = parse(gz)
        finally:
            gz.unlink(missing_ok=True)
        rows = sum(len(bucket[0]) for bucket in table.values())
        if rows < MIN_ROWS:
            raise ValueError(f"only {rows} rows -- not keeping it")
        meta = {"schema": 1, **stamp, "etag": got.get("etag", ""), "lastModified": got.get("last_modified", ""), "fileDate": _day(got.get("last_modified", ""))}
        self.table, self.meta = table, self.save(table, meta)
        return True


STORE = Ratings()


def configure(folder: Path) -> None:
    STORE.folder = folder
    STORE.load()


def scores_for(ids: Iterable[object]) -> dict[str, list[int]]:
    """{imdb id: [score in tenths, votes]} for the ones that have a rating."""
    out: dict[str, list[int]] = {}
    for imdb_id in ids:
        if not imdb_id or imdb_id in out:
            continue
        found = STORE.get(imdb_id)
        if found:
            out[str(imdb_id)] = [found[0], found[1]]
    return out
