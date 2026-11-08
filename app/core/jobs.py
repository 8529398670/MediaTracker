"""Background jobs: work the server does on a schedule, with nobody asking.
server/jobs/jobs.go is the same thing for the Go template.

A job is a name, an interval and a function returning (note, error). A tick
every 30 seconds starts whatever is due, and the owner can start one by hand
on the Jobs screen. What is due comes from the database, not from how long this
process has been up: last_started is written before a job runs and the next
run is last_started + interval, so a server restarted more often than a job's
interval still runs it, and restarting a moment after a run does not repeat it.
A job never run, or overdue, runs at the first tick after boot.

The rules, whatever the job does:

  - one run of a job at a time; a second start is refused (or simply not due)
  - an exception is the job's failure, recorded like any other, never the
    server's problem
  - `running` lives in memory only, so a crash cannot leave a job stuck; a run
    the process died in shows up as a start with no finish after it
  - stopping waits up to five seconds for a run under way, then leaves it. It
    is not cancelled: it runs in a worker thread that cannot be interrupted.
    Exit does not wait for that thread (graceful.run_abandonable)

The job functions are synchronous and run in a worker thread, so they may use
the store directly. Everything else here runs on the event loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from app.core import graceful, logs
from app.core.db import Store
from app.models import to_iso, utc_now
from app.models.jobs import JobRecord, all_job_records, mark_finished, mark_started

TICK_SECONDS = 30
STOP_WAIT_SECONDS = 5


class UnknownJobError(Exception):
    pass


class JobRunningError(Exception):
    pass


@dataclass
class Job:
    name: str
    interval: timedelta
    # Returns (note, error): what happened, in a few words, and why it failed,
    # empty when it did not.
    fn: Callable[[], tuple[str, str]]
    running: bool = False


class Registry:
    def __init__(self, store: Store, logger: logs.Logger) -> None:
        self.store = store
        self.logger = logger
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._ticker: asyncio.Task[None] | None = None
        # Replaced in tests.
        self.now: Callable[[], datetime] = utc_now
        # Hears the name of a job whose run failed, in the job's worker
        # thread. main points it at webhooks.
        self.on_failure: Callable[[str], None] | None = None

    def register(self, name: str, interval_seconds: int, fn: Callable[[], tuple[str, str]]) -> None:
        if name in self._jobs:
            raise ValueError(f"job {name!r} is already registered")
        self._jobs[name] = Job(name, timedelta(seconds=interval_seconds), fn)

    # -- starting ----------------------------------------------------------

    async def run_due(self, now: datetime) -> list[asyncio.Task[None]]:
        """Start every job due at now and return their tasks, without waiting
        for them: the tick must not stall behind a long backup. A test gathers
        the tasks instead of sleeping."""
        records = await graceful.run_abandonable(all_job_records, self.store)
        started = []
        for job in self._jobs.values():
            record = records.get(job.name)
            if job.running:
                continue
            if record is None or record.last_started is None or now >= record.last_started + job.interval:
                started.append(self._start(job))
        return started

    def run_now(self, name: str) -> asyncio.Task[None]:
        """Start one job by hand, due or not. Raises UnknownJobError or
        JobRunningError."""
        job = self._jobs.get(name)
        if job is None:
            raise UnknownJobError(name)
        if job.running:
            raise JobRunningError(name)
        return self._start(job)

    def _start(self, job: Job) -> asyncio.Task[None]:
        # Set here, before anything can yield to the event loop: the check and
        # the mark have to be one step for "no overlapping runs" to hold.
        job.running = True
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run(self, job: Job) -> None:
        try:
            await graceful.run_abandonable(self._execute, job)
        except Exception as error:  # noqa: BLE001 -- only the bookkeeping can land here
            print(f"[job] {job.name}: could not record the run: {error!r}", flush=True)
        finally:
            job.running = False

    def _execute(self, job: Job) -> None:
        mark_started(self.store, job.name, self.now())
        try:
            note, error = job.fn()
        except Exception as failure:  # noqa: BLE001 -- a job must never take the server down
            note, error = "", str(failure) or repr(failure)
        mark_finished(self.store, job.name, self.now(), note, error)
        if error:
            print(f"[job] {job.name} failed: {error}", flush=True)
            self.logger.system(logs.LEVEL_ERROR, "job failed", {"job": job.name, "error": error})
            if self.on_failure is not None:
                self.on_failure(job.name)

    # -- the tick ----------------------------------------------------------

    def start(self) -> None:
        self._ticker = asyncio.create_task(self._tick())

    async def _tick(self) -> None:
        while True:
            try:
                await self.run_due(self.now())
            except Exception as error:  # noqa: BLE001 -- nor may a bad tick end the schedule
                print(f"[job] tick failed: {error!r}", flush=True)
            await asyncio.sleep(TICK_SECONDS)

    async def stop(self, wait_seconds: float = STOP_WAIT_SECONDS) -> None:
        """asyncio.wait, not wait_for: wait_for would cancel what it gave up
        on."""
        if self._ticker is not None:
            self._ticker.cancel()
            self._ticker = None
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=wait_seconds)

    # -- reading -----------------------------------------------------------

    def records(self) -> dict[str, JobRecord]:
        """What is stored for each registered job. Reads SQLite: call it
        through run()."""
        stored = all_job_records(self.store)
        return {name: stored.get(name, JobRecord(name=name)) for name in self._jobs}

    def rows(self) -> list[dict[str, Any]]:
        """GET /api/owner/jobs, by name. Reads SQLite: call it through run()."""
        records = self.records()
        return [self._row(self._jobs[name], records[name]) for name in sorted(records)]

    def _row(self, job: Job, record: JobRecord) -> dict[str, Any]:
        next_due = self.now() if record.last_started is None else record.last_started + job.interval
        row: dict[str, Any] = {
            "name": job.name,
            "interval_seconds": int(job.interval.total_seconds()),
            "running": job.running,
            "interrupted": not job.running and not record.finished_since_start,
            "runs": record.runs,
            "next_due": to_iso(next_due),
        }
        if record.last_started is not None:
            row["last_started"] = to_iso(record.last_started)
        if record.last_finished is not None:
            row["last_finished"] = to_iso(record.last_finished)
        if record.last_ok is not None:
            row["last_ok"] = record.last_ok
        if record.last_note:
            row["last_note"] = record.last_note
        if record.last_error:
            row["last_error"] = record.last_error
        return row
