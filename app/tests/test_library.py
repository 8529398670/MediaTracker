"""The shared library and each person's state over it: edits that refuse to
overwrite a change made elsewhere, soft deletes and the purge,
the in-memory snapshot noticing writes from another process, merging and
its undo, imports and their undo, and an account taking its state with it."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from app.core import db
from app.core.db import BUCKET_TITLES
from app.discover import catalogue
from app.media import genres
from app.models import RestoreExpiredError, credentials, import_batches, library_cache, merges, to_iso, types, user_state, users, utc_now, verdicts
from app.models import revision
from app.models import titles as titles_model
from app.models.revision import ConflictError, NotFoundError


class LibraryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "app.db"
        self.store = db.Store(self.path, "", False)
        self.store.initialise()
        types.ensure_builtin(self.store)
        self.admin = users.create_user(self.store, "Halo", users.ROLE_ADMIN)
        self.mom = users.create_user(self.store, "Mom", users.ROLE_USER)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def add(self, name: str, **fields: object) -> dict:
        return titles_model.create_title(self.store, {"title": name, **fields}, self.admin.id, 1000)


class TitleTest(LibraryTestCase):
    def test_update_returns_previous_values_and_honours_expect(self) -> None:
        title = self.add("Heat", year=1995)
        record, previous = titles_model.update_title(self.store, title["id"], {"year": 1996}, None, self.admin.id)
        self.assertEqual((record["year"], previous), (1996, {"year": 1995}))
        with self.assertRaises(ConflictError):
            titles_model.update_title(self.store, title["id"], {"year": 1995}, {"year": 1990}, self.mom.id)

    def test_fill_only_fills_blanks_and_stands_aside_for_an_edit(self) -> None:
        title = self.add("Heat", overview="mine")
        self.assertEqual(titles_model.fill_title(self.store, title["id"], {"overview": "theirs", "runtime": 170}, title["updated_at"]), {"runtime": None})
        self.assertEqual(titles_model.get_title(self.store, title["id"])["overview"], "mine")
        titles_model.update_title(self.store, title["id"], {"year": 1995}, None, self.mom.id)
        self.assertEqual(titles_model.fill_title(self.store, title["id"], {"creator": "Mann"}, title["updated_at"]), {})

    def test_delete_restore_and_purge_with_state(self) -> None:
        title = self.add("Heat")
        user_state.set_state(self.store, self.mom.id, title["id"], {"status": "queue"}, None, self.mom.id)
        titles_model.delete_title(self.store, title["id"], self.mom.id)
        self.assertEqual(titles_model.restore_title(self.store, title["id"], 30)["deleted_at"], None)
        titles_model.delete_title(self.store, title["id"], self.mom.id)
        self.store.update_value(BUCKET_TITLES, title["id"], lambda record: record.update(deleted_at=to_iso(utc_now() - timedelta(days=31))))
        with self.assertRaises(RestoreExpiredError):
            titles_model.restore_title(self.store, title["id"], 30)
        self.assertEqual(titles_model.purge_deleted_titles(self.store, 30), 1)
        self.assertIsNone(user_state.get_state(self.store, self.mom.id, title["id"]))


class StateTest(LibraryTestCase):
    def test_state_is_per_person(self) -> None:
        title = self.add("Heat")
        user_state.set_state(self.store, self.mom.id, title["id"], {"status": "watched"}, None, self.mom.id)
        self.assertIsNone(user_state.get_state(self.store, self.admin.id, title["id"]))
        state = user_state.get_state(self.store, self.mom.id, title["id"])
        self.assertEqual(state["status"], "watched")
        self.assertIsNotNone(state["watched_at"])

    def test_state_on_a_missing_title_is_refused(self) -> None:
        with self.assertRaises(NotFoundError):
            user_state.set_state(self.store, self.mom.id, "nope", {"status": "queue"}, None, self.mom.id)


class SnapshotTest(LibraryTestCase):
    def test_a_write_from_another_process_is_seen(self) -> None:
        self.add("Heat")
        self.assertEqual(len(library_cache.get(self.store).titles), 1)
        other = db.Store(self.path, "", False)
        titles_model.create_title(other, {"title": "Alien"}, None, 1000)
        snapshot = library_cache.get(self.store)
        self.assertEqual(sorted(t["title"] for t in snapshot.titles.values()), ["Alien", "Heat"])

    def test_social_counts(self) -> None:
        title = self.add("Heat")
        user_state.set_state(self.store, self.mom.id, title["id"], {"status": "watched", "heart": True, "rating": 8}, None, self.mom.id)
        social = library_cache.get(self.store).social[title["id"]]
        self.assertEqual((social["watched"], social["loved"], social["ratings"]), ([self.mom.id], [self.mom.id], {str(self.mom.id): 8}))


class MergeTest(LibraryTestCase):
    def test_merge_folds_states_and_undo_puts_it_all_back(self) -> None:
        keep = self.add("Sunrise", tags=["silent"])
        drop = self.add("Sunrise: A Song of Two Humans", tags=["murnau"], imdb_id="tt0018455")
        user_state.set_state(self.store, self.mom.id, drop["id"], {"status": "watched", "rating": 9}, None, self.mom.id)
        user_state.set_state(self.store, self.mom.id, keep["id"], {"status": "queue"}, None, self.mom.id)
        result = merges.merge(self.store, keep["id"], [drop["id"]], self.admin.id)
        merged = titles_model.get_title(self.store, keep["id"])
        self.assertEqual((merged["tags"], merged["imdb_id"]), (["silent", "murnau"], "tt0018455"))
        state = user_state.get_state(self.store, self.mom.id, keep["id"])
        self.assertEqual((state["status"], state["rating"]), ("watched", 9))
        self.assertIsNotNone(titles_model.get_title(self.store, drop["id"])["deleted_at"])
        merges.undo_merge(self.store, result["merge_id"])
        self.assertEqual(titles_model.get_title(self.store, keep["id"])["tags"], ["silent"])
        self.assertIsNone(titles_model.get_title(self.store, drop["id"])["deleted_at"])
        self.assertEqual(user_state.get_state(self.store, self.mom.id, keep["id"])["status"], "queue")
        self.assertEqual(user_state.get_state(self.store, self.mom.id, drop["id"])["rating"], 9)

    def test_undo_refuses_after_an_edit(self) -> None:
        keep, drop = self.add("Heat"), self.add("Heat (1995)")
        result = merges.merge(self.store, keep["id"], [drop["id"]], self.admin.id)
        titles_model.update_title(self.store, keep["id"], {"notes": "edited"}, None, self.mom.id)
        with self.assertRaises(ConflictError):
            merges.undo_merge(self.store, result["merge_id"])


class OtherModelsTest(LibraryTestCase):
    def test_import_batch_undo(self) -> None:
        a, b = self.add("A"), self.add("B")
        import_batches.record_created(self.store, "batch1", self.mom.id, [a["id"], b["id"]], self.mom.id)
        self.assertEqual(import_batches.undo_batch(self.store, "batch1", self.mom.id), 2)
        with self.assertRaises(NotFoundError):
            import_batches.undo_batch(self.store, "batch1", self.mom.id)

    def test_type_in_use_needs_a_destination_and_restores_with_its_titles(self) -> None:
        types.save_type(self.store, {"id": "radio", "label": "Radio", "lookup": "other"})
        title = self.add("Lux Radio Theatre", type="radio")
        with self.assertRaises(types.TypeInUseError):
            types.delete_type(self.store, "radio", None, self.admin.id)
        self.assertEqual(types.delete_type(self.store, "radio", "movie", self.admin.id), 1)
        self.assertEqual(titles_model.get_title(self.store, title["id"])["type"], "movie")
        types.restore_type(self.store, "radio", self.admin.id, True)
        self.assertEqual(titles_model.get_title(self.store, title["id"])["type"], "radio")
        with self.assertRaises(types.BuiltinTypeError):
            types.delete_type(self.store, "movie", "tv", self.admin.id)

    def test_verdicts_are_per_person_with_expect(self) -> None:
        self.assertIsNone(verdicts.set_verdict(self.store, self.mom.id, "w:heat", "skip"))
        self.assertEqual(verdicts.get_verdicts(self.store, self.admin.id), {})
        with self.assertRaises(ConflictError):
            verdicts.set_verdict(self.store, self.mom.id, "w:heat", None, expect=None)
        self.assertEqual(verdicts.set_verdict(self.store, self.mom.id, "w:heat", None, expect="skip"), "skip")

    def test_deleting_an_account_takes_its_state_not_its_titles(self) -> None:
        title = self.add("Heat")
        user_state.set_state(self.store, self.mom.id, title["id"], {"status": "queue"}, None, self.mom.id)
        verdicts.set_verdict(self.store, self.mom.id, "w:heat", "skip")
        credentials.delete_user(self.store, self.mom.id, self.admin.id)
        self.assertIsNone(user_state.get_state(self.store, self.mom.id, title["id"]))
        self.assertEqual(verdicts.get_verdicts(self.store, self.mom.id), {})
        self.assertIsNotNone(titles_model.get_title(self.store, title["id"]))



class GenreRefoldTest(LibraryTestCase):
    def stored(self, ident: str, genre_list: list[str]) -> None:
        with self.store.transaction() as tx:
            record = tx.get(BUCKET_TITLES, ident)
            record["genres"] = genre_list
            tx.put(BUCKET_TITLES, ident, record)

    def test_old_words_fold_once_and_only_changed_titles_move(self) -> None:
        old = self.add("Old")["id"]
        clean = self.add("Clean")["id"]
        self.stored(old, ["Animated", "6 Separate Stories", "Romantic Fantasy"])
        self.stored(clean, ["Romance", "Comedy"])
        before = self.store.get(BUCKET_TITLES, clean)["rev"]
        self.assertEqual(titles_model.refold_genres(self.store), 1)
        record = self.store.get(BUCKET_TITLES, old)
        self.assertEqual(record["genres"], ["Animation", "Romance", "Fantasy"])
        self.assertEqual(record["rev"], revision.current(self.store))
        self.assertEqual(self.store.get(BUCKET_TITLES, clean)["rev"], before)
        self.stored(old, ["Animated"])
        self.assertEqual(titles_model.refold_genres(self.store), 0)
        self.assertEqual(self.store.get(BUCKET_TITLES, old)["genres"], ["Animated"])

    def test_a_new_vocabulary_version_runs_it_again(self) -> None:
        old = self.add("Old")["id"]
        titles_model.refold_genres(self.store)
        self.stored(old, ["Animated"])
        with mock.patch.object(genres, "VOCABULARY_VERSION", genres.VOCABULARY_VERSION + 1):
            self.assertEqual(titles_model.refold_genres(self.store), 1)


class CatalogueGenreTest(unittest.TestCase):
    """The archive keeps what the vocabulary said the day a page was harvested;
    a rebuild has to bring it up to today."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        before = catalogue.LISTS_DIR
        self.addCleanup(catalogue.configure, before)
        self.lists = Path(folder.name)
        catalogue.configure(self.lists)
        (self.lists / "raw").mkdir()
        rows = [
            {"title": "Bride Talk", "year": 1940, "article": "Bride Talk", "genreText": "Romantic Comedy", "genres": ["Romance", "Comedy"]},
            {"title": "Night Rain", "year": 1941, "article": "Night Rain", "genreText": "film noir", "genres": ["Crime"]},
            {"title": "Odd One", "year": 1942, "article": "Odd One", "genreText": "First National", "genres": ["First National"]},
            {"title": "Cat Tale", "year": 1943, "article": "Cat Tale", "genres": ["Animated Short"]},
        ]
        page = {"page": "p", "title": "p", "set": "american", "topic": "", "year": 1940, "rows": rows}
        (self.lists / "raw" / "american-1940.json").write_text(json.dumps(page), encoding="utf-8")
        catalogue.rebuild()

    def facets(self, **query: object) -> dict[str, int]:
        return {entry["id"]: entry["count"] for entry in catalogue.query(**query)["facets"]["genres"]}

    def titles(self, **query: object) -> list[str]:
        return sorted(film["title"] for film in catalogue.query(**query)["films"])

    def test_a_rebuild_applies_todays_vocabulary(self) -> None:
        self.assertEqual(self.titles(genres=["Film Noir"]), ["Night Rain"])
        self.assertEqual(self.titles(genres=["crime"]), ["Night Rain"])
        self.assertEqual(self.titles(genres=["Animation"]), ["Cat Tale"])
        self.assertNotIn("First National", self.facets())

    def test_a_compound_is_a_filter_a_count_and_a_search(self) -> None:
        self.assertEqual(self.titles(genres=["Romantic Comedy"]), ["Bride Talk"])
        self.assertEqual(self.titles(genres=["Comedy"]), ["Bride Talk"])
        self.assertEqual(self.facets()["Romantic Comedy"], 1)
        self.assertEqual(self.titles(text="romantic comedy"), ["Bride Talk"])

    def test_a_film_stores_the_ingredients_not_the_compound(self) -> None:
        film = catalogue.query(genres=["Romantic Comedy"])["films"][0]
        self.assertEqual(film["genres"], ["Romance", "Comedy"])

    def test_the_facet_spells_names_properly_and_leads_with_the_most_used(self) -> None:
        names = [entry["label"] for entry in catalogue.genre_facet({"coming of age": 2, "tv movie": 2, "drama": 9, "romantic comedy": 3})]
        self.assertEqual(names, ["Drama", "Romantic Comedy", "Coming of Age", "TV Movie"])


if __name__ == "__main__":
    unittest.main()


class DiscoverHidingTest(LibraryTestCase):
    """What you watched, and what you skipped in the library, are hidden on
    Discover unless asked for."""

    def search(self, films: list[dict], **params: str) -> tuple[dict, dict]:
        from unittest import mock

        from app.routes import discover

        seen: dict = {}

        def fake_query(**kwargs: object) -> dict:
            seen.update(kwargs)
            return {"total": len(films), "films": [dict(film) for film in films]}

        with mock.patch.object(discover.catalogue, "query", fake_query):
            return discover.search(self.store, self.mom.id, params), seen

    def test_watched_and_dropped_titles_are_passed_to_the_catalogue(self) -> None:
        heat = self.add("Heat", year=1995, catalogue_key="w:heat 1995 film")
        alien = self.add("Alien", year=1979, wiki_url="https://en.wikipedia.org/wiki/Alien_(film)")
        user_state.set_state(self.store, self.mom.id, heat["id"], {"status": "watched"}, None, self.mom.id)
        user_state.set_state(self.store, self.mom.id, alien["id"], {"status": "dropped"}, None, self.mom.id)
        _result, query = self.search([])
        self.assertEqual((query["watched"], query["skipped"]), ("hide", "hide"))
        self.assertIn("w:heat 1995 film", query["seen"])
        self.assertIn("w:alien film", query["passed"])
        _result, query = self.search([], watched="only")
        self.assertEqual(query["watched"], "only")

    def test_a_watched_film_matched_by_name_is_kept_off_the_page(self) -> None:
        heat = self.add("Heat", year=1995)
        user_state.set_state(self.store, self.mom.id, heat["id"], {"status": "watched"}, None, self.mom.id)
        film = {"key": "w:something else", "title": "Heat", "year": 1995}
        result, _query = self.search([film])
        self.assertEqual(result["films"], [])
        result, _query = self.search([film], watched="all")
        self.assertEqual([f["title_id"] for f in result["films"]], [heat["id"]])
