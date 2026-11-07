"""One shape for every background job: a daemon thread, a stop flag, and a
status anyone can read.

At most one run of a job at a time. A job's work is network-bound and slow;
its writes go through short model calls (titles.fill_title and friends), never
one long transaction, so the app stays responsive while it runs and a person
editing a title always wins over a job that read it a moment earlier.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable

from app.models import to_iso, utc_now


class Job:
    name = "job"
    # Admins may start and stop it from the Jobs screen.
    manual = True

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.done = 0
        self.total = 0
        self.message = ""
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.last_error = ""
        self.last_result: dict[str, Any] = {}
        self.last_started = 0.0

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "manual": self.manual,
            "running": self.running,
            "done": self.done,
            "total": self.total,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_error": self.last_error,
            "last_result": self.last_result,
            **self.extra_status(),
        }

    def extra_status(self) -> dict[str, Any]:
        return {}

    def start(self, **options: Any) -> bool:
        """False if it is already running."""
        with self.lock:
            if self.running:
                return False
            self.stop_event.clear()
            self.done = 0
            self.total = 0
            self.message = ""
            self.last_error = ""
            self.started_at = to_iso(utc_now())
            self.finished_at = None
            self.last_started = time.time()
            self.thread = threading.Thread(target=self._main, kwargs=options, name=f"job-{self.name}", daemon=True)
            self.thread.start()
            return True

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def stopping(self) -> bool:
        return self.stop_event.is_set()

    def _main(self, **options: Any) -> None:
        try:
            self.last_result = self.run(**options) or {}
        except Exception as error:  # noqa: BLE001 -- a job failing must never take the server down
            self.last_error = f"{type(error).__name__}: {error}"
            print(f"[job:{self.name}] failed: {self.last_error}", flush=True)
            traceback.print_exc()
        finally:
            self.finished_at = to_iso(utc_now())

    def run(self, **options: Any) -> dict[str, Any] | None:  # pragma: no cover - overridden
        raise NotImplementedError

    def due(self) -> bool:
        """Whether the scheduler should start it now on its own."""
        return False


REGISTRY: dict[str, Job] = {}


def register(job: Job) -> Job:
    REGISTRY[job.name] = job
    return job


def statuses() -> list[dict[str, Any]]:
    return [job.status() for job in REGISTRY.values()]


def stop_all() -> None:
    for job in REGISTRY.values():
        job.stop()


def wait(predicate: Callable[[], bool], seconds: float) -> None:
    """Sleep in short steps so a stop is noticed quickly."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not predicate():
        time.sleep(min(0.5, end - time.monotonic()))
