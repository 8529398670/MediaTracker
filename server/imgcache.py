"""Poster artwork, kept on disk instead of fetched again every time.

Two things were wrong with proxying artwork straight through. Every response
carries `no-store`, so the browser threw each poster away and asked again on
the next render; and each of those asks became a fresh HTTPS call to the
provider. Scrolling a list of nine hundred cards on a small machine therefore
meant a continuous storm of outbound requests, which is what made the list
stutter.

So: the bytes land in the data volume, keyed by the URL asked for, and are
served from there with a long-lived immutable header. The volume outlives the
container, so a rebuild does not throw the artwork away.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

from config import IMG_CACHE_BYTES, IMG_CACHE_DIR, log

_LOCK = threading.Lock()
_BYTES = -1                        # total on disk; -1 until first counted

EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
       "image/gif": ".gif", "image/avif": ".avif", "image/svg+xml": ".svg"}


def key_for(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _paths(key: str) -> list[Path]:
    return [IMG_CACHE_DIR / f"{key}{ext}" for ext in dict.fromkeys(EXT.values())]


def get(key: str) -> tuple[bytes, str] | None:
    """The cached bytes and their content type, or None."""
    for path in _paths(key):
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        ctype = next((c for c, e in EXT.items() if path.name.endswith(e)), "image/jpeg")
        # Touch it so eviction can tell what is still being looked at.
        try:
            os.utime(path, None)
        except OSError:
            pass
        return blob, ctype
    return None


def put(key: str, blob: bytes, ctype: str) -> None:
    ext = EXT.get(ctype)
    if not ext or not blob:
        return
    path = IMG_CACHE_DIR / f"{key}{ext}"
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(blob)
        os.replace(tmp, path)                      # readers never see a part file
    except OSError as exc:
        log(f"img cache: could not write {path.name}: {exc}")
        try:
            tmp.unlink()
        except OSError:
            pass
        return

    global _BYTES
    with _LOCK:
        if _BYTES < 0:
            _BYTES = _measure()
        else:
            _BYTES += len(blob)
        if _BYTES > IMG_CACHE_BYTES:
            _evict()


def _measure() -> int:
    total = 0
    try:
        for entry in os.scandir(IMG_CACHE_DIR):
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        return 0
    return total


def _evict() -> None:
    """Drop the least recently read files until comfortably under budget.

    Called with the lock held. The target is 80% rather than exactly the
    budget so that a full cache does not evict on every single write.
    """
    global _BYTES
    try:
        files = [(e.stat().st_atime, e.stat().st_size, e.path)
                 for e in os.scandir(IMG_CACHE_DIR) if e.is_file()]
    except OSError:
        return
    files.sort()                                   # oldest read first
    target = int(IMG_CACHE_BYTES * 0.8)
    total = sum(size for _, size, _ in files)
    dropped = 0
    for _, size, path in files:
        if total <= target:
            break
        try:
            os.unlink(path)
        except OSError:
            continue
        total -= size
        dropped += 1
    _BYTES = total
    if dropped:
        log(f"img cache: evicted {dropped} files, now {total // 1024}kB")


def stats() -> dict:
    try:
        files = [e for e in os.scandir(IMG_CACHE_DIR) if e.is_file()]
    except OSError:
        return {"files": 0, "bytes": 0}
    return {"files": len(files), "bytes": sum(e.stat().st_size for e in files)}
