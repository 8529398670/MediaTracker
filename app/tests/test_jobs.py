"""Background jobs (app/core/jobs.py, app/core/housekeeping.py): what is due
survives a restart, nothing overlaps, a failing job is recorded and nothing
worse, and stopping neither hangs on a job nor cancels it. Every test drives
run_due directly, so none of them sleep through a tick."""
from __future__ import annotations

import asyncio
import contextlib
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app.core import db, encryption, housekeeping, jobs, logs
from app.core.config import LogsConfig
from app.models import from_iso, sessions
from app.models.jobs import get_job_record, mark_started
from app.tests.support import new_holder

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def quiet_logger() -> logs.Logger:
    return logs.Logger(LogsConfig(enabled=False), encryption.generate_key_hex(), False)


class JobsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "app.db"
        self.key = encryption.generate_key_hex()
        self.store = db.open_store(self.path, self.key, True)
        self.clock = T0
        self.calls: list[str] = []

    def registry(self, store: db.Store | None = None) -> jobs.Registry:
        registry = jobs.Registry(store or self.store, quiet_logger())
        registry.now = lambda: self.clock
        return registry

    def counted(self, name: str, result: tuple[str, str] = ("done", "")):
        def fn() -> tuple[str, str]:
            self.calls.append(name)
            return result

        return fn

    async def run_due(self, registry: jobs.Registry, now: datetime) -> None:
        tasks = await registry.run_due(now)
        if tasks:
            await asyncio.gather(*tasks)


class ScheduleTest(JobsTestCase):
    async def test_a_job_never_run_is_due_at_once(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a"))
        await self.run_due(registry, T0)
        self.assertEqual(self.calls, ["a"])

    async def test_not_due_until_the_interval_has_passed(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a"))
        await self.run_due(registry, T0)
        await self.run_due(registry, T0 + HOUR - timedelta(seconds=1))
        self.assertEqual(self.calls, ["a"])
        await self.run_due(registry, T0 + HOUR)
        self.assertEqual(self.calls, ["a", "a"])

    async def test_due_time_survives_a_reopen(self) -> None:
        """The bug this replaces: a server restarted more often than hourly
        never ran its housekeeping, because each start slept an hour first."""
        first = self.registry()
        first.register("a", 3600, self.counted("a"))
        await self.run_due(first, T0)

        reopened = self.registry(db.open_store(self.path, self.key, True))
        reopened.register("a", 3600, self.counted("a"))
        await self.run_due(reopened, T0 + timedelta(seconds=5))
        self.assertEqual(self.calls, ["a"])
        await self.run_due(reopened, T0 + 2 * HOUR)
        self.assertEqual(self.calls, ["a", "a"])

    async def test_last_started_is_written_before_the_job_runs(self) -> None:
        seen: list[datetime | None] = []

        def fn() -> tuple[str, str]:
            seen.append(get_job_record(self.store, "a").last_started)
            return "", ""

        registry = self.registry()
        registry.register("a", 3600, fn)
        await self.run_due(registry, T0)
        self.assertEqual(seen, [T0])

    async def test_a_second_registration_of_a_name_is_a_mistake(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a"))
        with self.assertRaises(ValueError):
            registry.register("a", 3600, self.counted("a"))


class OverlapTest(JobsTestCase):
    async def test_a_running_job_does_not_start_again(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        runs = []

        def fn() -> tuple[str, str]:
            runs.append(1)
            release.wait(5)
            return "", ""

        registry = self.registry()
        registry.register("a", 1, fn)
        first = await registry.run_due(T0)
        self.assertEqual(len(first), 1)
        self.assertEqual(await registry.run_due(T0 + HOUR), [])
        with self.assertRaises(jobs.JobRunningError):
            registry.run_now("a")
        self.assertTrue(registry.rows()[0]["running"])
        self.assertFalse(registry.rows()[0]["interrupted"])
        release.set()
        await asyncio.gather(*first)
        self.assertEqual(len(runs), 1)
        self.assertFalse(registry.rows()[0]["running"])

    async def test_run_now_ignores_the_schedule_and_knows_its_jobs(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a"))
        await self.run_due(registry, T0)
        await registry.run_now("a")
        self.assertEqual(self.calls, ["a", "a"])
        with self.assertRaises(jobs.UnknownJobError):
            registry.run_now("nope")


class FailureTest(JobsTestCase):
    async def test_an_exception_is_the_jobs_failure_and_nothing_more(self) -> None:
        def explode() -> tuple[str, str]:
            raise ValueError("it broke")

        registry = self.registry()
        registry.register("a", 3600, explode)
        registry.register("b", 3600, self.counted("b"))
        await self.run_due(registry, T0)
        self.assertEqual(self.calls, ["b"])
        row = registry.rows()[0]
        self.assertFalse(row["last_ok"])
        self.assertEqual(row["last_error"], "it broke")
        self.assertFalse(row["running"])
        self.assertEqual(get_job_record(self.store, "a").last_failure, T0)

        await self.run_due(registry, T0 + HOUR)
        self.assertEqual(registry.rows()[0]["runs"], 2)

    async def test_a_returned_error_is_a_failure_too(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a", ("half done", "step two")))
        await self.run_due(registry, T0)
        row = registry.rows()[0]
        self.assertFalse(row["last_ok"])
        self.assertEqual((row["last_note"], row["last_error"]), ("half done", "step two"))

    async def test_a_tick_that_fails_keeps_ticking(self) -> None:
        registry = self.registry()
        reached = asyncio.Event()

        async def broken(now: datetime) -> list:
            reached.set()
            raise RuntimeError("no database")

        registry.run_due = broken  # type: ignore[method-assign]
        registry.start()
        await asyncio.wait_for(reached.wait(), 2)
        self.assertFalse(registry._ticker.done())
        await registry.stop()


class RowsTest(JobsTestCase):
    async def test_sorted_with_optional_fields_left_out_until_they_exist(self) -> None:
        registry = self.registry()
        registry.register("zebra", 3600, self.counted("z"))
        registry.register("alpha", 7200, self.counted("a"))
        rows = registry.rows()
        self.assertEqual([row["name"] for row in rows], ["alpha", "zebra"])
        self.assertEqual(
            set(rows[0]), {"name", "interval_seconds", "running", "interrupted", "runs", "next_due"}
        )
        self.assertEqual(rows[0]["interval_seconds"], 7200)
        self.assertEqual(rows[0]["runs"], 0)
        self.assertEqual(from_iso(rows[0]["next_due"]), T0)

    async def test_after_a_run(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a", ("all good", "")))
        await self.run_due(registry, T0)
        row = registry.rows()[0]
        self.assertTrue(row["last_ok"])
        self.assertEqual(row["last_note"], "all good")
        self.assertNotIn("last_error", row)
        self.assertEqual(row["runs"], 1)
        self.assertEqual(from_iso(row["next_due"]), T0 + HOUR)
        self.assertEqual(from_iso(row["last_started"]), T0)
        self.assertEqual(from_iso(row["last_finished"]), T0)
        self.assertFalse(row["interrupted"])

    async def test_a_run_the_process_died_in_shows_as_interrupted(self) -> None:
        registry = self.registry()
        registry.register("a", 3600, self.counted("a"))
        await self.run_due(registry, T0)
        mark_started(self.store, "a", T0 + HOUR)

        reopened = self.registry()
        reopened.register("a", 3600, self.counted("a"))
        row = reopened.rows()[0]
        self.assertTrue(row["interrupted"])
        self.assertFalse(row["running"])

        self.clock = T0 + 2 * HOUR
        await self.run_due(reopened, self.clock)
        self.assertFalse(reopened.rows()[0]["interrupted"])

    async def test_a_first_run_that_never_finished_is_interrupted_too(self) -> None:
        mark_started(self.store, "a", T0)
        registry = self.registry()
        registry.register("a", 3600, self.counted("a"))
        self.assertTrue(registry.rows()[0]["interrupted"])


class StopTest(JobsTestCase):
    async def test_waits_for_a_run_that_finishes_in_time(self) -> None:
        def fn() -> tuple[str, str]:
            time.sleep(0.05)
            return "finished", ""

        registry = self.registry()
        registry.register("a", 3600, fn)
        await registry.run_due(T0)
        await registry.stop()
        self.assertEqual(get_job_record(self.store, "a").last_note, "finished")

    async def test_gives_up_on_a_slow_run_without_cancelling_it(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        finished = threading.Event()

        def fn() -> tuple[str, str]:
            release.wait(5)
            finished.set()
            return "got there", ""

        registry = self.registry()
        registry.register("a", 3600, fn)
        tasks = await registry.run_due(T0)
        started = time.monotonic()
        await registry.stop(wait_seconds=0.05)
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(tasks[0].done())
        self.assertFalse(tasks[0].cancelled())
        release.set()
        await asyncio.gather(*tasks)
        self.assertTrue(finished.is_set())
        self.assertEqual(get_job_record(self.store, "a").last_note, "got there")

    async def test_stops_the_tick(self) -> None:
        registry = self.registry()
        registry.start()
        ticker = registry._ticker
        await registry.stop()
        await asyncio.sleep(0)
        self.assertTrue(ticker.cancelled() or ticker.cancelling())


class HousekeepingTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.holder, _ = new_holder(self, app_dir=str(self.root / "data"))
        cfg = self.holder.boot()
        cfg.app_dir.mkdir(parents=True, exist_ok=True)
        self.store = db.open_store(cfg.database_path, cfg.secret_key, True)

    def test_every_purge_step_runs_and_the_errors_are_joined(self) -> None:
        session_id, _, session = sessions.new_session(1, -10)
        self.store.put(db.BUCKET_SESSIONS, session_id, session.to_record())
        with contextlib.ExitStack() as patches:
            patches.enter_context(mock.patch("app.models.api_keys.purge_dead_api_keys", side_effect=RuntimeError("keys broke")))
            patches.enter_context(mock.patch("app.models.login_tokens.purge_expired_login_tokens", side_effect=RuntimeError("tokens broke")))
            note, error = housekeeping.purge(self.store)
        self.assertIn("api keys: keys broke", error)
        self.assertIn("login tokens: tokens broke", error)
        self.assertIn("1 sessions", note)
        self.assertIsNone(self.store.get(db.BUCKET_SESSIONS, session_id))

    def test_a_clean_purge_says_so(self) -> None:
        self.assertEqual(housekeeping.purge(self.store), ("nothing to remove", ""))


    def test_prune_logs_exists_only_with_the_log(self) -> None:
        names = {}
        for enabled in (True, False):
            settings = LogsConfig(enabled=enabled, dir=self.root)
            registry = jobs.Registry(self.store, quiet_logger())
            housekeeping.register(registry, self.store, self.holder, logs.Logger(settings, encryption.generate_key_hex(), False))
            names[enabled] = [row["name"] for row in registry.rows()]
        always = ["purge"]
        self.assertEqual(names[True], sorted([*always, "prune-logs"]))
        self.assertEqual(names[False], sorted(always))


if __name__ == "__main__":
    unittest.main()
