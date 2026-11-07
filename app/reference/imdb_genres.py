"""IMDb's genres, for the titles this app knows about.

The same family of files as the ratings (reference/imdb.py), under the same
personal, non-commercial licence: title.basics has up to three genres for
every title on IMDb. It is the one source that covers the old films Wikipedia's
lists say nothing about, and it says Musical and Film-Noir outright.

The file is big (230 MB compressed, twelve million lines, most of them single
television episodes), and this app wants a few tens of thousands of those
lines. So it is read as a stream, only the ids asked for are kept, and the
download is thrown away afterwards: what stays is one small JSON file. A title
added since then is picked up by the next refresh.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from app.media.genres import canon_genres

URL = "https://datasets.imdbws.com/title.basics.tsv.gz"

# The real file has twelve million rows; an error page or a truncated download
# is a small fraction of that, and is not allowed to replace the table.
MIN_ROWS = 1_000_000
MAX_DOWNLOAD = 1024 * 1024 * 1024
NO_VALUE = "\\N"


def parse(path: Path, wanted: set[str], progress: Callable[[int], None] | None = None) -> tuple[dict[str, list[str]], int]:
    """The genres of the wanted ids, and how many rows the file had. Ids with
    no genre on IMDb are left out."""
    table: dict[str, list[str]] = {}
    rows = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="\n") as lines:
        for line in lines:
            rows += 1
            if progress and rows % 1_000_000 == 0:
                progress(rows)
            ident = line[: line.find("\t")]
            if ident not in wanted:
                continue
            cell = line.rstrip("\n").rsplit("\t", 1)[-1]
            if cell == NO_VALUE:
                continue
            found = canon_genres(cell.split(","), 3)
            if found:
                table[ident] = found
    return table, rows


class GenreTable:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder
        self.table: dict[str, list[str]] = {}
        self.meta: dict[str, Any] = {}

    @property
    def path(self) -> Path:
        assert self.folder is not None
        return self.folder / "genres.json"

    def get(self, imdb_id: object) -> list[str]:
        return list(self.table.get(str(imdb_id or ""), ()))

    def count(self) -> int:
        return len(self.table)

    def load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.table = payload.get("titles") or {}
        self.meta = {key: value for key, value in payload.items() if key != "titles"}

    def due(self, refresh_hours: int) -> bool:
        if not self.meta:
            return True
        return time.time() - float(self.meta.get("checkedAt") or 0) >= refresh_hours * 3600

    def refresh(self, fetch_file: Any, wanted: Iterable[str], progress: Callable[[int], None] | None = None) -> int:
        """Download, keep what is wanted, swap it in. Returns the titles held.
        Always a full download: the file changes daily, and the point of a
        refresh is often a new id rather than a new file."""
        assert self.folder is not None
        self.folder.mkdir(parents=True, exist_ok=True)
        gz = self.folder / "title.basics.tsv.gz"
        got = fetch_file(URL, gz, limit=MAX_DOWNLOAD, timeout=600.0)
        if not got:
            raise OSError("the download came back empty")
        try:
            table, rows = parse(gz, set(wanted), progress)
        finally:
            gz.unlink(missing_ok=True)
        if rows < MIN_ROWS:
            raise ValueError(f"only {rows} rows -- not keeping it")
        meta = {"schema": 1, "checkedAt": time.time(), "fileDate": time.strftime("%Y-%m-%d", time.gmtime()), "rows": rows}
        partial = self.path.with_suffix(".tmp")
        partial.write_text(json.dumps({**meta, "titles": table}), encoding="utf-8")
        os.replace(partial, self.path)
        self.table, self.meta = table, meta
        return len(table)


STORE = GenreTable()


def configure(folder: Path) -> None:
    STORE.folder = folder
    STORE.table, STORE.meta = {}, {}
    STORE.load()
