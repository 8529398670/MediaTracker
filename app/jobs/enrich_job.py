"""Filling in titles: posters, overview, cast, genres, runtime, age rating,
IMDb and Wikipedia links -- from whichever provider knows (see
app/providers/enrich.py for the chain).

Two ways in. A title added by anyone is queued at once (jobs.enrich_on_add),
and the job drains the queue in the background. An admin can also start a
pass over the whole library from the Jobs screen, choosing a scope:
"missing" (titles with no poster or no details), "all" (every blank on every
title) or "refresh" (re-ask even where something is filled in, for provider
facts only -- a person's own title, tags and notes are never touched).
"""
from __future__ import annotations

import threading
from typing import Any

from app.core.db import Store
from app.jobs.runner import Job, register
from app.models import library_cache

_pending: list[str] = []
_pending_lock = threading.Lock()

SCOPES = ("missing", "all", "refresh")


def needs_work(title: dict[str, Any], scope: str) -> bool:
    if scope == "refresh":
        return True
    if scope == "all":
        return any(not title.get(field) for field in ("poster_url", "overview", "genres", "year", "imdb_id", "wiki_url", "runtime", "cast"))
    return not title.get("poster_url") or not title.get("overview") or not title.get("genres") or not title.get("year")


class EnrichJob(Job):
    name = "enrich"

    def __init__(self) -> None:
        super().__init__()
        self.store: Store | None = None
        self.filled = 0

    def extra_status(self) -> dict[str, Any]:
        with _pending_lock:
            return {"queued": len(_pending), "filled": self.filled, "scopes": list(SCOPES)}

    def run(self, scope: str = "queue", limit: int = 0, **_options: Any) -> dict[str, Any]:
        from app.providers import enrich

        assert self.store is not None
        snapshot = library_cache.get(self.store)
        if scope in SCOPES:
            ids = [title["id"] for title in snapshot.live_titles() if needs_work(title, scope)]
            if limit:
                ids = ids[:limit]
            with _pending_lock:
                for ident in ids:
                    if ident not in _pending:
                        _pending.append(ident)
        self.filled = 0
        while not self.stopping:
            with _pending_lock:
                if not _pending:
                    break
                ident = _pending.pop(0)
                self.total = self.done + len(_pending) + 1
            title = library_cache.get(self.store).titles.get(ident)
            if title is not None and title.get("deleted_at") is None:
                self.message = title.get("title", "")
                changed = enrich.enrich_and_save(self.store, title, refresh=(scope == "refresh"))
                if changed:
                    self.filled += 1
            self.done += 1
        return {"checked": self.done, "filled": self.filled}


JOB = register(EnrichJob())


def queue_titles(ids: list[str]) -> None:
    """Fill these in soon. Starts the job if it is idle."""
    with _pending_lock:
        for ident in ids:
            if ident not in _pending:
                _pending.append(ident)
    if JOB.store is not None and not JOB.running:
        JOB.start(scope="queue")
