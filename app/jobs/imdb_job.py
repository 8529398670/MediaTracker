"""Keeps the IMDb ratings table fresh: one conditional download a day
(jobs.imdb_refresh_hours), parsed into the packed arrays reference/imdb.py
reads. A failure keeps the old table and is retried an hour later."""
from __future__ import annotations

import time
from typing import Any

from app.jobs.runner import Job, register
from app.providers import net
from app.reference import imdb

RETRY_SECONDS = 3600


class ImdbJob(Job):
    name = "imdb"

    def extra_status(self) -> dict[str, Any]:
        return imdb.STORE.status()

    def due(self) -> bool:
        cfg = getattr(self, "cfg", None)
        if cfg is None or imdb.STORE.folder is None:
            return False
        if self.last_error and time.time() - self.last_started < RETRY_SECONDS:
            return False
        return imdb.STORE.due(cfg.jobs.imdb_refresh_hours)

    def run(self, **_options: Any) -> dict[str, Any]:
        self.message = "checking datasets.imdbws.com"
        changed = imdb.STORE.refresh(net.fetch_file)
        return {"changed": changed, "titles": imdb.STORE.count()}


JOB = register(ImdbJob())
