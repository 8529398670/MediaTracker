"""A rate-limited Wikidata ends the Apple TV lookup early with what it got,
instead of failing the job; the ids it never asked about stay askable."""
from __future__ import annotations

import unittest
import urllib.error
from unittest import mock

from app.providers import appletv

MOVIE = "umc.cmc.abcdefghij1234"


def throttled() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(appletv.SPARQL, 429, "Aggressively rate-limiting to 1 req / min", {}, None)  # type: ignore[arg-type]


def answer(imdb: str) -> dict:
    return {"results": {"bindings": [{"imdb": {"value": imdb}, "movie": {"value": MOVIE}}]}}


class LookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = [f"tt{n:07d}" for n in range(appletv.BATCH + 10)]

    def test_throttle_without_pause_stops_and_keeps_partial_results(self) -> None:
        replies = [answer(self.ids[0]), throttled()]
        with mock.patch.object(appletv.net, "fetch_json", side_effect=replies):
            result = appletv.lookup(self.ids)
        self.assertTrue(result.throttled)
        self.assertEqual(result.found, {self.ids[0]: f"movie/{MOVIE}"})
        self.assertEqual(result.answered, set(self.ids[: appletv.BATCH]))

    def test_pause_then_retry_finishes_the_batch(self) -> None:
        pauses: list[float] = []
        replies = [throttled(), answer(self.ids[0]), answer(self.ids[-1])]
        with mock.patch.object(appletv.net, "fetch_json", side_effect=replies):
            result = appletv.lookup(self.ids, pause=lambda s: pauses.append(s) or True)
        self.assertFalse(result.throttled)
        self.assertEqual(pauses, [appletv.THROTTLE_WAIT])
        self.assertEqual(result.answered, set(self.ids))
        self.assertEqual(len(result.found), 2)

    def test_still_throttled_after_the_pause_gives_up(self) -> None:
        with mock.patch.object(appletv.net, "fetch_json", side_effect=[throttled(), throttled()]):
            result = appletv.lookup(self.ids, pause=lambda s: True)
        self.assertTrue(result.throttled)
        self.assertEqual(result.answered, set())

    def test_other_errors_still_raise(self) -> None:
        error = urllib.error.HTTPError(appletv.SPARQL, 400, "bad query", {}, None)  # type: ignore[arg-type]
        with mock.patch.object(appletv.net, "fetch_json", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                appletv.lookup(self.ids)


if __name__ == "__main__":
    unittest.main()
