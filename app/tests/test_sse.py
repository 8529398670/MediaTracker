"""Live updates (app/core/sse.py). Through the whole app with a raw ASGI call,
because TestClient waits for a response to end and these do not. Each test
ends with the slot it took given back, which is the thing most worth proving."""
from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app.core import encryption, logs, security, sse
from app.core.config import LogsConfig
from app.models import login_tokens, sessions, to_iso, users, utc_now
from app.models.sign_in import SignInRules
from app.tests.route_support import RoutesTestCase, asgi_request

PATH = "/api/owner/logs/stream"
OPENING = b"retry: 5000\n\nevent: changed\ndata: 1\n\n"


class FormatTest(unittest.TestCase):
    def test_an_event(self) -> None:
        self.assertEqual(sse.event("changed", "1"), b"event: changed\ndata: 1\n\n")
        self.assertEqual(sse.CHANGED, b"event: changed\ndata: 1\n\n")
        self.assertEqual(sse.retry(5000), b"retry: 5000\n\n")
        self.assertEqual(sse.PING, b": ping\n\n")

    def test_data_cannot_forge_a_field(self) -> None:
        for attack in ("a\nevent: admin\ndata: b", "a\revent: admin", "a\r\nevent: admin"):
            encoded = sse.event("changed", attack)
            lines = encoded.decode().rstrip("\n").split("\n")
            self.assertEqual(lines[0], "event: changed")
            for line in lines[1:]:
                self.assertTrue(line.startswith("data: "), line)
            self.assertFalse(any("\r" in line for line in lines))

    def test_a_name_cannot_either(self) -> None:
        self.assertEqual(sse.event("a\ndata: forged", "1"), b"event: adata: forged\ndata: 1\n\n")


class HubTest(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_drops_and_never_blocks(self) -> None:
        hub = sse.Hub()
        client = hub.join()
        started = time.monotonic()
        for index in range(sse.CLIENT_QUEUE_SIZE * 4):
            hub.publish(str(index).encode())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(client.queue.qsize(), sse.CLIENT_QUEUE_SIZE)
        self.assertEqual(client.queue.get_nowait(), b"0")

    async def test_the_cap(self) -> None:
        hub = sse.Hub(max_clients=2)
        first = hub.join()
        self.assertIsNotNone(hub.join())
        self.assertIsNone(hub.join())
        hub.leave(first)
        self.assertIsNotNone(hub.join())

    async def test_closing_reaches_a_client_with_a_full_queue(self) -> None:
        hub = sse.Hub()
        client = hub.join()
        for _ in range(sse.CLIENT_QUEUE_SIZE):
            hub.publish(b"x")
        hub.close()
        self.assertIsNone(client.queue.get_nowait())
        self.assertIsNone(hub.join())

    async def test_publishing_from_another_thread(self) -> None:
        hub = sse.Hub()
        client = hub.join()
        loop = asyncio.get_running_loop()
        await asyncio.to_thread(sse.publish_from_thread, loop, hub, b"x")
        self.assertEqual(await asyncio.wait_for(client.queue.get(), 2), b"x")

    def test_publishing_to_a_closed_loop_is_harmless(self) -> None:
        loop = asyncio.new_event_loop()
        loop.close()
        sse.publish_from_thread(loop, sse.Hub(), b"x")


class NudgeTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.logger = logs.Logger(LogsConfig(dir=Path(directory.name)), "ab" * 32, False)
        self.addCleanup(self.logger.close)
        self.nudges: list[float] = []
        self.logger.on_flushed = lambda: self.nudges.append(time.perf_counter())

    def record(self) -> dict:
        return logs.entry(logs.KIND_SYSTEM, msg="x")

    def test_nothing_new_means_no_nudge(self) -> None:
        self.logger._nudge()
        self.assertEqual(self.nudges, [])

    def test_gated_then_owed(self) -> None:
        clock = iter([10.0, 10.5, 11.1])
        with mock.patch.object(logs.time, "monotonic", lambda: next(clock)):
            self.logger._write(self.record())
            self.logger._nudge()
            self.assertEqual(len(self.nudges), 1)
            self.logger._write(self.record())
            self.logger._nudge()
            self.assertEqual(len(self.nudges), 1, "half a second later: too soon")
            self.logger._nudge()
            self.assertEqual(len(self.nudges), 2, "owed from the entry above")

    def test_a_failing_callback_does_not_stop_the_writer(self) -> None:
        def broken() -> None:
            raise RuntimeError("listener gone")

        self.logger.on_flushed = broken
        self.logger._write(self.record())
        self.logger._nudge()

    def test_the_writer_thread_calls_it_about_once_a_second(self) -> None:
        self.logger.start()
        for _ in range(30):
            self.logger.log(self.record())
            time.sleep(0.005)
        deadline = time.monotonic() + 3
        while len(self.nudges) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.nudges), 2, "the first entry, then the rest once")
        self.assertGreaterEqual(self.nudges[1] - self.nudges[0], logs.NUDGE_INTERVAL - 0.01)


class StillOwnerTest(RoutesTestCase):
    def credential(self, user_id: int) -> str:
        login = login_tokens.issue_login_token(self.store, user_id, 3600)
        return login_tokens.redeem_login_token(self.store, login, SignInRules(3600)).session_credential

    def test_the_owner(self) -> None:
        self.assertTrue(security.still_owner(self.store, self.credential(self.owner.id)))

    def test_another_admin(self) -> None:
        self.assertFalse(security.still_owner(self.store, self.credential(self.admin.id)))

    def test_a_session_that_ended(self) -> None:
        credential = self.credential(self.owner.id)
        sessions.destroy_session(self.store, credential)
        self.assertFalse(security.still_owner(self.store, credential))

    def test_an_owner_who_handed_over(self) -> None:
        credential = self.credential(self.owner.id)
        self.store.put("meta", users.META_OWNER_KEY, {"user_id": self.admin.id})
        self.assertFalse(security.still_owner(self.store, credential))

    def test_it_does_not_count_as_activity(self) -> None:
        credential = self.credential(self.owner.id)
        security.still_owner(self.store, credential)
        self.assertNotIn("last_seen_at", self.store.get("sessions", credential.partition(".")[0]))


class StreamTest(RoutesTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.hub: sse.Hub = self.app.state.log_hub

    def owner_session(self) -> tuple[str, str]:
        login = login_tokens.issue_login_token(self.store, self.owner.id, 3600)
        credential = login_tokens.redeem_login_token(self.store, login, SignInRules(3600)).session_credential
        return credential, f"{self.cfg.cookie_name}={encryption.xchacha_encrypt_string(self.cfg.secret_key, credential)}"

    async def open(self, cookie: str | None = None):
        exchange, task = asgi_request(self.app, PATH, cookie or self.owner_cookie)
        self.addAsyncCleanup(self.finish, exchange, task)
        await exchange.wait_for_body(OPENING)
        return exchange, task

    @staticmethod
    async def finish(exchange, task) -> None:
        exchange.disconnected.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)

    async def test_the_stream_as_the_contract_says(self) -> None:
        exchange, task = await self.open()
        self.assertEqual(exchange.status, 200)
        headers = exchange.headers
        self.assertEqual(headers["content-type"], "text/event-stream")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-accel-buffering"], "no")
        self.assertRegex(headers["x-request-id"], r"^[0-9a-f]{16}$")
        self.assertTrue(exchange.body.startswith(OPENING))

        self.hub.publish(sse.CHANGED)
        await exchange.wait_for_body(OPENING + sse.CHANGED)

    async def test_only_the_owner(self) -> None:
        for cookie in ("", self.admin_cookie, self.user_cookie):
            exchange, task = asgi_request(self.app, PATH, cookie)
            await asyncio.wait_for(task, 5)
            self.assertEqual(exchange.status, 404)
        self.assertEqual(self.hub.clients, set())

    async def test_over_the_cap(self) -> None:
        for _ in range(sse.MAX_CLIENTS):
            await self.open()
        exchange, task = asgi_request(self.app, PATH, self.owner_cookie)
        await asyncio.wait_for(task, 5)
        self.assertEqual(exchange.status, 503)
        self.assertEqual(exchange.body, b'{"error":"too many live streams"}')

    async def test_head_answers_without_streaming(self) -> None:
        exchange, task = asgi_request(self.app, PATH, self.owner_cookie, method="HEAD")
        await asyncio.wait_for(task, 5)
        self.assertEqual(exchange.status, 200)
        self.assertEqual(exchange.headers["content-type"], "text/event-stream")
        self.assertEqual(exchange.body, b"")
        self.assertEqual(self.hub.clients, set())

    async def test_a_disconnect_frees_the_slot(self) -> None:
        exchange, task = await self.open()
        self.assertEqual(len(self.hub.clients), 1)
        exchange.disconnected.set()
        await asyncio.wait_for(task, 5)
        self.assertEqual(self.hub.clients, set())

    async def test_a_cancelled_stream_frees_the_slot(self) -> None:
        exchange, task = await self.open()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.hub.clients, set())

    async def test_a_client_that_stops_reading_is_dropped(self) -> None:
        self.hub.send_timeout_seconds = 0.05
        stuck = asyncio.Event()
        exchange_send = []

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                exchange_send.append(message)
                return
            stuck.set()
            await asyncio.Event().wait()

        exchange, task = asgi_request(self.app, PATH, self.owner_cookie, send=send)
        await asyncio.wait_for(task, 5)
        self.assertTrue(stuck.is_set())
        self.assertEqual(self.hub.clients, set())

    async def test_closing_the_hub_ends_the_stream(self) -> None:
        exchange, task = await self.open()
        self.hub.close()
        await asyncio.wait_for(task, 5)
        self.assertFalse(exchange.messages[-1].get("more_body", True))
        self.assertEqual(self.hub.clients, set())

        refused, task = asgi_request(self.app, PATH, self.owner_cookie)
        await asyncio.wait_for(task, 5)
        self.assertEqual(refused.status, 503)

    async def test_a_tick_is_a_ping(self) -> None:
        self.hub.tick_seconds = 0.02
        exchange, task = await self.open()
        await exchange.wait_for_body(sse.PING)

    async def test_a_busy_stream_is_still_rechecked(self) -> None:
        self.hub.tick_seconds = 0.02
        exchange, task = await self.open()
        stop = asyncio.Event()

        async def flood() -> None:
            while not stop.is_set():
                self.hub.publish(sse.CHANGED)
                await asyncio.sleep(0.001)

        flooding = asyncio.create_task(flood())
        try:
            await exchange.wait_for_body(sse.PING)
        finally:
            stop.set()
            await flooding

    async def test_a_revoked_session_ends_the_stream(self) -> None:
        self.hub.tick_seconds = 0.02
        credential, cookie = self.owner_session()
        exchange, task = await self.open(cookie)
        sessions.destroy_session(self.store, credential)
        await asyncio.wait_for(task, 5)
        self.assertEqual(self.hub.clients, set())

    async def test_a_disabled_owner_ends_the_stream(self) -> None:
        self.hub.tick_seconds = 0.02
        exchange, task = await self.open()
        self.store.update_value("users", self.owner.id, lambda record: record.update(disabled_at=to_iso(utc_now())))
        await asyncio.wait_for(task, 5)
        self.assertEqual(self.hub.clients, set())

    async def test_unable_to_check_means_no(self) -> None:
        self.hub.tick_seconds = 0.02
        exchange, task = await self.open()
        with mock.patch.object(self.store, "get", side_effect=RuntimeError("locked")):
            await asyncio.wait_for(task, 5)
        self.assertEqual(self.hub.clients, set())

    async def test_the_stream_is_not_in_the_activity_log(self) -> None:
        """Nothing is writing here (no lifespan), so anything logged is still
        in the queue. A stream that logged itself would nudge itself."""
        exchange, task = await self.open()
        self.hub.close()
        await asyncio.wait_for(task, 5)
        self.assertTrue(self.app.state.logs._queue.empty())


if __name__ == "__main__":
    unittest.main()
