"""The handful of names the provider code was written against in the old
app (its config constants, its netio and normalize helpers), mapped onto
this app's modules. The lookup, resolve and fill-in logic was ported as it
was -- it encodes years of provider quirks -- and this is the seam that lets
it run on the new network layer (net.py) and the new config without
rewriting it.

Provider results still use the old field names (imdbId, wikiUrl, poster...);
fields.py turns them into this app's at the boundary.
"""
from __future__ import annotations

from typing import Any

from app.providers import net

# A type made up in the app ("audiobook") is looked up as what it is closest
# to: no catalogue files an audio book apart from the book it was read from.
LOOKUP_AS = {"audiobook": "book", "radio-drama": "other", "music": "music"}


class Keys:
    """Read at call time, so configure() at startup takes effect."""

    tmdb = ""
    omdb = ""
    network = True


KEYS = Keys()
BREAKER = net.BREAKER


def configure(tmdb_key: str, omdb_key: str, network: bool) -> None:
    KEYS.tmdb = tmdb_key.strip()
    KEYS.omdb = omdb_key.strip()
    KEYS.network = network


def fetch_json(address: str, timeout: float = 6.0, limit: int = 4_000_000, tries: int = 2) -> Any:
    return net.fetch_json(address, timeout=timeout, limit=limit, tries=tries)


def fetch_text(address: str, timeout: float = 8.0, limit: int = 600_000) -> str:
    return net.fetch_text(address, timeout=timeout, limit=limit)


def proxy_img(address: str) -> str:
    """The old app wrapped every poster in its own proxy path here. This app
    keeps the provider's URL on the title and serves it through the poster
    cache by key (reference/images.py), so the URL passes through as is."""
    return address or ""


def text(value: object, limit: int, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        value = str(value)
    return value.strip()[:limit]


def url(value: object) -> str:
    from app.media.normalize import url as clean_url

    return clean_url(value)


def log(*parts: object) -> None:
    print("[providers]", *parts, flush=True)
