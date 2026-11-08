"""Starting uvicorn and stopping it in the right order.

uvicorn.run has no hook between "a stop was asked for" and "wait for every
connection to finish". The lifespan's shutdown runs after that wait, so
anything that never finishes by itself -- an open live stream, above all --
would cost the whole graceful timeout on every stop. Server.shutdown is that
moment: on_stop runs first, ends the streams, and the wait finds nothing to
wait for.

run() is uvicorn.run for this one case: the same KeyboardInterrupt catch and
the same exit status when the server never got as far as listening.
"""
from __future__ import annotations

import socket
import sys
from typing import Any, Callable, TypeVar

import uvicorn
from anyio import to_thread
from uvicorn.main import STARTUP_FAILURE

T = TypeVar("T")


class Server(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, on_stop: Callable[[], None]) -> None:
        super().__init__(config)
        self.on_stop = on_stop

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            self.on_stop()
        finally:
            await super().shutdown(sockets)


def run(app: Any, on_stop: Callable[[], None], **options: Any) -> None:
    """Serve app until a signal stops it. on_stop runs on the event loop, once,
    before connections are waited for, so it must not block. options are
    uvicorn.Config's."""
    server = Server(uvicorn.Config(app, **options), on_stop)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        sys.exit(STARTUP_FAILURE)


async def run_abandonable(fn: Callable[..., T], *args: Any) -> T:
    """helpers.run for work that must not hold up the exit. A plain
    run_in_threadpool cannot be cancelled until its thread returns, and
    asyncio.run cancels and then waits for every task left when the server
    stops, so a backup still writing would keep the process alive however
    bounded everything before it was. Cancelling this one returns at once and
    leaves the thread to die with the process: worker threads are daemons."""
    return await to_thread.run_sync(fn, *args, abandon_on_cancel=True)
