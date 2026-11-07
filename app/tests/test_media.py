"""The pure media rules: one genre vocabulary, the shape every title and
state is cleaned to, what counts as a duplicate, and lists in and out."""
from __future__ import annotations

import json
import unittest

from app.media import dupes, genres, normalize, porting


class GenreTest(unittest.TestCase):
    def test_provider_spellings_fold_onto_one_vocabulary(self) -> None:
        self.assertEqual(genres.canon_genre("science fiction film"), ["Science Fiction"])
        self.assertEqual(genres.canon_genre("Sci-Fi & Fantasy"), ["Science Fiction", "Fantasy"])
        self.assertEqual(genres.canon_genre("adventure fiction"), ["Adventure"])
        self.assertEqual(genres.canon_genre("film"), [])

    def test_lists_are_deduplicated_and_capped(self) -> None:
        self.assertEqual(genres.canon_genres(["Drama", "drama", "Romantic comedy"], limit=6), ["Drama", "Romance", "Comedy"])
        self.assertEqual(len(genres.canon_genres([f"genre {n}" for n in range(20)], limit=6)), 6)


class NormalizeTest(unittest.TestCase):
    def test_unknown_fields_are_dropped_and_known_ones_clamped(self) -> None:
        clean = normalize.clean_title_fields({"title": "  Sunrise ", "year": "1927", "added_at": "x", "rev": 99, "imdb_id": "nope", "tags": ["#Pre Code", "pre-code"]})
        self.assertEqual(clean["title"], "Sunrise")
        self.assertEqual(clean["year"], 1927)
        self.assertEqual(clean["imdb_id"], "")
        self.assertEqual(clean["tags"], ["pre-code"])
        self.assertNotIn("added_at", clean)
        self.assertNotIn("rev", clean)

    def test_links_keep_only_web_addresses(self) -> None:
        links = normalize.links(["https://example.com/a", {"label": "x", "url": "javascript:alert(1)"}, {"url": "ftp://x"}])
        self.assertEqual(links, [{"label": "", "url": "https://example.com/a"}])

    def test_state_fields(self) -> None:
        self.assertEqual(normalize.clean_state_fields({"status": "watched", "rating": 11, "heart": 1}), {"status": "watched", "rating": None, "heart": True})
        self.assertEqual(normalize.clean_state_fields({"status": "binged"}), {"status": None})


class DupesTest(unittest.TestCase):
    def test_same_ids_are_certain_and_different_ids_are_not(self) -> None:
        self.assertEqual(dupes.similarity({"title": "A", "imdb_id": "tt1"}, {"title": "B", "imdb_id": "tt1"})[0], dupes.CERTAIN)
        self.assertEqual(dupes.similarity({"title": "A", "imdb_id": "tt1"}, {"title": "A", "imdb_id": "tt2"})[0], 0)

    def test_subtitles_numbers_and_remakes(self) -> None:
        sunrise = {"title": "Sunrise: A Song of Two Humans", "year": 1927}
        self.assertEqual(dupes.similarity({"title": "Sunrise", "year": 1927}, sunrise)[0], dupes.LIKELY)
        self.assertEqual(dupes.similarity({"title": "Rocky II", "year": 1979}, {"title": "Rocky III", "year": 1979})[0], 0)
        self.assertEqual(dupes.similarity({"title": "The Godfather Part 2", "year": 1974}, {"title": "The Godfather Part II", "year": 1974})[0], dupes.CERTAIN)
        self.assertEqual(dupes.similarity({"title": "Little Women", "year": 1994}, {"title": "Little Women", "year": 2019})[0], dupes.REMAKE)

    def test_groups_respect_dismissals(self) -> None:
        titles = [{"id": "a", "title": "Heat", "year": 1995}, {"id": "b", "title": "Heat (1995)", "year": 1995}, {"id": "c", "title": "Alien", "year": 1979}]
        self.assertEqual([sorted(group["ids"]) for group in dupes.duplicate_groups(titles, set())], [["a", "b"]])
        self.assertEqual(dupes.duplicate_groups(titles, {dupes.pair_key("a", "b")}), [])

    def test_merged_state_takes_the_furthest_status(self) -> None:
        merged = dupes.merged_state([
            {"status": "queue", "rating": None, "heart": False, "watched_at": None, "note": ""},
            {"status": "watched", "rating": 7, "heart": True, "watched_at": "2026-01-01", "note": "great"},
        ])
        self.assertEqual((merged["status"], merged["rating"], merged["heart"]), ("watched", 7, True))


class PortingTest(unittest.TestCase):
    def test_outline_headings_set_status_and_type(self) -> None:
        parsed = porting.parse("# Watched\n- Sunrise (1927)\n# TV shows\n- Fleabag\n")
        rows = {row["fields"]["title"]: row for row in parsed["rows"]}
        self.assertEqual(rows["Sunrise"]["state"]["status"], "watched")
        self.assertEqual(rows["Sunrise"]["fields"]["year"], 1927)
        self.assertEqual(rows["Fleabag"]["fields"]["type"], "tv")

    def test_csv_and_json_round_trip(self) -> None:
        titles = [{"id": "x1", "title": "Heat", "year": 1995, "type": "movie", "tags": ["crime"], "genres": ["Crime"]}]
        states = {"x1": {"status": "watched", "rating": 9, "heart": True}}
        for fmt in ("csv", "json"):
            body, _kind, _ext = porting.export(titles, states, [{"id": "movie", "label": "Movies"}], fmt, "halo")
            rows = porting.parse(body.decode("utf-8"), fmt)["rows"]
            self.assertEqual(rows[0]["fields"]["title"], "Heat")
            self.assertEqual(rows[0]["state"]["rating"], 9, fmt)
            self.assertTrue(rows[0]["state"]["heart"], fmt)

    def test_markdown_export_reads_as_a_list(self) -> None:
        body, _kind, _ext = porting.export([{"id": "x", "title": "Heat", "year": 1995, "type": "movie"}], {"x": {"status": "queue"}}, [{"id": "movie", "label": "Movies"}], "md", "halo")
        self.assertIn("## Movies", body.decode())
        self.assertIn("- Heat (1995)", body.decode())


if __name__ == "__main__":
    unittest.main()
