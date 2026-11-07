"""Starts the jobs that run on their own: the daily IMDb ratings check and
the Apple TV id lookup. Everything else (the full fill-in pass, the
Wikipedia harvest, age ratings) is started by an admin from the Jobs screen
or by a title being added.

The scheduler only decides *when*; each job decides *whether* (Job.due), so
the schedule lives next to the work it schedules.
"""
from __future__ import annotations

import asyncio

from app.core.config import Config
from app.core.db import Store
from app.jobs import runner

CHECK_SECONDS = 60
# A minute after start, not at once: a restart should not open with a burst
# of outbound calls while the first page is loading.
FIRST_DELAY_SECONDS = 60


def prepare(store: Store, cfg: Config) -> None:
    """Hand every job the store and config, once, at startup. Importing the
    job modules is what registers them."""
    from app.jobs import appletv_job, enrich_job, harvest_job, imdb_genres_job, imdb_job  # noqa: F401

    for job in runner.REGISTRY.values():
        job.store = store  # type: ignore[attr-defined]
        job.cfg = cfg  # type: ignore[attr-defined]


async def loop(store: Store, cfg: Config) -> None:
    if not cfg.providers.network:
        return
    await asyncio.sleep(FIRST_DELAY_SECONDS)
    while True:
        for job in list(runner.REGISTRY.values()):
            try:
                if not job.running and job.due():
                    job.start()
            except Exception as error:  # noqa: BLE001 -- scheduling must never take the server down
                print(f"[jobs] could not start {job.name}: {error}", flush=True)
        await asyncio.sleep(CHECK_SECONDS)
