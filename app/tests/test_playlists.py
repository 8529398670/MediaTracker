"""Playlists: numbered lists that renumber themselves on every add, remove
and move; the list as it was coming back as the undo; titles purged or
merged leaving them consistent; an account taking its playlists with it;
the old hand-made Up next order becoming a playlist, once; and the HTTP and
MCP doors keeping each person to their own."""
from __future__ import annotations

import unittest
from datetime import timedelta

from app.core.db import BUCKET_META, BUCKET_TITLES, BUCKET_USER_STATE
from app.models import api_keys, credentials, merges, playlists, to_iso, user_state, users, utc_now
from app.models import titles as titles_model
from app.models.revision import NotFoundError
from app.tests.asgi import Client
from app.tests.test_library import LibraryTestCase


class PlaylistModelTest(LibraryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ids = [self.add(name)["id"] for name in ("A", "B", "C", "D")]
        self.playlist = playlists.create_playlist(self.store, self.mom.id, "Friday", self.ids[:3])

    def items(self) -> list[str]:
        return playlists.list_playlists(self.store, self.mom.id)[0]["items"]

    def test_a_name_is_needed_and_ids_are_kept_once(self) -> None:
        with self.assertRaises(ValueError):
            playlists.create_playlist(self.store, self.mom.id, "  ")
        twice = playlists.create_playlist(self.store, self.mom.id, "Twice", [self.ids[0], self.ids[0], "not an id"])
        self.assertEqual(twice["items"], [self.ids[0]])

    def test_move_renumbers_and_clamps(self) -> None:
        a, b, c, _d = self.ids
        _record, before = playlists.move_item(self.store, self.mom.id, self.playlist["id"], c, 1)
        self.assertEqual((before, self.items()), ([a, b, c], [c, a, b]))
        playlists.move_item(self.store, self.mom.id, self.playlist["id"], c, 99)
        self.assertEqual(self.items(), [a, b, c])
        playlists.move_item(self.store, self.mom.id, self.playlist["id"], a, 0)
        self.assertEqual(self.items(), [a, b, c])
        playlists.move_item(self.store, self.mom.id, self.playlist["id"], a, 2)
        self.assertEqual(self.items(), [b, a, c])
        with self.assertRaises(NotFoundError):
            playlists.move_item(self.store, self.mom.id, self.playlist["id"], self.ids[3], 1)

    def test_add_remove_and_undo_by_set(self) -> None:
        a, b, c, d = self.ids
        _record, before = playlists.add_items(self.store, self.mom.id, self.playlist["id"], [d, a], 2)
        self.assertEqual(self.items(), [a, d, b, c])
        playlists.remove_items(self.store, self.mom.id, self.playlist["id"], [a, b])
        self.assertEqual(self.items(), [d, c])
        playlists.set_items(self.store, self.mom.id, self.playlist["id"], before)
        self.assertEqual(self.items(), [a, b, c])

    def test_playlists_are_their_owners(self) -> None:
        with self.assertRaises(NotFoundError):
            playlists.add_items(self.store, self.admin.id, self.playlist["id"], [self.ids[3]])
        self.assertEqual(playlists.list_playlists(self.store, self.admin.id), [])

    def test_delete_restore_and_rename(self) -> None:
        _record, old = playlists.rename_playlist(self.store, self.mom.id, self.playlist["id"], "Saturday")
        self.assertEqual(old, "Friday")
        playlists.delete_playlist(self.store, self.mom.id, self.playlist["id"], self.mom.id)
        self.assertEqual(playlists.list_playlists(self.store, self.mom.id), [])
        playlists.restore_playlist(self.store, self.mom.id, self.playlist["id"], self.mom.id, False)
        self.assertEqual(playlists.list_playlists(self.store, self.mom.id)[0]["name"], "Saturday")

    def test_a_purged_title_leaves_every_playlist(self) -> None:
        titles_model.delete_title(self.store, self.ids[1], self.mom.id)
        self.assertEqual(self.items(), self.ids[:3])  # soft-deleted: still in place
        self.store.update_value(BUCKET_TITLES, self.ids[1], lambda record: record.update(deleted_at=to_iso(utc_now() - timedelta(days=31))))
        titles_model.purge_deleted_titles(self.store, 30)
        self.assertEqual(self.items(), [self.ids[0], self.ids[2]])

    def test_merge_puts_the_kept_title_in_place_and_undo_restores(self) -> None:
        a, b, c, _d = self.ids
        result = merges.merge(self.store, c, [a], self.admin.id)
        self.assertEqual(self.items(), [c, b])
        merges.undo_merge(self.store, result["merge_id"])
        self.assertEqual(self.items(), [a, b, c])

    def test_an_account_takes_its_playlists(self) -> None:
        credentials.delete_user(self.store, self.mom.id, self.admin.id)
        self.assertEqual(playlists.list_playlists(self.store, self.mom.id), [])


class MigrationTest(LibraryTestCase):
    def test_old_queue_order_becomes_an_up_next_playlist_once(self) -> None:
        ids = [self.add(name)["id"] for name in ("A", "B", "C")]
        for ident, rank, status in zip(ids, (3.0, 1.0, 2.0), ("queue", "watching", "watched")):
            user_state.set_state(self.store, self.mom.id, ident, {"status": status}, None, self.mom.id)
            self.store.update_value(BUCKET_USER_STATE, user_state.key(self.mom.id, ident), lambda state, rank=rank: state.update(rank=rank))
        self.store.put(BUCKET_META, f"queue_tail:{self.mom.id}", {"rank": 3.0})
        self.assertEqual(playlists.migrate_queue_order(self.store), 1)
        # Watched titles had a rank too, but were not on Up next.
        self.assertEqual([(p["name"], p["items"]) for p in playlists.list_playlists(self.store, self.mom.id)], [("Up next", [ids[1], ids[0]])])
        self.assertNotIn("rank", user_state.get_state(self.store, self.mom.id, ids[0]))
        self.assertIsNone(self.store.get(BUCKET_META, f"queue_tail:{self.mom.id}"))
        self.assertEqual(playlists.migrate_queue_order(self.store), 0)
        self.assertEqual(len(playlists.list_playlists(self.store, self.mom.id)), 1)


class PlaylistRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Client()
        store = self.client.store
        self.admin = users.create_user(store, "Halo", users.ROLE_ADMIN)
        self.mom = users.create_user(store, "Mom", users.ROLE_USER)
        self.admin_key, _ = api_keys.issue_api_key(store, self.admin.id, "t", users.ROLE_ADMIN, 3600)
        self.mom_key, _ = api_keys.issue_api_key(store, self.mom.id, "t", users.ROLE_USER, 3600)
        self.ids = []
        for name in ("Heat", "Alien", "Arrival"):
            status, body = self.client.request("POST", "/api/titles", self.mom_key, {"title": {"title": name}, "force": True})
            self.assertEqual(status, 201, body)
            self.ids.append(body["title"]["id"])

    def tearDown(self) -> None:
        self.client.close()

    def test_numbered_order_over_http(self) -> None:
        status, made = self.client.request("POST", "/api/playlists", self.mom_key, {"name": "Weekend", "items": self.ids})
        self.assertEqual(status, 201, made)
        status, body = self.client.request("POST", f"/api/playlists/{made['id']}/move", self.mom_key, {"title_id": self.ids[2], "position": 1})
        self.assertEqual(status, 200, body)
        self.assertEqual((body["playlist"]["items"], body["previous_items"]), ([self.ids[2], self.ids[0], self.ids[1]], self.ids))
        status, body = self.client.request("POST", f"/api/playlists/{made['id']}/set", self.mom_key, {"items": body["previous_items"]})
        self.assertEqual(body["playlist"]["items"], self.ids)

    def test_only_an_admin_reaches_someone_elses(self) -> None:
        _, made = self.client.request("POST", "/api/playlists", self.mom_key, {"name": "Mine"})
        status, _ = self.client.request("POST", f"/api/playlists/{made['id']}/add", self.admin_key, {"title_ids": self.ids[:1]})
        self.assertEqual(status, 404)
        status, body = self.client.request("POST", f"/api/playlists/{made['id']}/add?user={self.mom.id}", self.admin_key, {"title_ids": self.ids[:1]})
        self.assertEqual((status, body["playlist"]["items"]), (200, self.ids[:1]))
        status, _ = self.client.request("GET", f"/api/playlists?user={self.admin.id}", self.mom_key)
        self.assertEqual(status, 403)

    def test_mcp_playlist_tools(self) -> None:
        def call(name: str, arguments: dict) -> dict:
            status, body = self.client.request("POST", "/mcp", self.mom_key, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            self.assertEqual(status, 200, body)
            return body["result"]

        _, made = self.client.request("POST", "/api/playlists", self.mom_key, {"name": "Weekend", "items": self.ids})
        moved = call("move_in_playlist", {"playlist_id": made["id"], "title_id": self.ids[1], "position": 3})
        self.assertFalse(moved.get("isError"), moved)
        self.assertEqual(moved["structuredContent"]["previous_items"], self.ids)
        got = call("list_playlists", {"playlist_id": made["id"]})["structuredContent"]
        self.assertEqual([(row["number"], row["id"]) for row in got["titles"]], [(1, self.ids[0]), (2, self.ids[2]), (3, self.ids[1])])
        listed = call("list_playlists", {})["structuredContent"]
        self.assertEqual(listed["playlists"], [{"id": made["id"], "name": "Weekend", "count": 3}])


if __name__ == "__main__":
    unittest.main()
