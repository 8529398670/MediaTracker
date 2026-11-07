"""The Discover catalogue harvest and the age-rating pass, as jobs.

Both were written for the old app as self-contained workers with their own
thread, pacing and progress (app/discover/catalogue.py: Harvester,
Certifier); these wrappers give them the Jobs screen's shape -- start, stop,
status -- without rewriting work that already paces itself politely against
Wikimedia.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.discover import catalogue
from app.jobs.runner import Job, register


class WrappedJob(Job):
    worker: Any = None

    @property
    def running(self) -> bool:  # type: ignore[override]
        return bool(self.worker.status().get("running"))

    def stop(self) -> None:
        self.worker.stop()

    def status(self) -> dict[str, Any]:
        state = self.worker.status()
        return {
            "name": self.name,
            "manual": True,
            "running": bool(state.get("running")),
            "done": state.get("done", 0),
            "total": state.get("total", 0),
            "message": state.get("current") or state.get("note") or "",
            "started_at": state.get("startedAt") or None,
            "finished_at": state.get("finishedAt") or None,
            "last_error": "",
            "last_result": {"note": state.get("note", "")},
            **self.extra(state),
        }

    def extra(self, state: dict[str, Any]) -> dict[str, Any]:
        return {}


class HarvestJob(WrappedJob):
    name = "harvest"
    worker = catalogue.HARVESTER

    def extra(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"films": (state.get("coverage") or {}).get("films", 0), "scopes": ["recent", "all"]}

    def start(self, scope: str = "recent", **_options: Any) -> bool:
        """"recent": this year and last (what changes); "all": every year
        and topic, which takes a while at Wikimedia's pace."""
        last = datetime.now(timezone.utc).year
        first = catalogue.FIRST_YEAR if scope == "all" else last - 1
        years = list(range(first, last + 1))
        topics = list(catalogue.TOPICS) if scope == "all" else []
        self.worker.start(list(catalogue.SETS), years, topics)
        return True


class CertifyJob(WrappedJob):
    name = "certify"
    worker = catalogue.CERTIFIER

    def extra(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"rated": state.get("rated", 0), "scopes": ["missing", "all"]}

    def start(self, scope: str = "missing", **_options: Any) -> bool:
        self.worker.start(scope if scope in ("missing", "all") else "missing")
        return True


HARVEST = register(HarvestJob())
CERTIFY = register(CertifyJob())
