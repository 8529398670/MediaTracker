"""IMDb's keyless search box as a provider, and what it fixes in the resolver."""
from __future__ import annotations

import unittest
from unittest import mock

from app.providers import compat, resolve, sources

GAL = {"d": [
    {"id": "tt0043873", "l": "Has Anybody Seen My Gal", "y": 1952, "qid": "movie",
     "s": "Piper Laurie, Rock Hudson",
     "i": {"imageUrl": "https://m.media-amazon.com/images/M/gal.jpg"}},
    {"id": "nm0000001", "l": "Someone", "qid": ""},
    {"id": "tt6628326", "l": "Has Anybody Seen My Love", "y": 1985, "qid": "musicVideo"},
    {"id": "tt0000002", "l": "Has Anybody Seen My Show", "y": 1990, "qid": "tvSeries"},
]}


class ProvImdbTest(unittest.TestCase):
    def test_titles_are_kept_and_people_and_music_videos_dropped(self) -> None:
        with mock.patch.object(sources, "fetch_json", return_value=GAL) as fetch:
            rows = sources.prov_imdb("Has Anyone Seen My Gal", "any", 6)
        self.assertIn("/suggestion/h/has%20anyone%20seen%20my%20gal.json", fetch.call_args[0][0])
        self.assertEqual([r["sourceId"] for r in rows], ["tt0043873", "tt0000002"])
        first = rows[0]
        self.assertEqual((first["source"], first["type"], first["year"]), ("imdb", "movie", 1952))
        self.assertEqual(first["imdbId"], "tt0043873")
        self.assertTrue(first["poster"].startswith("https://m.media-amazon.com/"))
        self.assertEqual(first["cast"], ["Piper Laurie", "Rock Hudson"])

    def test_kind_filters_film_from_television(self) -> None:
        with mock.patch.object(sources, "fetch_json", return_value=GAL):
            self.assertEqual([r["type"] for r in sources.prov_imdb("x", "tv", 6)], ["tv"])
            self.assertEqual([r["type"] for r in sources.prov_imdb("x", "movie", 6)], ["movie"])

    def test_nothing_to_ask_asks_nothing(self) -> None:
        with mock.patch.object(sources, "fetch_json") as fetch:
            self.assertEqual(sources.prov_imdb("  ?! ", "any", 6), [])
        fetch.assert_not_called()


class ResolverUsesImdbTest(unittest.TestCase):
    def test_a_word_off_still_finds_the_film_without_a_tmdb_key(self) -> None:
        wrong = [{"source": "wikipedia", "sourceId": "Has_Anyone_Seen_My_Girl",
                  "title": "Has Anyone Seen My Girl?", "year": 2021, "type": "movie"}]
        with mock.patch.object(compat.KEYS, "tmdb", ""), \
             mock.patch.object(sources, "fetch_json", return_value=GAL), \
             mock.patch.object(resolve, "prov_wikipedia", return_value=wrong), \
             mock.patch.object(resolve, "prov_tvmaze", return_value=[]), \
             mock.patch.object(resolve, "wiki_spelling", return_value=""), \
             mock.patch("app.reference.imdb.STORE.get", return_value=(70, 3000)), \
             mock.patch("app.reference.imdb.STORE.folder", "x"):
            rows, _via, _used = resolve.search("Has Anyone Seen My Gal")
        self.assertEqual(rows[0]["sourceId"], "tt0043873")


if __name__ == "__main__":
    unittest.main()
