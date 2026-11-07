"""Posters, fetched once and kept on disk.

A library page shows hundreds of posters, and every one used to be a fresh
call to a provider. So the bytes land in <storage>/cache/img/, keyed by
sha256 of the provider's URL (the same key the old app used, so its cache
carries over), and are served from there with a year-long cache header.

The page never names a URL to fetch. It asks for /api/img/<key>, and the
server only fetches a URL it registered itself -- a title's poster or a
Discover thumbnail -- whose host is on images.allow_hosts. The old
/api/img?u=<any url> was an open proxy; this is not.

The cache has a size budget (images.cache_mb); when it is exceeded the least
recently read files go until it is at 80%.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Callable

EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}
KEY = re.compile(r"^[0-9a-f]{32}$")
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# A poster is drawn a few hundred pixels wide at most, and providers hand
# back far larger ones. Only rewrites that are certain are made; a rewrite
# that fails falls back to the original URL.
SMALLER = (
    ("https://image.tmdb.org/t/p/w500/", "https://image.tmdb.org/t/p/w342/"),
    ("https://image.tmdb.org/t/p/original/", "https://image.tmdb.org/t/p/w342/"),
    ("-L.jpg", "-M.jpg"),
    ("/original_", "/medium_portrait_"),
)
WIDTH = 330  # one of Wikimedia's standard thumbnail steps; others are refused


def key_for(address: str) -> str:
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:32]


def smaller(address: str) -> str:
    for big, small in SMALLER:
        if big in address:
            return address.replace(big, small, 1)
    match = re.search(r"/thumb/.*/(\d+)px-", address)
    if match and int(match.group(1)) > WIDTH:
        return address[: match.start(1)] + str(WIDTH) + address[match.end(1) :]
    return address


class ImageCache:
    def __init__(self) -> None:
        self.folder: Path | None = None
        self.budget = 256 * 1024 * 1024
        self.allow_hosts: tuple[str, ...] = ()
        self.known: dict[str, str] = {}
        self.lock = threading.Lock()
        self.size = -1

    def configure(self, folder: Path, cache_mb: int, allow_hosts: list[str]) -> None:
        self.folder = folder
        self.budget = cache_mb * 1024 * 1024
        self.allow_hosts = tuple(host.lower() for host in allow_hosts)

    # -- the registry ------------------------------------------------------

    def allowed(self, address: str) -> bool:
        parsed = urllib.parse.urlsplit(address)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            return False
        return any(fnmatch.fnmatchcase(host, pattern) or (pattern.startswith("*.") and host == pattern[2:]) for pattern in self.allow_hosts)

    def path_for(self, address: str) -> str:
        """The same-origin path a page uses for this image, registering it so
        a cache miss can fetch it. Empty for a URL the server will not fetch
        and has no copy of."""
        if not address:
            return ""
        key = key_for(address)
        if key not in self.known:
            if not self.allowed(address) and self.cached(key) is None:
                return ""
            self.known[key] = address
        return f"/api/img/{key}"

    # -- the disk ------------------------------------------------------------

    def cached(self, key: str) -> Path | None:
        if self.folder is None or not KEY.match(key):
            return None
        for ext in EXT.values():
            path = self.folder / f"{key}{ext}"
            if path.is_file():
                return path
        return None

    def read(self, key: str) -> tuple[bytes, str] | None:
        path = self.cached(key)
        if path is None:
            return None
        try:
            data = path.read_bytes()
            os.utime(path)  # "recently read", for eviction
        except OSError:
            return None
        kind = next((kind for kind, ext in EXT.items() if path.name.endswith(ext)), "image/jpeg")
        return data, kind

    def write(self, key: str, data: bytes, kind: str) -> None:
        ext = EXT.get(kind)
        if self.folder is None or not ext or not data:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{key}{ext}"
        partial = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        try:
            partial.write_bytes(data)
            os.replace(partial, path)
        except OSError:
            partial.unlink(missing_ok=True)
            return
        with self.lock:
            self.size = self._measure() if self.size < 0 else self.size + len(data)
            if self.size > self.budget:
                self._evict()

    def _measure(self) -> int:
        assert self.folder is not None
        try:
            return sum(entry.stat().st_size for entry in os.scandir(self.folder) if entry.is_file())
        except OSError:
            return 0

    def _evict(self) -> None:
        assert self.folder is not None
        try:
            files = sorted((entry.stat().st_mtime, entry.stat().st_size, entry.path) for entry in os.scandir(self.folder) if entry.is_file())
        except OSError:
            return
        target = int(self.budget * 0.8)
        total = sum(size for _when, size, _path in files)
        for _when, size, path in files:
            if total <= target:
                break
            try:
                os.unlink(path)
                total -= size
            except OSError:
                continue
        self.size = total

    def stats(self) -> dict[str, int]:
        if self.folder is None:
            return {"files": 0, "bytes": 0, "budget": self.budget}
        files = [entry for entry in os.scandir(self.folder) if entry.is_file()]
        return {"files": len(files), "bytes": sum(entry.stat().st_size for entry in files), "budget": self.budget}

    # -- fetching ------------------------------------------------------------

    def fetch(self, key: str, fetch_bytes: Callable[..., tuple[bytes, str]]) -> tuple[bytes, str] | None:
        """The image for a registered key: from disk, or fetched once and kept.
        fetch_bytes is providers.net.fetch_bytes, passed in so this module has
        no network import."""
        hit = self.read(key)
        if hit is not None:
            return hit
        address = self.known.get(key)
        if not address or not self.allowed(address):
            return None
        for candidate in dict.fromkeys((smaller(address), address)):
            try:
                data, kind = fetch_bytes(candidate, MAX_IMAGE_BYTES, accept="image/*")
            except Exception:  # noqa: BLE001 -- any failure is "no image", and the original is tried next
                continue
            if kind in EXT:
                self.write(key, data, kind)
                return data, kind
        return None


CACHE = ImageCache()
