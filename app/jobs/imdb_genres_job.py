"""Genres from elsewhere: IMDb's file, and the Discover catalogue.

One job, in the only order that works: fetch IMDb's genres for every film the
catalogue and the library have an id for, fold them into the catalogue, then
offer the library what the catalogue now knows. Every title is offered this
once (titles.add_reference_genres), so a genre someone took off by hand stays
off; a title added later gets its turn on the next run.

A failure keeps the old table and is retried an hour later.
"""
from __future__ import annotations

import time
from typing import Any

from app.discover import catalogue, certs
from app.jobs.runner import Job, register
from app.media import dupes
from app.models import library_cache, titles
from app.providers import net
from app.reference import imdb_genres

RETRY_SECONDS = 3600


def wanted_ids(library: list[dict[str, Any]]) -> set[str]:
    found = {entry[certs.E_IMDB] for entry in certs.STORE.snapshot().values() if entry[certs.E_IMDB]}
    found.update(title["imdb_id"] for title in library if title.get("imdb_id"))
    return found


def film_for(title: dict[str, Any], index: tuple[dict, dict, dict]) -> list[str]:
    """What the catalogue says about a library title. By the Wikipedia article
    where there is one; a name and a year only for a film, since a series of
    the same name and year is a different thing."""
    by_key, by_wiki, by_name = index
    if title.get("catalogue_key") in by_key:
        return by_key[title["catalogue_key"]]
    wiki = dupes.wiki_key(title.get("wiki_url") or "")
    if wiki and wiki in by_wiki:
        return by_wiki[wiki]
    if title.get("type") == "movie" and title.get("year"):
        return by_name.get(f"{dupes.norm_key(title.get('title'))}|{title['year']}", [])
    return []


def fill_library(store: Any) -> int:
    """Offer every title not yet offered what is known about it."""
    index = catalogue.genre_index()
    extras: dict[str, list[str]] = {}
    for title in library_cache.get(store).live_titles():
        extras[title["id"]] = imdb_genres.STORE.get(title.get("imdb_id")) + film_for(title, index)
    return titles.add_reference_genres(store, extras)


class ImdbGenresJob(Job):
    name = "imdb_genres"

    def extra_status(self) -> dict[str, Any]:
        return {"genre_titles": imdb_genres.STORE.count(), "file_date": imdb_genres.STORE.meta.get("fileDate", "")}

    def due(self) -> bool:
        cfg = getattr(self, "cfg", None)
        if cfg is None or imdb_genres.STORE.folder is None:
            return False
        if self.last_error and time.time() - self.last_started < RETRY_SECONDS:
            return False
        return imdb_genres.STORE.due(cfg.jobs.imdb_genres_refresh_hours)

    def run(self, **_options: Any) -> dict[str, Any]:
        store = self.store  # type: ignore[attr-defined]
        self.message = "downloading IMDb's title file"
        wanted = wanted_ids(library_cache.get(store).live_titles())

        def reading(rows: int) -> None:
            self.message = f"reading it: {rows:,} rows"

        held = imdb_genres.STORE.refresh(net.fetch_file, wanted, reading)
        self.message = "rebuilding the Discover catalogue"
        catalogue.rebuild()
        self.message = "filling in the library"
        filled = fill_library(store)
        self.message = ""
        return {"titles": held, "library_filled": filled}


JOB = register(ImdbGenresJob())
