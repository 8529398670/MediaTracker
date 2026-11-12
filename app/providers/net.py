"""Talking to the outside world, safely and politely.

Three governors sit on every outbound call:

- HostPace keeps us inside each host's rate limit (Wikimedia wants about a
  call a second; Apple's search allows about twenty a minute). A throttled
  provider just looks like a title with no data, so politeness is the only
  thing between this app and a silent failure.
- Breaker stops calling a provider that has just timed out, so one
  unreachable host does not add its full timeout to every lookup.
- The opener refuses private addresses. Some URLs this server fetches come
  from people (a pasted link) or from third-party pages, so a fetch is a
  request from inside the network. Every connection resolves its host,
  refuses loopback, private, link-local, reserved, multicast and unspecified
  addresses (IPv4-mapped IPv6 included), and then connects to *the address it
  checked* -- so a DNS answer that changes between the check and the connect
  (rebinding) cannot slip through. Redirects are re-checked hop by hop (at
  most MAX_REDIRECTS), and https never downgrades to http. Proxy environment
  variables are ignored, like the healthcheck does.

Nothing here reads the config file directly: configure() is called once at
startup with the providers section.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

MAX_REDIRECTS = 3


class NetworkOff(OSError):
    def __init__(self) -> None:
        super().__init__("outbound lookups are switched off (providers.network)")


class UnsafeAddressError(OSError):
    """A host that resolves somewhere this server must not connect to."""


class Settings:
    enabled = True
    user_agent = "MediaTracker/2.0"
    timeout = 12.0


SETTINGS = Settings()


def configure(enabled: bool, user_agent: str, timeout: float) -> None:
    SETTINGS.enabled = enabled
    SETTINGS.user_agent = user_agent
    SETTINGS.timeout = float(timeout)


# ---------------------------------------------------------------------------
# the private-address refusal
# ---------------------------------------------------------------------------


def unsafe_ip(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or (isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"))
    )


def resolve_public(host: str, port: int) -> tuple[int, str]:
    """(address family, address) of a public address for host, or
    UnsafeAddressError. Every address the name resolves to must be public:
    one private answer among public ones is how rebinding is usually done."""
    if not host or host.lower() in ("localhost", "localhost.localdomain"):
        raise UnsafeAddressError(f"refusing to connect to {host!r}")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise UnsafeAddressError(f"could not resolve {host!r}: {error}") from None
    if not infos:
        raise UnsafeAddressError(f"{host!r} has no address")
    for info in infos:
        if unsafe_ip(info[4][0]):
            raise UnsafeAddressError(f"{host!r} resolves to a private address")
    return infos[0][0], infos[0][4][0]


def _connect(host: str, port: int, timeout: Any, source_address: Any) -> socket.socket:
    family, address = resolve_public(host, port)
    sock = socket.socket(family, socket.SOCK_STREAM)
    if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
        sock.settimeout(timeout)
    if source_address:
        sock.bind(source_address)
    try:
        sock.connect((address, port))
    except OSError:
        sock.close()
        raise
    return sock


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = _connect(self.host, self.port, self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        sock = _connect(self.host, self.port, self.timeout, self.source_address)
        # SNI and certificate checking use the name, not the address.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_PinnedHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self) -> None:
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)  # type: ignore[attr-defined]


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if new.scheme not in ("http", "https") or not new.hostname:
            raise urllib.error.HTTPError(newurl, code, "redirect to a non-web address refused", headers, fp)
        if old.scheme == "https" and new.scheme == "http":
            raise urllib.error.HTTPError(newurl, code, "redirect from https to http refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _SafeHTTPHandler(),
    _SafeHTTPSHandler(),
    _SafeRedirectHandler(),
)


# ---------------------------------------------------------------------------
# politeness
# ---------------------------------------------------------------------------


class HostPace:
    """A minimum gap between calls to the same host, and backoff after a 429."""

    LIMITS = {
        "wikidata.org": 1.1,
        "wikipedia.org": 1.1,
        "wikimedia.org": 1.1,
        "itunes.apple.com": 3.0,
        "api.tvmaze.com": 0.6,
        "openlibrary.org": 1.0,
        "www.omdbapi.com": 0.4,
        "api.themoviedb.org": 0.06,
        "image.tmdb.org": 0.02,
        "upload.wikimedia.org": 0.2,
        # IMDb's suggestion JSON and Amazon's poster images are static files
        # on CDNs; a page of posters at the default gap took a quarter minute.
        "media-imdb.com": 0.05,
        "media-amazon.com": 0.03,
    }

    def __init__(self, default: float = 0.3) -> None:
        self.default = default
        self.next_at: dict[str, float] = {}
        self.penalty: dict[str, float] = {}
        self.lock = threading.Lock()

    def gap(self, host: str) -> float:
        best = None
        for name, seconds in self.LIMITS.items():
            if host == name or host.endswith("." + name):
                if best is None or len(name) > len(best[0]):
                    best = (name, seconds)
        return best[1] if best else self.default

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


class Breaker:
    """Stop calling a provider that just failed twice, for a while."""

    def __init__(self, threshold: int = 2, cooldown: float = 600.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.state: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()

    def is_open(self, name: str) -> bool:
        with self.lock:
            fails, until = self.state.get(name, (0, 0.0))
            return fails >= self.threshold and time.monotonic() < until

    def record(self, name: str, ok: bool) -> None:
        with self.lock:
            if ok:
                self.state.pop(name, None)
                return
            fails = self.state.get(name, (0, 0.0))[0] + 1
            self.state[name] = (fails, time.monotonic() + self.cooldown)


class RateLimiter:
    """What one person may ask of our outbound endpoints per window."""

    def __init__(self, allowance: int, window: float) -> None:
        self.allowance = allowance
        self.window = window
        self.hits: dict[str, deque[float]] = {}
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


PACE = HostPace()
BREAKER = Breaker()


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------


def _request(address: str, headers: dict[str, str] | None = None) -> urllib.request.Request:
    if not SETTINGS.enabled:
        raise NetworkOff()
    parsed = urllib.parse.urlsplit(address)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"not a web address: {address!r}")
    return urllib.request.Request(address, headers={"User-Agent": SETTINGS.user_agent, **(headers or {})})


def _retry_after(error: urllib.error.HTTPError) -> float:
    try:
        return float(error.headers.get("Retry-After") or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_json(address: str, headers: dict[str, str] | None = None, timeout: float | None = None, limit: int = 4_000_000, tries: int = 2) -> Any:
    request = _request(address, {"Accept": "application/json", **(headers or {})})
    host = urllib.parse.urlsplit(address).hostname or ""
    for attempt in range(max(1, tries)):
        PACE.wait(host)
        try:
            with OPENER.open(request, timeout=timeout or SETTINGS.timeout) as response:
                payload = json.loads(response.read(limit).decode("utf-8", "replace"))
            PACE.eased(host)
            return payload
        except urllib.error.HTTPError as error:
            # 502 sits beside the throttles because a shared gateway answers
            # with one now and then and the same call succeeds a moment later.
            if error.code not in (429, 502, 503) or attempt + 1 >= tries:
                raise
            PACE.throttled(host, _retry_after(error))
    return None


def fetch_bytes(address: str, limit: int, accept: str = "*/*", timeout: float | None = None) -> tuple[bytes, str]:
    """(body, content type), refusing anything over limit bytes."""
    request = _request(address, {"Accept": accept})
    host = urllib.parse.urlsplit(address).hostname or ""
    PACE.wait(host)
    with OPENER.open(request, timeout=timeout or SETTINGS.timeout) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError(f"{address} is larger than {limit} bytes")
        PACE.eased(host)
        return body, (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()


def fetch_text(address: str, timeout: float | None = None, limit: int = 600_000) -> str:
    """The head of an HTML page, for reading its metadata tags. Empty on any
    failure: a page that cannot be read is simply a page with no tags."""
    try:
        request = _request(address, {"Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"})
        PACE.wait(urllib.parse.urlsplit(address).hostname or "")
        with OPENER.open(request, timeout=timeout or 8.0) as response:
            kind = (response.headers.get("Content-Type") or "").lower()
            if kind and "html" not in kind and "xml" not in kind:
                return ""
            return response.read(limit).decode("utf-8", "replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError, OSError, NetworkOff, http.client.HTTPException):
        return ""


def fetch_file(address: str, dest: Path, etag: str = "", modified: str = "", limit: int = 64 * 1024 * 1024, timeout: float = 120.0, tries: int = 2) -> dict[str, Any]:
    """Download to a file only if it changed since last time; streamed to
    disk and renamed into place, so a download that dies halfway never leaves
    half a file. {"not_modified": True} when the copy held is current;
    otherwise the validators to send next time."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    request = _request(address, headers)
    host = urllib.parse.urlsplit(address).hostname or ""
    partial = dest.with_name(dest.name + ".part")
    for attempt in range(max(1, tries)):
        PACE.wait(host)
        try:
            with OPENER.open(request, timeout=timeout) as response:
                got = 0
                with open(partial, "wb") as handle:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        got += len(chunk)
                        if got > limit:
                            raise ValueError(f"{address} is larger than {limit} bytes")
                        handle.write(chunk)
                os.replace(partial, dest)
                PACE.eased(host)
                return {"etag": response.headers.get("ETag") or "", "last_modified": response.headers.get("Last-Modified") or ""}
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return {"not_modified": True}
            if error.code not in (429, 502, 503) or attempt + 1 >= tries:
                raise
            PACE.throttled(host, _retry_after(error))
        finally:
            partial.unlink(missing_ok=True)
    return {}
