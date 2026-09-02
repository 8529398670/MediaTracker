"""Talking to the outside world, and the two governors on it.

`HostPace` keeps us inside each host's rate limit on the way out, `Breaker`
stops us calling a provider that has just timed out, and `RateLimiter` caps
what one caller can ask of our own outbound endpoints.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

from config import UA


IMG_HOSTS = re.compile(
    r"^(?:[a-z0-9-]+\.)*"
    r"(?:mzstatic\.com|tvmaze\.com|openlibrary\.org|tmdb\.org|media-amazon\.com"
    r"|wikimedia\.org|omdbapi\.com|rawg\.io)$",
    re.I,
)

class HostPace:
    """A minimum gap between calls to the same host, and backoff after a 429.

    These providers are free and unauthenticated, so politeness is the only
    thing between this and a rate limit — and a rate limit here is invisible,
    because a throttled provider just looks like a title with no data. The
    limits that matter: Wikimedia wants about a call a second, and Apple's
    search endpoint allows roughly twenty a minute.
    """

    LIMITS = {
        "wikidata.org": 1.1,
        "wikipedia.org": 1.1,
        "wikimedia.org": 1.1,
        "itunes.apple.com": 3.0,
        "api.tvmaze.com": 0.6,
        "openlibrary.org": 1.0,
        "www.omdbapi.com": 0.4,
        "api.themoviedb.org": 0.06,
    }

    def __init__(self, default: float = 0.3) -> None:
        self.default = default
        self.next_at: dict[str, float] = {}
        self.penalty: dict[str, float] = {}
        self.lock = threading.Lock()

    def gap(self, host: str) -> float:
        for name, seconds in self.LIMITS.items():
            if host == name or host.endswith("." + name):
                return seconds
        return self.default

    def wait(self, host: str) -> None:
        with self.lock:
            due = max(self.next_at.get(host, 0.0), time.monotonic())
            self.next_at[host] = due + self.gap(host) + self.penalty.get(host, 0.0)
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(min(delay, 60.0))

    def throttled(self, host: str, retry_after: float = 0.0) -> None:
        with self.lock:
            step = min(max(self.penalty.get(host, 0.0) * 2, 1.0), 30.0)
            self.penalty[host] = max(step, min(retry_after, 30.0))
            self.next_at[host] = time.monotonic() + self.penalty[host]

    def eased(self, host: str) -> None:
        with self.lock:
            if host not in self.penalty:
                return
            self.penalty[host] /= 2
            if self.penalty[host] < 0.2:
                del self.penalty[host]


PACE = HostPace()


def fetch_json(url: str, timeout: float = 6.0, limit: int = 4_000_000,
               tries: int = 2) -> object:
    host = urllib.parse.urlsplit(url).hostname or ""
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(max(1, tries)):
        PACE.wait(host)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = json.loads(response.read(limit).decode("utf-8", "replace"))
            PACE.eased(host)
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt + 1 >= tries:
                raise
            try:
                after = float(exc.headers.get("Retry-After") or 0)
            except (TypeError, ValueError):
                after = 0.0
            PACE.throttled(host, after)
    return None


# A poster is drawn in a 52x78 box. Providers hand back something far larger
# than that — TMDB's w342 is a 342px-wide image, six times the width it will
# ever be shown at — and every one of those pixels costs bandwidth to move and
# CPU to decode, on a machine that has little of either. So the size is
# stepped down to the largest the layout can actually use on a dense screen.
#
# Only rewrites that are certain are made: each of these providers encodes the
# size in the path in a documented, fixed way. Anything else is fetched as-is,
# and a rewrite that 404s falls back to the original URL.
SMALLER = (
    ("https://image.tmdb.org/t/p/w342/", "https://image.tmdb.org/t/p/w185/"),
    ("https://image.tmdb.org/t/p/w500/", "https://image.tmdb.org/t/p/w185/"),
    ("https://image.tmdb.org/t/p/original/", "https://image.tmdb.org/t/p/w185/"),
    ("-L.jpg", "-M.jpg"),                       # covers.openlibrary.org
    ("/original_", "/medium_portrait_"),        # static.tvmaze.com
)


# A 52px-wide box is 156px on a three-times-dense phone screen, so nothing
# needs to arrive wider than this. TMDB's own w185 step is the same idea.
WIDTH = 240


def smaller_img(url: str) -> str:
    """The same artwork at a size the card can actually use, where we can."""
    for big, small in SMALLER:
        if big in url:
            return url.replace(big, small, 1)

    # Wikimedia serves the same file three ways. Thumbnails carry the width in
    # the filename; Special:FilePath takes it as a query parameter; a plain
    # upload path has no size in it at all and is left alone, since guessing
    # a thumbnail URL for it is not reliable enough to be worth a failed call.
    match = re.search(r"/thumb/.*/(\d+)px-", url)
    if match and int(match.group(1)) > WIDTH:
        return url[:match.start(1)] + str(WIDTH) + url[match.end(1):]

    match = re.search(r"([?&]width=)(\d+)", url)
    if match and "wikimedia.org" in url and int(match.group(2)) > WIDTH:
        return url[:match.start(2)] + str(WIDTH) + url[match.end(2):]
    return url


def proxy_img(url: str) -> str:
    if not url:
        return ""
    return "/api/img?u=" + urllib.parse.quote(url, safe="")

class RateLimiter:
    def __init__(self, allowance: int, window: float) -> None:
        self.allowance = allowance
        self.window = window
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if len(self.hits) > 4096:
                self.hits.clear()
            bucket = self.hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.allowance:
                return False
            bucket.append(now)
            return True


class Breaker:
    """Stop calling a provider that just timed out.

    Providers are queried in sequence, so one unreachable host would otherwise
    add its full timeout to every single lookup.
    """

    def __init__(self, threshold: int = 2, cooldown: float = 600.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.state: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()

    def is_open(self, name: str) -> bool:
        with self.lock:
            fails, until = self.state.get(name, (0, 0.0))
            if fails >= self.threshold and time.monotonic() < until:
                return True
            return False

    def record(self, name: str, ok: bool) -> None:
        with self.lock:
            if ok:
                self.state.pop(name, None)
                return
            fails = self.state.get(name, (0, 0.0))[0] + 1
            self.state[name] = (fails, time.monotonic() + self.cooldown)


BREAKER = Breaker()
OUTBOUND_LIMIT = RateLimiter(180, 60.0)
