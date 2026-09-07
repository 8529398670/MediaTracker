"""What a film was rated, kept where it survives the merge being rebuilt.

The age rating is the one fact on a Discover row that answers a different
question from all the others.  Year, genre, cast and gross say what a film
*is*; G, PG, PG-13, R say what kind of evening it is, and who can be in the
room for it.  That makes it something to filter by rather than only something
to read — and filtering by it is exactly what could not be done while the
rating lived in a dictionary that was thrown away when the process stopped.

Wikidata holds it as P1657, one query for fifty films.  Fifty films is also
about a second and a half, so a century of these lists — twenty-eight
thousand of them — is a quarter of an hour of asking.  That is a thing you
pay for once, and then only for the years harvested since.  So it is written
down here, keyed by the same catalogue key a verdict uses, and the browsing
of Discover reads it from disk instead of asking Wikidata again.

Two things are stored per film rather than one.  The rating is the point; the
IMDb id arrives in the same answer to the same query, and it is what turns
the two IMDb links on a row — the film, and its parents guide, which is the
long-form version of the rating standing beside it.  Dropping it would mean
asking Wikidata a second time for something it had already said.

It lives beside ``verdicts.json`` and not inside ``data/lists/`` for one
reason: ``data/lists/`` is meant to be safe to delete and harvest again, and
a quarter of an hour of Wikidata is not something to lose by re-collecting a
decade.  The catalogue key is stable across a rebuild, so what is here still
finds its film afterwards.

Three states, and they are not two.  A film can be rated, or known to have no
rating — most films before November 1968 never had one, and Wikidata says so
by having nothing to say — or *not yet asked about*, which is what every film
is until the pass has run.  A filter that folds the last two together would
show an empty list and call it an answer.
"""

from __future__ import annotations

import json
import os
import threading
import time

from config import DATA_DIR, log, now_iso

CERTS_PATH = DATA_DIR / "certs.json"

# The MPA's own trail, least restrictive first.  M, GP and M/PG are the
# short-lived middles of 1968-1972 and they turn up in a century of films
# often enough to be worth a place; X ran until NC-17 replaced it in 1990.
# The order is the order a person reads a rating scale in, which is why the
# picker is not sorted by count the way the genres are.
ORDER = ("G", "M", "GP", "M/PG", "PG", "PG-13", "R", "NC-17", "X")

# The two answers that are not ratings but are the whole reason the picker is
# honest: what Wikidata says has none, and what has not been asked yet.
NONE = "none"
UNKNOWN = "unknown"

LABELS = {NONE: "Not rated", UNKNOWN: "Not looked up"}

# A rating is a short token — the longest here is six characters. Anything
# longer arrived as something that is not a rating, and is dropped rather
# than offered as a chip nobody can use.
MAX_RATING = 12

# One row per film in a century of lists is about forty-five thousand. The
# cap is here so a loop somewhere cannot fill the volume.
MAX_FILMS = 200_000

# Entries are positional, the same way the lean catalogue rows are: the file
# is one line per film and twenty-eight thousand of them, so the field names
# would be most of it.
E_IMDB, E_RATINGS = 0, 1


def clean(label: str) -> str:
    """One rating as it should be stored, or empty if it is not one.

    Wikidata's label service answers with the item id when an item has no
    English label, and an id is not a rating anyone can read.
    """
    text = str(label or "").strip().upper()
    if not text or len(text) > MAX_RATING:
        return ""
    if text.startswith("Q") and text[1:].isdigit():
        return ""
    return text


def in_order(names) -> list[str]:
    """The ratings a film carries, on the scale, least restrictive first.

    A film can hold more than one and the second is usually the story: *A
    Clockwork Orange* is X and R, because it was cut and rated again three
    years later.  Both are true and both should find it, so both are kept —
    and the one shown is the first here, which is the one it is rated now.
    """
    seen = []
    for name in names or []:
        name = clean(name)
        if name and name not in seen:
            seen.append(name)
    return sorted(seen, key=lambda r: (ORDER.index(r) if r in ORDER else len(ORDER), r))


class Certs:
    """The rating file, guarded by a lock and written atomically.

    Unlike the verdicts beside it this is not written through on every change:
    a fill pass learns fifty films a second and a half, and rewriting a
    megabyte each time would be most of the work.  So it is flushed on a timer
    and always at the end of a pass, and the worst a crash mid-pass can cost
    is the few seconds of asking since the last write.
    """

    FLUSH_SECONDS = 20.0

    def __init__(self, path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, list] = {}
        self.loaded = False
        self.dirty = False
        self.wrote = 0.0

    # ---------------------------------------------------------------- disk

    def load(self) -> None:
        with self.lock:
            if self.loaded:
                return
            self.loaded = True
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            given = (raw or {}).get("films")
            if not isinstance(given, dict):
                return
            for key, entry in given.items():
                if not isinstance(key, str) or not isinstance(entry, list):
                    continue
                imdb = str(entry[E_IMDB] if len(entry) > E_IMDB else "")[:16]
                self.data[key] = [imdb, in_order(entry[E_RATINGS:])]
            log(f"certs: {len(self.data)} films, {self.rated()} with a rating")

    def flush(self, force: bool = False) -> None:
        """Write, if there is anything to write and it is time to."""
        with self.lock:
            if not self.dirty:
                return
            if not force and time.monotonic() - self.wrote < self.FLUSH_SECONDS:
                return
            payload = json.dumps(
                {"schema": 1, "updatedAt": now_iso(),
                 "films": {key: [entry[E_IMDB], *entry[E_RATINGS]]
                           for key, entry in self.data.items()}},
                ensure_ascii=False, separators=(",", ":"))
            # Counted as an attempt whether or not it lands, so a disk that
            # is refusing is not hammered once a batch.
            self.wrote = time.monotonic()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        # Only now: a write that threw leaves this dirty, so the next flush
        # tries again rather than believing the file holds what memory does.
        with self.lock:
            self.dirty = False

    # --------------------------------------------------------------- using

    def put(self, key: str, imdb: str = "", ratings=()) -> None:
        """Remember what Wikidata said, including that it said nothing.

        An answer of nothing is the answer for most of a century of films and
        it has to be written down, or every pass asks about them all again.
        """
        self.load()
        key = str(key or "").strip()
        if not key:
            return
        with self.lock:
            if key not in self.data and len(self.data) >= MAX_FILMS:
                return
            self.data[key] = [str(imdb or "")[:16], in_order(ratings)]
            self.dirty = True

    def get(self, key: str) -> list:
        """``[imdb, [ratings]]`` for a film that has been asked about."""
        self.load()
        with self.lock:
            entry = self.data.get(key)
            return ["", []] if entry is None else [entry[E_IMDB], list(entry[E_RATINGS])]

    def known(self, key: str) -> bool:
        """Whether this film has been asked about at all."""
        self.load()
        with self.lock:
            return key in self.data

    def snapshot(self) -> dict[str, list]:
        """Every answer at once, for a walk that cannot take the lock per row.

        A query touches twenty-eight thousand rows and a fill pass may be
        writing underneath it; copying the mapping once is a millisecond and
        it is what stops the walk seeing a dictionary change size.
        """
        self.load()
        with self.lock:
            return dict(self.data)

    def rated(self) -> int:
        with self.lock:
            return sum(1 for entry in self.data.values() if entry[E_RATINGS])

    def counts(self) -> dict:
        """How much of the catalogue has an answer, in the three states."""
        self.load()
        with self.lock:
            asked = len(self.data)
            rated = sum(1 for entry in self.data.values() if entry[E_RATINGS])
        return {"asked": asked, "rated": rated, "none": asked - rated}


STORE = Certs(CERTS_PATH)
