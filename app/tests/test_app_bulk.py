"""MediaTracker's own bulk routes (bulk=True on its single-thing actions, see
app/apidocs/bulk.py): each item runs through the route's own handler, so one
failing leaves the rest done, and each person still reaches only their own."""
from __future__ import annotations

import unittest

from app.models import api_keys, playlists, users
from app.tests.asgi import Client


class AppBulkRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Client()
        store = self.client.store
        self.admin = users.create_user(store, "Halo", users.ROLE_ADMIN)
        self.mom = users.create_user(store, "Mom", users.ROLE_USER)
        self.mom_key, _ = api_keys.issue_api_key(store, self.mom.id, "t", users.ROLE_USER, 3600)
        self.admin_key, _ = api_keys.issue_api_key(store, self.admin.id, "t", users.ROLE_ADMIN, 3600)
        self.ids = []
        for name in ("Heat", "Alien", "Arrival"):
            status, body = self.client.request("POST", "/api/titles", self.mom_key, {"title": {"title": name}, "force": True})
            self.assertEqual(status, 201, body)
            self.ids.append(body["title"]["id"])

    def tearDown(self) -> None:
        self.client.close()

    def test_bulk_title_update_applies_shared_and_own_fields(self) -> None:
        status, reply = self.client.request("POST", "/api/bulk/titles/update", self.mom_key, {
            "items": [{"title_id": self.ids[0]}, {"title_id": "tt0000000x"}, {"title_id": self.ids[1], "set": {"year": 1979}}],
            "shared": {"set": {"year": 1995}},
        })
        self.assertEqual((status, reply["done"], reply["failed"]), (200, 2, 1), reply)
        self.assertTrue(reply["results"][0]["ok"])
        self.assertFalse(reply["results"][1]["ok"])
        self.assertEqual(reply["results"][0]["reply"]["title"]["year"], 1995)
        self.assertEqual(reply["results"][2]["reply"]["title"]["year"], 1979)

    def test_bulk_playlist_delete_and_restore_keep_to_their_owner(self) -> None:
        made = [self.client.request("POST", "/api/playlists", self.mom_key, {"name": name})[1]["id"] for name in ("A", "B")]
        status, reply = self.client.request("POST", "/api/bulk/playlists/delete", self.mom_key, {
            "items": [{"playlist_id": made[0]}, {"playlist_id": 9999}, {"playlist_id": made[1]}],
        })
        self.assertEqual((status, reply["done"], reply["failed"]), (200, 2, 1), reply)
        self.assertEqual(reply["results"][1]["status"], 404)
        self.assertEqual(playlists.list_playlists(self.client.store, self.mom.id), [])

        # Another account's playlists are not reached, item by item.
        status, reply = self.client.request("POST", "/api/bulk/playlists/restore", self.admin_key, {"items": [{"playlist_id": made[0]}]})
        self.assertEqual((status, reply["failed"]), (200, 1), reply)
        status, reply = self.client.request("POST", "/api/bulk/playlists/restore", self.mom_key, {"items": [{"playlist_id": pid} for pid in made]})
        self.assertEqual((status, reply["done"]), (200, 2), reply)
        self.assertEqual(len(playlists.list_playlists(self.client.store, self.mom.id)), 2)

    def test_bulk_tool_deletes_many_playlists(self) -> None:
        made = [self.client.request("POST", "/api/playlists", self.mom_key, {"name": name})[1]["id"] for name in ("A", "B")]
        status, body = self.client.request("POST", "/mcp", self.mom_key, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "delete_playlist_bulk", "arguments": {"items": [{"playlist_id": pid} for pid in made]}},
        })
        self.assertEqual(status, 200, body)
        self.assertFalse(body["result"].get("isError"), body)
        self.assertEqual(playlists.list_playlists(self.client.store, self.mom.id), [])


if __name__ == "__main__":
    unittest.main()
