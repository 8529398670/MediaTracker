"""Puts an Apple TV link on every title that has an IMDb id and none yet,
once a day (jobs.appletv_hours). Ids Wikidata had nothing for are not asked
about again until the server restarts. When Wikidata is rate-limiting, the
run ends early with what it got and the job is due again in an hour."""
from __future__ import annotations

import time
from typing import Any

from app.jobs.runner import Job, register, wait
from app.models import library_cache, titles
from app.providers import appletv


THROTTLED_RETRY_HOURS = 1


class AppleTvJob(Job):
    name = "appletv"

    def __init__(self) -> None:
        super().__init__()
        self.asked: set[str] = set()
        self.throttled = False

    def due(self) -> bool:
        cfg = getattr(self, "cfg", None)
        if cfg is None:
            return False
        hours = THROTTLED_RETRY_HOURS if self.throttled else cfg.jobs.appletv_hours
        return not self.last_started or time.time() - self.last_started >= hours * 3600

    def _pause(self, seconds: float) -> bool:
        self.message = "Wikidata is rate-limiting; waiting a minute"
        wait(lambda: self.stopping, seconds)
        return not self.stopping

    def run(self, **_options: Any) -> dict[str, Any]:
        store = self.store  # type: ignore[attr-defined]
        wanted: dict[str, list[dict[str, Any]]] = {}
        for title in library_cache.get(store).live_titles():
            imdb = title.get("imdb_id") or ""
            if imdb and not title.get("apple_tv") and imdb not in self.asked:
                wanted.setdefault(imdb, []).append(title)
        self.total = len(wanted)
        if not wanted:
            return {"linked": 0}
        self.message = f"asking Wikidata about {len(wanted)} titles"
        answer = appletv.lookup(sorted(wanted), pause=self._pause)
        found = answer.found
        self.throttled = answer.throttled
        self.asked.update(ident for ident in answer.answered if ident not in found)
        linked = 0
        for imdb, path in found.items():
            for title in wanted.get(imdb, []):
                if titles.fill_title(store, title["id"], {"apple_tv": path}, title.get("updated_at")):
                    linked += 1
        self.done = len(answer.answered)
        result: dict[str, Any] = {"linked": linked, "not_on_wikidata": len(answer.answered) - len(found)}
        if answer.throttled:
            result["throttled"] = True
            result["not_asked_yet"] = len(wanted) - len(answer.answered)
            self.message = f"Wikidata is rate-limiting; {result['not_asked_yet']} titles left for the next run"
            print(f"[job:{self.name}] {self.message}", flush=True)
        return result


JOB = register(AppleTvJob())
