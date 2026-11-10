"""The library tools /mcp offers beside the HTTP routes they stand for: a
sample of them doing what the route does, refusing in the route's words,
keeping a user-scoped key away from the admin-only job tools, and keeping
each person to their own lists unless they may act for others."""
from __future__ import annotations

import unittest
from typing import Any

from app.models import api_keys, users
from app.tests.asgi import Client


class MCPLibraryToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Client()
        store = self.client.store
        self.admin = users.create_user(store, "Halo", users.ROLE_ADMIN)
        self.mom = users.create_user(store, "Mom", users.ROLE_USER)
        self.admin_key, _ = api_keys.issue_api_key(store, self.admin.id, "t", users.ROLE_ADMIN, 3600)
        self.mom_key, _ = api_keys.issue_api_key(store, self.mom.id, "t", users.ROLE_USER, 3600)

    def tearDown(self) -> None:
        self.client.close()

    def rpc(self, key: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        status, body = self.client.request("POST", "/mcp", key, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        self.assertEqual(status, 200, body)
        return body

    def call(self, name: str, arguments: dict[str, Any], key: str = "") -> dict[str, Any]:
        """The tool's structuredContent; it must not be an error."""
        result = self.rpc(key or self.mom_key, "tools/call", {"name": name, "arguments": arguments})["result"]
        self.assertFalse(result.get("isError"), result)
        return result["structuredContent"]

    def refused(self, name: str, arguments: dict[str, Any], key: str = "") -> str:
        result = self.rpc(key or self.mom_key, "tools/call", {"name": name, "arguments": arguments})["result"]
        self.assertTrue(result.get("isError"), result)
        return result["structuredContent"]["error"]

    def test_a_title_through_its_tools(self) -> None:
        made = self.call("add_title", {"title": "Heat", "year": 1995})
        title_id = made["title"]["id"]
        self.assertEqual(self.call("check_title", {"title": "Heat", "year": 1995})["matches"][0]["id"], title_id)
        changed = self.call("update_title", {"title_id": title_id, "set": {"notes": "Mann"}})
        self.assertEqual(changed["title"]["notes"], "Mann")
        tagged = self.call("bulk_edit_titles", {"ids": [title_id], "op": "add_tags", "value": ["crime"]})
        self.assertIn(title_id, tagged["previous"])
        self.assertEqual(self.call("get_title", {"title_id": title_id})["tags"], ["crime"])
        self.call("delete_title", {"title_id": title_id})
        self.assertEqual(self.refused("get_title", {"title_id": title_id}), "no such title")
        status, _ = self.client.request("GET", f"/api/titles/{title_id}", self.mom_key)
        self.assertEqual(status, 200)  # the route still shows a deleted title, for its restore
        self.call("restore_title", {"title_id": title_id})
        self.assertEqual(self.call("search_library", {"status": "up_next"})["titles"][0]["id"], title_id)
        self.assertEqual(self.refused("update_title", {"title_id": "0" * 32, "set": {"notes": "x"}}), "no such title")

    def test_bulk_state_and_refusals_in_the_routes_words(self) -> None:
        title_id = self.call("add_title", {"title": "Alien"})["title"]["id"]
        done = self.call("set_states", {"changes": {title_id: {"status": "watched", "rating": 9}}})
        self.assertEqual(done["previous"][title_id]["status"], "queue")
        self.assertEqual(self.refused("set_states", {"changes": {}}), "no changes given")
        # Lookups are off in the test config: refused as the route does (503), not an internal error.
        self.assertEqual(self.refused("lookup", {"text": "Heat 1995"}), "lookups_off")
        self.assertEqual(self.refused("enrich_title", {"title_id": title_id}), "lookups_off")

    def test_playlists_views_and_sources(self) -> None:
        ids = [self.call("add_title", {"title": name, "force": True})["title"]["id"] for name in ("Heat", "Alien", "Arrival")]
        playlist = self.call("create_playlist", {"name": "Weekend", "items": ids[:2]})
        added = self.call("add_to_playlist", {"playlist_id": playlist["id"], "title_ids": [ids[2]], "position": 1})
        self.assertEqual((added["playlist"]["items"], added["previous_items"]), ([ids[2], *ids[:2]], ids[:2]))
        removed = self.call("remove_from_playlist", {"playlist_id": playlist["id"], "title_ids": [ids[0]]})
        self.assertEqual(removed["playlist"]["items"], [ids[2], ids[1]])
        self.call("set_playlist_items", {"playlist_id": playlist["id"], "items": added["previous_items"]})
        self.assertEqual([row["id"] for row in self.call("list_playlists", {"playlist_id": playlist["id"]})["titles"]], ids[:2])

        view = self.call("create_view", {"name": "Short", "query": "#library/all/queue?runtime=..100"})
        self.assertEqual(self.call("update_view", {"view_id": view["id"], "name": "Shorts"})["view"]["name"], "Shorts")
        self.call("delete_view", {"view_id": view["id"]})
        self.assertEqual(self.call("list_views", {})["views"], [])

        source = self.call("create_source", {"url": "https://example.com/list", "title": "A list"})
        self.call("delete_source", {"source_id": source["id"]})
        self.assertEqual(self.call("list_sources", {})["sources"], [])
        self.call("restore_source", {"source_id": source["id"]})
        self.assertEqual([row["id"] for row in self.call("list_sources", {})["sources"]], [source["id"]])

        self.call("save_type", {"id": "radio", "label": "Radio"})
        self.call("add_title", {"title": "The War of the Worlds", "type": "radio"})
        self.assertIn("type_in_use", self.refused("delete_type", {"type_id": "radio"}))

    def test_someone_elses_lists_need_showing(self) -> None:
        self.assertEqual(
            self.refused("create_playlist", {"name": "Not mine", "user_id": self.admin.id}),
            "only an admin, or someone given Showing, can act for someone else",
        )
        self.assertEqual(self.refused("save_prefs", {"ui": {"dense": True}, "user_id": self.admin.id}), "only an admin, or someone given Showing, can act for someone else")
        made = self.call("create_playlist", {"name": "For Mom", "user_id": self.mom.id}, key=self.admin_key)
        self.assertEqual([row["id"] for row in self.call("list_playlists", {})["playlists"]], [made["id"]])

    def test_job_controls_are_for_admin_keys_only(self) -> None:
        listed = {tool["name"] for tool in self.rpc(self.mom_key, "tools/list", {})["result"]["tools"]}
        self.assertIn("jobs_status", listed)
        self.assertFalse({"admin_start_job", "admin_stop_job"} & listed)
        body = self.rpc(self.mom_key, "tools/call", {"name": "admin_stop_job", "arguments": {"name": "enrich"}})
        self.assertEqual(body["error"]["message"], "unknown tool: admin_stop_job")
        self.assertEqual(self.refused("admin_stop_job", {"name": "no-such-job"}, key=self.admin_key), "no such job")
        self.assertIn("network", self.call("jobs_status", {}))


if __name__ == "__main__":
    unittest.main()
