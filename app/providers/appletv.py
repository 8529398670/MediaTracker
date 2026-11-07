"""Where a title is on Apple TV, from Wikidata.

Wikidata records Apple TV's own ids for films (P9586) and shows (P9751), and
links them to IMDb ids (P345) -- which most of the library carries. So one
SPARQL query per 250 titles turns IMDb ids into tv.apple.com links, no key
needed. A title whose id is not on Wikidata simply keeps the search link.

The query service rate-limits hard when it is under strain (at times one
request a minute, answered with a 429 for anything faster). A throttled batch
waits out the minute once and is asked again; if it is still refused, the
lookup stops there and says so, and the ids it never got an answer for are
left for the next run instead of failing the whole job.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

from app.providers import net

SPARQL = "https://query.wikidata.org/sparql"
BATCH = 250
IMDB_ID = re.compile(r"^tt\d{6,10}$")
APPLE_ID = re.compile(r"^umc\.c[a-z]{2}\.[a-z0-9]{10,40}$")
# How long a throttled batch waits before its one second try: the strictest
# rule the query service has used is one request a minute.
THROTTLE_WAIT = 65.0


@dataclass
class Lookup:
    found: dict[str, str] = field(default_factory=dict)  # IMDb id -> movie/<id> or show/<id>
    answered: set[str] = field(default_factory=set)  # ids Wikidata actually gave an answer for
    throttled: bool = False


def _throttle(error: urllib.error.HTTPError) -> bool:
    return error.code in (429, 503)


def lookup(imdb_ids: list[str], pause: Callable[[float], bool] | None = None) -> Lookup:
    """Apple TV paths for the ones Wikidata has. pause(seconds) waits before
    a throttled batch is asked again and returns False if the caller wants
    to stop instead."""
    ids = [ident for ident in imdb_ids if IMDB_ID.match(ident)]
    result = Lookup()
    out = result.found
    for at in range(0, len(ids), BATCH):
        chunk = ids[at : at + BATCH]
        query = (
            "SELECT ?imdb ?movie ?show WHERE {\n"
            "  VALUES ?imdb { " + " ".join(f'"{ident}"' for ident in chunk) + " }\n"
            "  ?item wdt:P345 ?imdb .\n"
            "  OPTIONAL { ?item wdt:P9586 ?movie . }\n"
            "  OPTIONAL { ?item wdt:P9751 ?show . }\n"
            "  FILTER(BOUND(?movie) || BOUND(?show))\n"
            "}"
        )
        address = f"{SPARQL}?format=json&query={urllib.parse.quote(query)}"
        try:
            payload = net.fetch_json(address, timeout=30, tries=2)
        except urllib.error.HTTPError as error:
            if not _throttle(error):
                raise
            if pause is None or not pause(THROTTLE_WAIT):
                result.throttled = True
                break
            try:
                payload = net.fetch_json(address, timeout=30, tries=1)
            except urllib.error.HTTPError as again:
                if not _throttle(again):
                    raise
                result.throttled = True
                break
        result.answered.update(chunk)
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
    return result
