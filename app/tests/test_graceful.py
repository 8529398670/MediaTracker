"""Starting and stopping (app/core/graceful.py): on_stop comes before the wait
for connections, the failure modes of uvicorn.run are kept, and abandonable
work really does let go."""
from __future__ import annotations

import asyncio
import threading
import time
import unittest
from unittest import mock

import uvicorn

from app.core import graceful


async def app(scope: dict, receive: object, send: object) -> None:
    raise AssertionError("never called")


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_on_stop_runs_before_connections_are_waited_for(self) -> None:
        order: list[str] = []

        async def uvicorn_shutdown(server: uvicorn.Server, sockets: object = None) -> None:
            order.append("uvicorn")

        with mock.patch.object(uvicorn.Server, "shutdown", uvicorn_shutdown):
            await graceful.Server(uvicorn.Config(app), lambda: order.append("on_stop")).shutdown()
        self.assertEqual(order, ["on_stop", "uvicorn"])

    async def test_a_failing_on_stop_does_not_stop_the_shutdown(self) -> None:
        called = []

        async def uvicorn_shutdown(server: uvicorn.Server, sockets: object = None) -> None:
            called.append(True)

        def on_stop() -> None:
            raise ValueError("no")

        with mock.patch.object(uvicorn.Server, "shutdown", uvicorn_shutdown):
            with self.assertRaises(ValueError):
                await graceful.Server(uvicorn.Config(app), on_stop).shutdown()
        self.assertEqual(called, [True])


class RunTest(unittest.TestCase):
    def test_exits_with_the_startup_failure_status_when_it_never_started(self) -> None:
        with mock.patch.object(graceful.Server, "run", lambda server: None):
            with self.assertRaises(SystemExit) as caught:
                graceful.run(app, lambda: None)
        self.assertEqual(caught.exception.code, graceful.STARTUP_FAILURE)

    def test_a_keyboard_interrupt_is_a_clean_stop(self) -> None:
        def interrupted(server: graceful.Server) -> None:
            server.started = True
            raise KeyboardInterrupt

        with mock.patch.object(graceful.Server, "run", interrupted):
            graceful.run(app, lambda: None)


class AbandonableTest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_result(self) -> None:
        self.assertEqual(await graceful.run_abandonable(lambda a, b: a + b, 2, 3), 5)

    async def test_cancelling_does_not_wait_for_the_thread(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        task = asyncio.create_task(graceful.run_abandonable(release.wait))
        await asyncio.sleep(0.05)
        started = time.monotonic()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertLess(time.monotonic() - started, 1)


if __name__ == "__main__":
    unittest.main()
