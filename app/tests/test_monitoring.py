"""Request IDs, /api/ready and /metrics. What matters most: the reference a
person is shown finds a log line that says what happened, with the log on or
off the ID and the counters still work, and /metrics refuses everyone but an
admin key."""
from __future__ import annotations

import asyncio
import contextlib
import io
import re
import threading
import time
import unittest
from unittest import mock

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core import db
from app.core import logs
from app.models import users
from app.routes import meta
from app.routes.logs import audit
from app.tests.route_support import RoutesTestCase, TestClient

REFERENCE = re.compile(r"^[0-9a-f]{16}$")


async def crash(request: Request) -> PlainTextResponse:
    raise ValueError("the real reason")


async def audited(request: Request) -> PlainTextResponse:
    audit(request, logs.KIND_ADMIN, "did a thing")
    return PlainTextResponse("ok")


class MonitoringTestCase(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app.router.routes.insert(0, Route("/api/crash", crash))
        self.app.router.routes.insert(0, Route("/api/audited", audited))

class RequestIDTest(MonitoringTestCase):
    def test_every_answer_has_one_and_no_two_match(self) -> None:
        seen = set()
        for path, cookie in (("/api/health", ""), ("/api/nope", ""), ("/", ""), ("/api/me", ""), ("/api/me", self.owner_cookie)):
            value = self.request("GET", path, cookie=cookie).headers["x-request-id"]
            self.assertRegex(value, REFERENCE)
            seen.add(value)
        self.assertEqual(len(seen), 5)

    def test_what_the_caller_sends_is_ignored(self) -> None:
        response = self.client.get("/api/health", headers={"X-Request-ID": "forged"})
        self.assertEqual(len(response.headers.get_list("x-request-id")), 1)
        self.assertRegex(response.headers["x-request-id"], REFERENCE)

    def test_a_refused_flood_has_one(self) -> None:
        self.set_config(rate_limit_max=1)
        self.client.get("/api/me")
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 429)
        self.assertRegex(response.headers["x-request-id"], REFERENCE)

    def test_a_crash_has_one_in_the_header_and_the_body(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            response = self.client.get("/api/crash")
        self.assertEqual(response.status_code, 500)
        reference = response.headers["x-request-id"]
        self.assertRegex(reference, REFERENCE)
        self.assertEqual(response.json(), {"error": "internal error", "request_id": reference})
        self.assertNotIn("the real reason", response.text)
        self.assertIn(f"[error] {reference} GET /api/crash: ValueError('the real reason')", stderr.getvalue())

    def test_a_handled_500_has_one_too(self) -> None:
        token = self.csrf(self.owner_cookie)
        with mock.patch.object(users, "rename_user", return_value=False), contextlib.redirect_stderr(io.StringIO()) as stderr:
            response = self.request(
                "POST", "/api/account/rename", cookie=self.owner_cookie, body={"display_name": "New", "csrf_token": token}
            )
        self.assertEqual(response.status_code, 500)
        reference = response.headers["x-request-id"]
        self.assertEqual(response.json(), {"error": "internal error", "request_id": reference})
        self.assertIn(f"[error] {reference} POST /api/account/rename: rename", stderr.getvalue())

    def test_a_body_over_the_limit_has_one(self) -> None:
        """Starlette's own max_body_size= sits outside every middleware here,
        which is why main.build_app does not use it."""
        big = b"x" * (self.cfg.body_limit_bytes + 1)
        with TestClient(self.app) as client:
            response = client.post("/api/logout", content=big, headers={"content-type": "application/json", "cookie": self.owner_cookie})
            self.assertEqual(response.status_code, 413)
            self.assertRegex(response.headers["x-request-id"], REFERENCE)
            self.assertEqual(response.headers["x-frame-options"], "DENY")
        logger = self.app.state.logs
        entries, _ = logger.read_day(logger.today(), logs.Query(response.headers["x-request-id"]))
        self.assertEqual([(entry["kind"], entry["request"]["status"]) for entry in entries], [(logs.KIND_REQUEST, 413)])

    def test_a_credential_in_the_path_stays_out_of_stdout(self) -> None:
        self.app.router.routes.insert(0, Route("/login/{credential:path}", crash))
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.client.get("/login/abc.s3cret")
        self.assertNotIn("s3cret", stderr.getvalue())


class FindingTheLineTest(MonitoringTestCase):
    def line_for(self, reference: str) -> dict:
        logger = self.app.state.logs
        entries, _ = logger.read_day(logger.today(), logs.Query(reference))
        self.assertEqual(len(entries), 1, entries)
        return entries[0]

    def test_a_crash(self) -> None:
        with TestClient(self.app, raise_server_exceptions=False) as client, contextlib.redirect_stderr(io.StringIO()):
            reference = client.get("/api/crash").headers["x-request-id"]
        line = self.line_for(reference)
        self.assertEqual(line["request_id"], reference)
        self.assertEqual(line["kind"], logs.KIND_ERROR)
        self.assertEqual(line["request"]["status"], 500)
        self.assertIn("the real reason", line["msg"])

    def test_a_handled_500_says_why_as_well(self) -> None:
        token = self.csrf(self.owner_cookie)
        with TestClient(self.app) as client, contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(users, "rename_user", return_value=False):
                reference = self.request(
                    "POST", "/api/account/rename", cookie=self.owner_cookie, body={"display_name": "New", "csrf_token": token}, client=client
                ).headers["x-request-id"]
        line = self.line_for(reference)
        self.assertEqual(line["kind"], logs.KIND_ERROR)
        self.assertIn("rename", line["msg"])

    def test_an_audit_line_carries_it(self) -> None:
        with TestClient(self.app) as client:
            reference = self.request("GET", "/api/audited", cookie=self.owner_cookie, client=client).headers["x-request-id"]
        logger = self.app.state.logs
        entries, _ = logger.read_day(logger.today(), logs.Query(reference))
        self.assertEqual({entry["kind"] for entry in entries}, {logs.KIND_ADMIN, logs.KIND_REQUEST})

    def test_an_ordinary_request_has_no_empty_field(self) -> None:
        with TestClient(self.app) as client:
            reference = client.get("/api/health/nope").headers["x-request-id"]
        self.assertNotIn("msg", self.line_for(reference))

class LogsOffTest(MonitoringTestCase):
    logs_enabled = False

    def test_ids_and_metrics_do_not_need_the_log(self) -> None:
        self.assertFalse(self.app.state.logs.enabled)
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            crashed = self.client.get("/api/crash")
        reference = crashed.headers["x-request-id"]
        self.assertRegex(reference, REFERENCE)
        self.assertEqual(crashed.json()["request_id"], reference)
        self.assertIn(reference, stderr.getvalue())
        self.assertRegex(self.client.get("/api/health").headers["x-request-id"], REFERENCE)

    def test_the_live_tail_is_gone_with_the_log(self) -> None:
        self.assertEqual(self.call("GET", "/api/owner/logs/stream", cookie=self.owner_cookie)[0], 404)


class ReadyTest(MonitoringTestCase):
    def test_ready_says_nothing_more(self) -> None:
        response = self.client.get("/api/ready")
        self.assertEqual((response.status_code, response.json()), (200, {"ok": True}))

    def test_public(self) -> None:
        self.assertEqual(self.call("GET", "/api/ready")[0], 200)

    def test_a_schema_mismatch_is_not_ready(self) -> None:
        with mock.patch.object(db, "latest_schema_version", return_value=99):
            response = self.client.get("/api/ready")
        self.assertEqual((response.status_code, response.json()), (503, {"ok": False}))

    def test_no_owner_is_not_ready(self) -> None:
        self.store.delete(db.BUCKET_META, users.META_OWNER_KEY)
        self.assertEqual(self.client.get("/api/ready").status_code, 503)

    def test_a_key_that_does_not_read_the_database_is_not_ready(self) -> None:
        other = db.Store(self.store.path, "ab" * 32, True)
        self.app.state.store = other
        response = self.client.get("/api/ready")
        self.assertEqual((response.status_code, response.json()), (503, {"ok": False}))

    def test_the_health_check_does_not_care(self) -> None:
        with mock.patch.object(db, "latest_schema_version", return_value=99):
            self.assertEqual(self.client.get("/api/health").status_code, 200)


class SlowReadyTest(unittest.IsolatedAsyncioTestCase):
    """The handler itself, on one event loop."""

    class Fixture:
        def __init__(self) -> None:
            self.state = type("State", (), {"store": object()})()

    def request(self, state: object) -> Request:
        app = type("App", (), {"state": state})()
        return Request({"type": "http", "app": app, "headers": []})

    async def test_times_out_without_stacking_threads(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []

        def slow(store: object) -> bool:
            calls.append(1)
            release.wait(5)
            return True

        state = self.Fixture().state
        with mock.patch.object(meta, "ready_now", slow), mock.patch.object(meta, "READY_TIMEOUT_SECONDS", 0.05):
            started = time.monotonic()
            answers = await asyncio.gather(meta.get_ready(self.request(state)), meta.get_ready(self.request(state)))
            late = await meta.get_ready(self.request(state))
            elapsed = time.monotonic() - started
            self.assertEqual([answer.status_code for answer in (*answers, late)], [503, 503, 503])
            self.assertEqual(len(calls), 1)
            self.assertLess(elapsed, 2)

            # Once the slow one finishes, the next probe starts afresh.
            release.set()
            await state.ready_probe
            self.assertEqual((await meta.get_ready(self.request(state))).status_code, 200)
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
