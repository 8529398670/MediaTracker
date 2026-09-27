#!/usr/bin/env python3
"""IMDb's ratings file, and what Discover does with it.

Offline and instant: the file is a few lines written here in IMDb's own
format, and the download is a function that copies it into place. The shapes
that matter are the ones the real file has — ids of two lengths interleaved,
because it is sorted as text — and the ones it might one day have: a line
that does not read, a download that is not the file, a cache written by
something else.

    python3 tests/test_imdb.py
"""

import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import certs                                            # noqa: E402
import imdb                                             # noqa: E402
import lists                                            # noqa: E402


# In the order IMDb writes them: sorted as text, so the eight-digit ids fall
# between the seven-digit ones rather than after them.
LINES = [
    ("tt0000001", "5.7", 2000),
    ("tt0034583", "8.5", 661592),      # Casablanca
    ("tt1000000", "9.4", 40),
    ("tt10000000", "8.5", 500000),
    ("tt10000001", "10.0", 7),
    ("tt1000001", "6.1", 1234),
]


def write_file(path: Path, lines=LINES, extra: str = "") -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("tconst\taverageRating\tnumVotes\n")
        for tconst, score, votes in lines:
            handle.write(f"{tconst}\t{score}\t{votes}\n")
        handle.write(extra)
    return path


FAILED = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(label)
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


def main() -> int:
    scratch = Path(tempfile.mkdtemp())
    try:
        run(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all good'}")
    return 1 if FAILED else 0


def run(scratch: Path) -> None:
    # -- reading the file --------------------------------------------------
    table = imdb.parse(write_file(scratch / "a.tsv.gz"))
    store = imdb.Ratings(scratch / "cache")
    store.table = table
    check("the ids are kept apart by length, each already in order",
          {size: list(bucket[0]) for size, bucket in table.items()},
          {7: [1, 34583, 1000000, 1000001], 8: [10000000, 10000001]})
    check("a score is kept in tenths", store.get("tt0034583"), (85, 661592))
    check("including a perfect one", store.get("tt10000001"), (100, 7))
    check("an eight-digit id is found in its own bucket",
          store.get("tt10000000"), (85, 500000))
    check("however it was typed", store.get(" TT1000001 "), (61, 1234))
    check("an id nobody has rated has no score", store.get("tt0000002"), None)
    check("and something that is not an id has none either",
          [store.get(v) for v in ("", None, "nm0000001", "tt12", "tt00000001x")],
          [None] * 5)
    check("many at once answers only for the ones that have a score",
          store.many(["tt0000001", "tt0000002", "TT1000000"]),
          {"tt0000001": [57, 2000], "tt1000000": [94, 40]})

    small, imdb.CHUNK = imdb.CHUNK, 37
    try:
        check("a chunk that ends mid-line reads the same as one that does not",
              imdb.parse(scratch / "a.tsv.gz"), table)
    finally:
        imdb.CHUNK = small

    odd = imdb.parse(write_file(scratch / "b.tsv.gz",
                                extra="tt2000000\t\\N\t5\nnonsense\ntt2000001\t7.0\t9\n"))
    check("a line that does not read is skipped, and the rest still are not",
          {size: list(bucket[0]) for size, bucket in odd.items()},
          {7: [1, 34583, 1000000, 1000001, 2000001], 8: [10000000, 10000001]})

    shuffled = imdb.parse(write_file(scratch / "c.tsv.gz", lines=LINES[::-1]))
    check("a file out of order is put in order rather than searched wrongly",
          list(shuffled[7][0]), [1, 34583, 1000000, 1000001])

    with gzip.open(scratch / "e.tsv.gz", "wt") as handle:
        handle.write("<html>not the file</html>\n")
    try:
        imdb.parse(scratch / "e.tsv.gz")
        check("a page that is not the file is refused", "parsed", "refused")
    except ValueError:
        check("a page that is not the file is refused", "refused", "refused")

    # -- the cache -------------------------------------------------------
    store.meta = store.save(table, {"fileDate": "2026-09-26", "checkedAt": 1})
    again = imdb.Ratings(scratch / "cache")
    check("what was parsed reads back from disk as it was",
          [again.load(), again.table, again.status()["date"]],
          [True, table, "2026-09-26"])

    meta = json.loads(again.meta_path.read_text())
    again.meta_path.write_text(json.dumps({**meta, "byteorder": "middle"}))
    check("a cache written in another byte order is not read",
          imdb.Ratings(scratch / "cache").load(), False)
    again.meta_path.write_text(json.dumps(meta))
    with open(again.bin_path, "ab") as handle:
        handle.write(b"\0")
    check("nor one whose length does not add up",
          imdb.Ratings(scratch / "cache").load(), False)

    # -- fetching --------------------------------------------------------
    # The download is a copy of a file written here; what is being tested is
    # what is done with what comes back.
    source = {"path": write_file(scratch / "f.tsv.gz"), "answer": None}

    def fake_fetch(url, dest, etag="", modified=""):
        source["asked"] = (etag, modified)
        if source["answer"]:
            return source["answer"]
        shutil.copy(source["path"], dest)
        return {"etag": '"v1"', "lastModified": "Sat, 26 Sep 2026 12:46:16 GMT"}

    real = (imdb.fetch_file, imdb.NET_ENABLED, imdb.MIN_ROWS)
    imdb.fetch_file, imdb.NET_ENABLED, imdb.MIN_ROWS = fake_fetch, True, 3
    try:
        fresh = imdb.Ratings(scratch / "fresh")
        check("with no cache the whole file is asked for, not whether it changed",
              [fresh.refresh(), source["asked"]], [True, ("", "")])
        check("and it is in use at once",
              [fresh.get("tt0034583"), fresh.status()["date"]],
              [(85, 661592), "2026-09-26"])
        check("the download is not kept once it has been read",
              fresh.gz_path.exists(), False)
        check("and it is not asked for again until tomorrow",
              0 < fresh.due_in() <= imdb.REFRESH_SECONDS, True)

        source["answer"] = {"notModified": True}
        check("the next time, it asks whether the file has changed",
              [fresh.refresh(), source["asked"]],
              [False, ('"v1"', "Sat, 26 Sep 2026 12:46:16 GMT")])
        check("and an unchanged file leaves the table as it was",
              fresh.get("tt0034583"), (85, 661592))

        source["answer"] = None
        source["path"] = write_file(scratch / "g.tsv.gz", lines=LINES[:2])
        try:
            fresh.refresh()
            check("a file far shorter than the real one is refused", "kept", "refused")
        except ValueError:
            check("a file far shorter than the real one is refused", "refused", "refused")
        check("and the one already held stands", fresh.get("tt1000001"), (61, 1234))
    finally:
        imdb.fetch_file, imdb.NET_ENABLED, imdb.MIN_ROWS = real

    # -- ranking ---------------------------------------------------------
    check("a 9.4 from forty people ranks below an 8.5 from half a million",
          imdb.weighted(94, 40) < imdb.weighted(85, 500_000), True)
    check("with enough votes the score is very nearly the score",
          round(imdb.weighted(85, 500_000)), 85)

    # -- Discover --------------------------------------------------------
    rows = [
        ["w:a", 1931, 40, "a", [], [], 0, []],
        ["w:b", 1933, 30, "b", [], [], 0, []],
        ["w:c", 1935, 20, "c", [], [], 0, []],
        ["w:d", 1949, 10, "d", [], [], 0, []],
        ["w:e", None, 5, "e", [], [], 0, []],
        # The merge files a film under the year it came out and the year it
        # topped the box office, so one key can have two rows.
        ["w:c", 1936, 1, "c", [], [], 0, []],
    ]
    lists.catalogue = lambda: rows
    lists.full_records = lambda page: [{"key": r[lists.R_KEY]} for r in page]
    lists.coverage = lambda: {}
    shown = lambda **kw: [f["key"] for f in lists.query(**kw)["films"]]

    marks = certs.Certs(scratch / "certs.json")
    marks.put("w:a", "tt0000001", [])     # 5.7 from 2000
    marks.put("w:b", "tt1000000", [])     # 9.4 from 40
    marks.put("w:c", "tt10000000", [])    # 8.5 from 500000
    marks.put("w:d", "", [])              # no IMDb id; w:e never asked
    real_certs, certs.STORE = certs.STORE, marks
    real_imdb, imdb.STORE = imdb.STORE, store
    try:
        check("the notable order is left alone unless asked",
              shown(), ["w:a", "w:b", "w:c", "w:d", "w:e"])
        check("a film filed under two years is shown once, and counted once",
              [shown(sort="imdb").count("w:c"), lists.query()["total"]], [1, 5])
        check("by IMDb: the most agreed-on first, and the unscored after, as they were",
              shown(sort="imdb"), ["w:c", "w:b", "w:a", "w:d", "w:e"])
        page = {f["key"]: f for f in lists.query(sort="imdb")["films"]}
        check("the score comes down with the row, with the id it was found by",
              [page["w:c"]["imdb"], page["w:c"]["imdbScore"]],
              ["tt10000000", [85, 500000]])
        check("and a row with no score says so rather than leaving it out",
              [page["w:d"]["imdbScore"], page["w:e"]["imdbScore"]], [None, None])
        marks.put("w:d", "tt1000001", [])     # 6.1 from 1234, learned just now
        check("an id learned after the ranking was worked out is ranked at once",
              shown(sort="imdb"), ["w:c", "w:b", "w:d", "w:a", "w:e"])
        check("the facts call looks the score up as it leaves",
              lists._scored({"imdb": "tt0000001", "thumb": ""})["imdbScore"], [57, 2000])
    finally:
        certs.STORE = real_certs
        imdb.STORE = real_imdb


if __name__ == "__main__":
    sys.exit(main())
