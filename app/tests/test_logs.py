"""The activity log (app/core/logs.py). What these pin down: nothing secret
reaches a line, an encrypted line reads back, a day rotates into parts and
pages back newest first across them, retention and recycling delete the right
days and never today, a gzipped day still reads, and the search grammar means
what the Logs screen says."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core import encryption, logs
from app.core.config import LogsConfig


def request(path: str, status: int, **extra: object) -> dict:
    return logs.entry(logs.KIND_REQUEST, request={"method": "GET", "path": path, "status": status}, **extra)


class LogsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.settings = LogsConfig(dir=Path(self.directory.name), retention_days=30, compress_after_days=1)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def logger(self, encrypt: bool = False, **changes: object) -> logs.Logger:
        logger = logs.Logger(replace(self.settings, **changes), encryption.generate_key_hex(), encrypt)
        self.addCleanup(logger.close)
        return logger

    @staticmethod
    def write_now(logger: logs.Logger, *records: dict) -> None:
        """Straight through the writer, skipping the queue, so a test can read
        what it wrote at once."""
        for record in records:
            logger._write(record)
        logger.flush()


class RedactTest(LogsTestCase):
    def test_credentials_never_survive(self) -> None:
        self.assertEqual(logs.redact("/login/abc.def"), "/login/…")
        self.assertEqual(logs.redact("/join/xyz"), "/join/…")
        self.assertEqual(logs.redact("/api/me"), "/api/me")
        self.assertEqual(logs.redact("/login/"), "/login/")
        self.assertNotIn("s3cret", logs.redact("/api/thing", "token=s3cret&page=2"))
        self.assertIn("page=2", logs.redact("/api/thing", "token=s3cret&page=2"))
        self.assertLessEqual(len(logs.redact("/" + "a" * 1000)), logs.MAX_PATH_LENGTH + 1)


class EncryptionTest(LogsTestCase):
    def test_encrypted_lines_read_back(self) -> None:
        logger = self.logger(encrypt=True)
        self.write_now(logger, request("/api/secret-looking-path", 200))
        raw = (self.settings.dir / logs.part_name(logger.today(), 0, False)).read_bytes()
        self.assertNotIn(b"secret-looking-path", raw)
        records, _ = logger.read_day(logger.today(), logs.Query())
        self.assertEqual([r["request"]["path"] for r in records], ["/api/secret-looking-path"])

        # The same files read under another key give nothing, not garbage.
        other = self.logger(encrypt=True)
        self.assertEqual(other.read_day(logger.today(), logs.Query())[0], [])


class RotationTest(LogsTestCase):
    def test_parts_and_paging(self) -> None:
        logger = self.logger(max_file_bytes=400)
        for index in range(30):
            self.write_now(logger, request("/api/item/" + "x" * (index % 3), 200 + index))
        parts = logger.day_files(logger.today())
        self.assertGreaterEqual(len(parts), 3)
        for part in parts:
            self.assertLessEqual(part.size, 400)

        seen: list[int] = []
        before = -1
        while True:
            records, following = logger.read_day(logger.today(), logs.Query(), before, 7)
            seen += [r["request"]["status"] for r in records]
            if following is None:
                break
            before = following
        self.assertEqual(seen, [229 - index for index in range(30)])


class PruneTest(LogsTestCase):
    def test_retention_compression_and_recycling(self) -> None:
        fixed = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        logger = self.logger(retention_days=5, compress_after_days=2)
        logger.now = lambda: fixed
        for days_ago in (0, 1, 2, 3, 9):
            self.write_now(logger, request("/api/day", 200, ts=logs.now_iso(fixed - timedelta(days=days_ago))))

        result = logger.prune()
        self.assertEqual((result["deleted"], result["compressed"]), (1, 2))
        by_day = logger.files()
        self.assertNotIn("2026-10-24", by_day)
        self.assertTrue(by_day["2026-10-31"][0].compressed)
        self.assertEqual(len(logger.read_day("2026-10-31", logs.Query())[0]), 1)

        # Recycling: a cap below what is there removes the oldest days, never
        # today.
        logger.settings = replace(logger.settings, max_total_bytes=1)
        logger.prune()
        self.assertEqual(list(logger.files()), ["2026-11-02"])
        with self.assertRaises(logs.TodayError):
            logger.delete_day("2026-11-02")


class QueryTest(LogsTestCase):
    def test_grammar(self) -> None:
        failing = request("/api/admin/users", 503, actor={"user_id": 7, "name": "Ana Lopez", "method": "session"}, ip="10.0.0.5")
        click = logs.entry(logs.KIND_UI, ui={"action": "click", "screen": "users", "target": "admin.create_button"})
        cases = [
            ("status:5xx", failing, True),
            ("status:4xx", failing, False),
            ("status:503", failing, True),
            ("user:ana", failing, True),
            ("user:7", failing, True),
            ("user:bob", failing, False),
            ("path:/api/admin", failing, True),
            ("ip:10.0.", failing, True),
            ("kind:ui,auth", failing, False),
            ("kind:ui,auth", click, True),
            ("-kind:request", failing, False),
            ("-kind:request", click, True),
            ("action:click screen:users", click, True),
            ("create_button", click, True),
            ('"ana lopez"', failing, True),
            ("users -status:5xx", failing, False),
            ("nonsense:thing", click, False),
        ]
        for text, record, want in cases:
            line = json.dumps(record, ensure_ascii=False).lower()
            self.assertEqual(logs.Query(text).match(record, line), want, f"{text!r} on {line}")


class QueueTest(LogsTestCase):
    def test_never_blocks(self) -> None:
        logger = self.logger()
        # Not started: nothing drains the queue, so it fills and then drops.
        for _ in range(logs.QUEUE_SIZE + 5):
            logger.log(request("/", 200))
        self.assertEqual(logger.dropped, 5)


if __name__ == "__main__":
    unittest.main()
