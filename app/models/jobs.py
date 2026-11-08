"""What is remembered about a background job between runs: when it last
started and finished, and how it ended. The registry itself is
app/core/jobs.py. Whether one is running right now is deliberately not here:
a crash would leave it true for ever."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.db import BUCKET_JOBS, Record, Store
from app.models import from_iso, to_iso


@dataclass
class JobRecord:
    name: str
    last_started: datetime | None = None
    last_finished: datetime | None = None
    last_ok: bool | None = None
    last_note: str = ""
    last_error: str = ""
    # The latest of each outcome, which last_ok alone would lose. /metrics
    # reports them.
    last_success: datetime | None = None
    last_failure: datetime | None = None
    # Runs started, whether or not they got to finish.
    runs: int = 0

    def to_record(self) -> Record:
        return {
            "name": self.name,
            "last_started": to_iso(self.last_started),
            "last_finished": to_iso(self.last_finished),
            "last_ok": self.last_ok,
            "last_note": self.last_note,
            "last_error": self.last_error,
            "last_success": to_iso(self.last_success),
            "last_failure": to_iso(self.last_failure),
            "runs": self.runs,
        }

    @classmethod
    def from_record(cls, record: Record) -> "JobRecord":
        return cls(
            name=record["name"],
            last_started=from_iso(record.get("last_started")),
            last_finished=from_iso(record.get("last_finished")),
            last_ok=record.get("last_ok"),
            last_note=record.get("last_note", ""),
            last_error=record.get("last_error", ""),
            last_success=from_iso(record.get("last_success")),
            last_failure=from_iso(record.get("last_failure")),
            runs=record.get("runs", 0),
        )

    @property
    def finished_since_start(self) -> bool:
        """False when the latest start has no finish after it: a run under way
        or, once the process is gone, one that never ended."""
        if self.last_started is None:
            return True
        return self.last_finished is not None and self.last_finished >= self.last_started


def all_job_records(store: Store) -> dict[str, JobRecord]:
    return {str(name): JobRecord.from_record(record) for name, record in store.all(BUCKET_JOBS)}


def get_job_record(store: Store, name: str) -> JobRecord:
    """An empty record for a job that has never run."""
    record = store.get(BUCKET_JOBS, name)
    return JobRecord(name=name) if record is None else JobRecord.from_record(record)


def mark_started(store: Store, name: str, at: datetime) -> None:
    """Written before the job runs, so a run the process died in still counts
    towards when the job is next due."""
    with store.transaction() as tx:
        record = tx.get(BUCKET_JOBS, name)
        job = JobRecord(name=name) if record is None else JobRecord.from_record(record)
        job.last_started = at
        job.runs += 1
        tx.put(BUCKET_JOBS, name, job.to_record())


def mark_finished(store: Store, name: str, at: datetime, note: str, error: str) -> None:
    with store.transaction() as tx:
        record = tx.get(BUCKET_JOBS, name)
        job = JobRecord(name=name) if record is None else JobRecord.from_record(record)
        job.last_finished = at
        job.last_ok = error == ""
        job.last_note = note
        job.last_error = error
        if error:
            job.last_failure = at
        else:
            job.last_success = at
        tx.put(BUCKET_JOBS, name, job.to_record())
