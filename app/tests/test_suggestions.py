"""Suggestions: lists like playlists that also hold Discover films, each item
with a note; a library title and its own catalogue film counted as one; an
imported film resolving to its library title; purges, merges and account
deletion keeping them consistent; and the HTTP and MCP doors."""
from __future__ import annotations

import unittest
from datetime import timedelta
from unittest import mock

from app.core.db import BUCKET_TITLES
from app.models import api_keys, credentials, merges, suggestions, to_iso, users, utc_now
from app.models import titles as titles_model
from app.models.revision import NotFoundError
from app.tests.asgi import Client
from app.tests.test_library import LibraryTestCase

FILMS = {
    "w:sicario": {"key": "w:sicario", "article": "Sicario (2015 film)", "title": "Sicario", "year": 2015,
                  "url": "https://en.wikipedia.org/wiki/Sicario_(2015_film)", "imdbScore": [76, 500000]},
    "w:thief": {"key": "w:thief", "article": "Thief (film)", "title": "Thief", "year": 1981,
                "url": "https://en.wikipedia.org/wiki/Thief_(film)", "imdbScore": [73, 40000]},
}


def films_by_keys(keys: object) -> dict:
    return {key: dict(FILMS[key]) for key in (keys or ()) if key in FILMS}


class SuggestionModelTest(LibraryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ids = [self.add(name)["id"] for name in ("A", "B", "C")]
        self.record = suggestions.create_list(self.store, self.mom.id, "For Mom")

    def refs(self) -> list[str]:
        return suggestions.refs(suggestions.list_lists(self.store, self.mom.id)[0])

    def test_mixed_refs_with_notes_kept_once(self) -> None:
        a, b, _c = self.ids
        _record, before = suggestions.add_items(self.store, self.mom.id, self.record["id"], [a, "cat:w:thief", a, "not an id"], "Michael Mann")
        self.assertEqual(before, [])
        self.assertEqual(self.refs(), [a, "cat:w:thief"])
        items = suggestions.list_lists(self.store, self.mom.id)[0]["items"]
        self.assertEqual({item["note"] for item in items}, {"Michael Mann"})
        # Again with a new note: same place, new note.
        suggestions.add_items(self.store, self.mom.id, self.record["id"], [b, a], "again", 1)
        items = suggestions.list_lists(self.store, self.mom.id)[0]["items"]
        self.assertEqual([(item["ref"], item["note"]) for item in items], [(b, "again"), (a, "again"), ("cat:w:thief", "Michael Mann")])

    def test_same_film_counts_once(self) -> None:
        a = self.ids[0]
        suggestions.add_items(self.store, self.mom.id, self.record["id"], ["cat:w:a"])
        suggestions.add_items(self.store, self.mom.id, self.record["id"], [a], same=lambda ref: {"cat:w:a"} if ref == a else set())
        self.assertEqual(self.refs(), ["cat:w:a"])

    def test_move_note_remove_and_undo(self) -> None:
        a, b, c = self.ids
        suggestions.add_items(self.store, self.mom.id, self.record["id"], [a, b, c])
        _record, before = suggestions.move_item(self.store, self.mom.id, self.record["id"], c, 1)
        self.assertEqual(self.refs(), [c, a, b])
        suggestions.set_note(self.store, self.mom.id, self.record["id"], a, "why")
        suggestions.remove_items(self.store, self.mom.id, self.record["id"], [b])
        self.assertEqual(self.refs(), [c, a])
        suggestions.set_items(self.store, self.mom.id, self.record["id"], before)
        self.assertEqual(self.refs(), [a, b, c])
        with self.assertRaises(NotFoundError):
            suggestions.move_item(self.store, self.mom.id, self.record["id"], "cat:nope", 1)
        with self.assertRaises(NotFoundError):
            suggestions.add_items(self.store, self.admin.id, self.record["id"], [a])

    def test_purge_merge_and_account(self) -> None:
        a, b, c = self.ids
        suggestions.add_items(self.store, self.mom.id, self.record["id"], [a, b, c])
        result = merges.merge(self.store, c, [a], self.admin.id)
        self.assertEqual(self.refs(), [c, b])
        merges.undo_merge(self.store, result["merge_id"])
        self.assertEqual(self.refs(), [a, b, c])
        titles_model.delete_title(self.store, b, self.mom.id)
        self.store.update_value(BUCKET_TITLES, b, lambda record: record.update(deleted_at=to_iso(utc_now() - timedelta(days=31))))
        titles_model.purge_deleted_titles(self.store, 30)
        self.assertEqual(self.refs(), [a, c])
        _old = suggestions.rename_list(self.store, self.mom.id, self.record["id"], "Renamed")
        suggestions.delete_list(self.store, self.mom.id, self.record["id"], self.mom.id)
        self.assertEqual(suggestions.list_lists(self.store, self.mom.id), [])
        suggestions.restore_list(self.store, self.mom.id, self.record["id"], self.mom.id, False)
        credentials.delete_user(self.store, self.mom.id, self.admin.id)
        self.assertEqual(suggestions.list_lists(self.store, self.mom.id), [])


@mock.patch("app.discover.catalogue.films_by_keys", films_by_keys)
class SuggestionRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Client()
        store = self.client.store
        self.admin = users.create_user(store, "Halo", users.ROLE_ADMIN)
        self.mom = users.create_user(store, "Mom", users.ROLE_USER)
        self.admin_key, _ = api_keys.issue_api_key(store, self.admin.id, "t", users.ROLE_ADMIN, 3600)
        self.mom_key, _ = api_keys.issue_api_key(store, self.mom.id, "t", users.ROLE_USER, 3600)
        status, body = self.client.request("POST", "/api/titles", self.mom_key, {"title": {"title": "Heat"}, "force": True})
        self.assertEqual(status, 201, body)
        self.heat = body["title"]["id"]
        status, self.made = self.client.request("POST", "/api/suggestions", self.mom_key, {"name": "Like Heat"})
        self.assertEqual(status, 201, self.made)

    def tearDown(self) -> None:
        self.client.close()

    def add(self, body: dict, key: str | None = None, query: str = "") -> tuple[int, dict]:
        return self.client.request("POST", f"/api/suggestions/{self.made['id']}/add{query}", key or self.mom_key, body)

    def test_add_films_and_titles_and_resolve_after_import(self) -> None:
        status, body = self.add({"film_keys": ["w:sicario", "w:thief"], "title_ids": [self.heat], "note": "Mann-ish"})
        self.assertEqual(status, 200, body)
        items = body["suggestion_list"]["items"]
        self.assertEqual([item["ref"] for item in items], ["cat:w:sicario", "cat:w:thief", self.heat])
        self.assertEqual(items[0]["film"]["title"], "Sicario")
        self.assertIsNone(items[0]["title_id"])
        self.assertEqual(items[2]["title_id"], self.heat)
        # Unknown keys and titles are refused.
        self.assertEqual(self.add({"film_keys": ["w:nope"]})[0], 400)
        self.assertEqual(self.add({"title_ids": ["zzzzzzzzzzzz"]})[0], 400)
        # Imported from Discover: the item stays, and is now that title.
        status, added = self.client.request("POST", "/api/discover/add", self.mom_key, {"film": FILMS["w:thief"], "force": True})
        self.assertEqual(status, 201, added)
        status, lists = self.client.request("GET", "/api/suggestions", self.mom_key)
        thief = lists[0]["items"][1]
        self.assertEqual((thief["ref"], thief["title_id"]), ("cat:w:thief", added["title"]["id"]))
        # Adding that title now is the same film: no second item.
        status, body = self.add({"title_ids": [added["title"]["id"]], "note": "new note"})
        self.assertEqual(len(body["suggestion_list"]["items"]), 3)
        self.assertEqual(body["suggestion_list"]["items"][1]["note"], "new note")

    def test_only_an_admin_reaches_someone_elses(self) -> None:
        self.assertEqual(self.add({"film_keys": ["w:thief"]}, self.admin_key)[0], 404)
        status, body = self.add({"film_keys": ["w:thief"]}, self.admin_key, f"?user={self.mom.id}")
        self.assertEqual(status, 200, body)
        status, _ = self.client.request("GET", f"/api/suggestions?user={self.admin.id}", self.mom_key)
        self.assertEqual(status, 403)

    def test_mcp_tools(self) -> None:
        def call(name: str, arguments: dict) -> dict:
            status, body = self.client.request("POST", "/mcp", self.mom_key, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            self.assertEqual(status, 200, body)
            self.assertFalse(body["result"].get("isError"), body)
            return body["result"]["structuredContent"]

        call("add_suggestions", {"list_id": self.made["id"], "film_keys": ["w:sicario"], "note": "Villeneuve"})
        got = call("list_suggestions", {"list_id": self.made["id"]})
        self.assertEqual(got["items"][0]["title"], "Sicario")
        self.assertEqual((got["items"][0]["note"], got["items"][0]["imdb_score"], got["items"][0]["in_library"]), ("Villeneuve", 7.6, False))
        self.assertEqual(call("list_suggestions", {})["lists"], [{"id": self.made["id"], "name": "Like Heat", "count": 1}])


if __name__ == "__main__":
    unittest.main()
