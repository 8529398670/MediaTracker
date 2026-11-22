"""Tells an open page that the frontend it is running has changed, so a save
in an editor (or a new build) shows up without anyone pressing refresh.

server.live_reload decides whether serve() creates it: auto does for an
unstamped build ("dev"), always and never decide it for every build. Without
it there is no route, and static/js/live.js stops at the 404. Go's twin is
server/livereload.

The page asks GET /api/live?boot=..&since=.. and the request is held until
something changes or HOLD_SECONDS pass (long-poll, so no streaming machinery
is needed). The reply says what changed: a stylesheet alone is swapped in
place by static/js/live.js, anything else needs a reload, which live.js does
at once on a dev build and at the next screen change on a stamped one (see
static/js/fresh.js). boot changes with every start of the process, which is
how a page notices a restart onto new Python code.

Changes are found by comparing modification times and sizes every
POLL_SECONDS, standard library only. A static tree is a few hundred files;
walking it is cheaper than a file-watching dependency.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

POLL_SECONDS = 0.3
HOLD_SECONDS = 25.0


def _scan(root: Path) -> dict[str, tuple[int, int]]:
    files: dict[str, tuple[int, int]] = {}
    for directory, folders, names in os.walk(root):
        folders[:] = [name for name in folders if not name.startswith(".")]
        for name in names:
            if name.startswith("."):  # editor swap files
                continue
            path = Path(directory) / name
            try:
                info = path.stat()
            except OSError:
                continue
            files[path.relative_to(root).as_posix()] = (info.st_mtime_ns, info.st_size)
    return files


class Watcher:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.boot = format(time.time_ns(), "x")
        self.files = _scan(root)
        self.stamp = 0
        # What the latest stamp changed, relative to root.
        self.changed: list[str] = []
        self.wake = asyncio.Event()
        self.closed = False
        self._polling: asyncio.Task | None = None

    def close(self) -> None:
        """Answer every held request, so a shutdown does not wait out
        HOLD_SECONDS."""
        self.closed = True
        self.wake.set()
        if self._polling is not None:
            self._polling.cancel()

    async def _poll(self) -> None:
        while not self.closed:
            await asyncio.sleep(POLL_SECONDS)
            files = await run_in_threadpool(_scan, self.root)
            changed = [name for name, state in files.items() if self.files.get(name) != state]
            changed += [name for name in self.files if name not in files]
            if not changed:
                continue
            self.files = files
            self.stamp += 1
            self.changed = changed
            self.wake.set()
            self.wake = asyncio.Event()

    def _reply(self, since: int) -> dict:
        # changed is None when the page missed more than one change (or is
        # new), which means "reload".
        changed = self.changed if 0 <= since == self.stamp - 1 else None
        return {"boot": self.boot, "stamp": self.stamp, "changed": changed}

    async def endpoint(self, request: Request) -> JSONResponse:
        """GET /api/live. A page from another process (boot differs) or
        one behind on changes is answered at once; one that is up to date
        waits."""
        # Started on the first request, inside the running event loop.
        if self._polling is None and not self.closed:
            self._polling = asyncio.create_task(self._poll())
        try:
            since = int(request.query_params.get("since", "-1"))
        except ValueError:
            since = -1
        if request.query_params.get("boot") == self.boot and since == self.stamp and not self.closed:
            try:
                await asyncio.wait_for(self.wake.wait(), HOLD_SECONDS)
            except asyncio.TimeoutError:
                pass
        return JSONResponse(self._reply(since), headers={"cache-control": "no-store"})
