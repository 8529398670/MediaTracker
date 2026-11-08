"""Proof that a server is running on this app directory.

bolt gives the Go template this for free, by handing its file to one process.
SQLite is happy to share, which is what lets `manage` work beside a live
server, but a few things must not happen under one: a restore swaps the
database file out, and a server that kept it open would carry on writing to
the old one.

So the server holds an operating-system lock on a file in the app directory
for as long as it runs. The kernel drops the lock when the process ends, however
it ends, so a crash leaves nothing to clean up and the file's existence means
nothing -- only whether it can be locked.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt


def _try_lock(descriptor: int) -> bool:
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


class ServerLock:
    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def release(self) -> None:
        os.close(self._descriptor)


def acquire(path: Path, timeout_seconds: float = 0) -> ServerLock | None:
    """Take the lock, waiting up to timeout_seconds, or None if something else
    holds it. A restart needs the wait: the old process can take a moment to
    finish going down."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout_seconds
    while not _try_lock(descriptor):
        if time.monotonic() >= deadline:
            os.close(descriptor)
            return None
        time.sleep(0.1)
    return ServerLock(descriptor)


def held(path: Path) -> bool:
    """Whether a server is running right now."""
    lock = acquire(path)
    if lock is None:
        return True
    lock.release()
    return False
