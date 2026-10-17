"""Where a title is on Apple TV, written onto it.

Apple has no public catalogue to ask, but Wikidata keeps Apple's own ids for
about fifty thousand films (P9586, "Apple TV movie ID") and three thousand
series (P9751, "Apple TV show ID"), and it can be asked by IMDb id — which
most titles here already carry. One query names a few hundred ids. Checked
2026-10-17: 588 of the 756 titles in this library with an IMDb id had one.

The id is all a link needs: ``https://tv.apple.com/us/movie/<id>`` redirects
to the film's page with its slug filled in. So what is stored on the title is
the end of that path, ``movie/umc.cmc.…`` or ``show/umc.cmc.…``, in the
``appleTv`` field beside ``imdbId``. Unlike an IMDb score it does not change
from day to day, so it belongs on the title.

A title Wikidata has no id for is remembered here for the life of the
process and asked about again after a restart: a few hundred ids are one
query, and the answer may have changed since. The app falls back to Apple's
search page for those.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse

from config import NET_ENABLED, log
from library import LIBRARY
from netio import fetch_json

SPARQL = "https://query.wikidata.org/sparql"
BATCH = 250
# A first look a little after start, so it does not compete with the boot,
# then again now and then for titles that have gained an IMDb id since.
FIRST_AFTER = 20.0
EVERY = 10 * 60.0

IMDB_ID = re.compile(r"^tt\d{6,10}$")
APPLE_ID = re.compile(r"^umc\.c[a-z]{2}\.[a-z0-9]{10,40}$")

_asked: set[str] = set()       # IMDb ids Wikidata had nothing for, this run
_lock = threading.Lock()


def lookup(imdb_ids: list[str]) -> dict[str, str]:
    """IMDb id -> ``movie/<id>`` or ``show/<id>``, for the ones Wikidata has."""
    ids = [i for i in imdb_ids if IMDB_ID.match(i)]
    out: dict[str, str] = {}
    for at in range(0, len(ids), BATCH):
        chunk = ids[at:at + BATCH]
        query = (
            "SELECT ?imdb ?movie ?show WHERE {\n"
            "  VALUES ?imdb { " + " ".join(f'"{i}"' for i in chunk) + " }\n"
            "  ?item wdt:P345 ?imdb .\n"
            "  OPTIONAL { ?item wdt:P9586 ?movie . }\n"
            "  OPTIONAL { ?item wdt:P9751 ?show . }\n"
            "  FILTER(BOUND(?movie) || BOUND(?show))\n"
            "}"
        )
        payload = fetch_json(f"{SPARQL}?format=json&query={urllib.parse.quote(query)}",
                             timeout=30, tries=3)
        if not isinstance(payload, dict):
            continue
        for row in (payload.get("results") or {}).get("bindings") or []:
            imdb = (row.get("imdb") or {}).get("value") or ""
            movie = (row.get("movie") or {}).get("value") or ""
            show = (row.get("show") or {}).get("value") or ""
            if imdb in out:
                continue
            if APPLE_ID.match(movie):
                out[imdb] = f"movie/{movie}"
            elif APPLE_ID.match(show):
                out[imdb] = f"show/{show}"
    return out


def fill() -> int:
    """Put an Apple TV id on every title that has an IMDb id and no Apple TV
    id yet, and that has not already come back empty this run. Answers how
    many titles were given one."""
    with _lock:
        items = LIBRARY.snapshot().get("items") or []
        wanted: dict[str, list[str]] = {}
        for item in items:
            imdb = item.get("imdbId") or ""
            if item.get("deleted") or item.get("appleTv") or not imdb or imdb in _asked:
                continue
            wanted.setdefault(imdb, []).append(item["id"])
        if not wanted:
            return 0
        found = lookup(sorted(wanted))
        _asked.update(i for i in wanted if i not in found)
        patches = {item_id: {"appleTv": path}
                   for imdb, path in found.items() for item_id in wanted.get(imdb, [])}
        changed = LIBRARY.patch_many(patches)
        if changed:
            log(f"appletv: {changed} titles linked to Apple TV, "
                f"{len(wanted) - len(found)} with no id on Wikidata")
        return changed


def _loop() -> None:
    time.sleep(FIRST_AFTER)
    while True:
        try:
            fill()
        except Exception as exc:  # a bad answer must not stop the loop
            log(f"!! appletv: {type(exc).__name__}: {exc}")
        time.sleep(EVERY)


def start() -> None:
    if NET_ENABLED:
        threading.Thread(target=_loop, daemon=True, name="appletv").start()
