"""The library over HTTP, through the real middleware and route guards: who
may act for whom, what a change sends back for its undo, the 409 that keeps
an undo from overwriting someone else's change, and the admin-only job
controls."""
from __future__ import annotations

import unittest

from app.models import api_keys, user_state, users
from app.tests.asgi import Client


class RouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Client()
        store = self.client.store
        self.admin = users.create_user(store, "Halo", users.ROLE_ADMIN)
        self.mom = users.create_user(store, "Mom", users.ROLE_USER)
        self.admin_key, _ = api_keys.issue_api_key(store, self.admin.id, "t", users.ROLE_ADMIN, 3600)
        self.mom_key, _ = api_keys.issue_api_key(store, self.mom.id, "t", users.ROLE_USER, 3600)
        status, body = self.client.request("POST", "/api/titles", self.mom_key, {"title": {"title": "Heat", "year": 1995}})
        self.assertEqual(status, 201, body)
        self.title_id = body["title"]["id"]

    def tearDown(self) -> None:
        self.client.close()

    def test_library_shows_my_own_state(self) -> None:
        status, body = self.client.request("GET", "/api/library", self.mom_key)
        self.assertEqual(status, 200)
        self.assertEqual(body["states"][self.title_id]["status"], "queue")
        status, body = self.client.request("GET", "/api/library", self.admin_key)
        self.assertEqual(body["states"], {})

    def test_only_an_admin_acts_for_someone_else(self) -> None:
        status, _ = self.client.request("GET", f"/api/library?user={self.admin.id}", self.mom_key)
        self.assertEqual(status, 403)
        status, body = self.client.request("POST", f"/api/state/{self.title_id}?user={self.mom.id}", self.admin_key, {"set": {"status": "watched"}})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["previous"]["status"], "queue")
        status, body = self.client.request("GET", "/api/library", self.mom_key)
        self.assertEqual(body["states"][self.title_id]["status"], "watched")

    def test_a_user_given_showing_acts_for_someone_else(self) -> None:
        store = self.client.store
        path = f"/api/state/{self.title_id}?user={self.admin.id}"
        self.assertEqual(self.client.request("POST", path, self.mom_key, {"set": {"status": "watched"}})[0], 403)
        users.set_showing(store, self.mom.id, True, self.admin.id)
        status, body = self.client.request("POST", path, self.mom_key, {"set": {"status": "watched"}})
        self.assertEqual(status, 200, body)
        status, body = self.client.request("GET", "/api/library", self.admin_key)
        self.assertEqual(body["states"][self.title_id]["status"], "watched")
        self.assertEqual(user_state.get_state(store, self.admin.id, self.title_id)["updated_by"], self.mom.id)
        status, body = self.client.request("GET", "/api/me", self.mom_key)
        self.assertEqual((body["can_show_others"], body["default_subject"]), (True, self.admin.id))

        # Taking it away forgets whose lists they started on, and refuses again.
        users.set_showing(store, self.mom.id, False, self.admin.id)
        self.assertIsNone(users.get_user(store, self.mom.id).default_subject)
        self.assertEqual(self.client.request("GET", f"/api/library?user={self.admin.id}", self.mom_key)[0], 403)
        status, body = self.client.request("GET", "/api/me", self.mom_key)
        self.assertEqual((body["can_show_others"], body["default_subject"]), (False, None))

    def test_undo_with_a_stale_expect_is_a_409(self) -> None:
        self.client.request("POST", f"/api/state/{self.title_id}", self.mom_key, {"set": {"rating": 8}})
        status, body = self.client.request("POST", f"/api/state/{self.title_id}", self.mom_key, {"set": {"rating": None}, "expect": {"rating": 5}})
        self.assertEqual((status, body["error"]), (409, "changed_elsewhere"))

    def test_adding_a_duplicate_answers_409_unless_forced(self) -> None:
        status, body = self.client.request("POST", "/api/titles", self.admin_key, {"title": {"title": "Heat (1995)", "year": 1995}})
        self.assertEqual(status, 409)
        self.assertEqual(body["dupes"][0]["id"], self.title_id)
        status, _ = self.client.request("POST", "/api/titles", self.admin_key, {"title": {"title": "Heat (1995)", "year": 1995}, "force": True})
        self.assertEqual(status, 201)

    def test_since_returns_only_changes(self) -> None:
        _, first = self.client.request("GET", "/api/library", self.mom_key)
        self.client.request("POST", f"/api/state/{self.title_id}", self.mom_key, {"set": {"heart": True}})
        _, delta = self.client.request("GET", f"/api/library?since={first['rev']}", self.mom_key)
        self.assertFalse(delta["full"])
        self.assertEqual(list(delta["states"]), [self.title_id])
        self.assertTrue(delta["states"][self.title_id]["heart"])

    def test_job_controls_are_admin_only(self) -> None:
        status, _ = self.client.request("GET", "/api/jobs", self.mom_key)
        self.assertEqual(status, 200)
        status, _ = self.client.request("POST", "/api/jobs/enrich/start", self.mom_key, {})
        self.assertEqual(status, 403)

    def test_an_unknown_image_key_is_404_not_a_fetch(self) -> None:
        status, _ = self.client.request("GET", "/api/img/" + "0" * 32, self.mom_key)
        self.assertEqual(status, 404)
        status, _ = self.client.request("GET", "/api/img/not-a-key", self.mom_key)
        self.assertEqual(status, 404)

    def test_prefs_and_views_are_mine(self) -> None:
        status, _ = self.client.request("POST", "/api/prefs", self.mom_key, {"cards": {"library": {"layout": "list"}}})
        self.assertEqual(status, 200)
        _, prefs = self.client.request("GET", "/api/prefs", self.mom_key)
        self.assertEqual(prefs["cards"]["library"]["layout"], "list")
        _, other = self.client.request("GET", "/api/prefs", self.admin_key)
        self.assertEqual(other["cards"], {})
        status, view = self.client.request("POST", "/api/views", self.mom_key, {"name": "Short", "screen": "library", "query": "#library/all/queue?runtime=..100"})
        self.assertEqual(status, 201)
        status, _ = self.client.request("POST", f"/api/views/{view['id']}/delete", self.admin_key, {})
        self.assertEqual(status, 404)


    def test_mcp_tools_follow_the_same_rules(self) -> None:
        def call(key: str, name: str, arguments: dict) -> dict:
            status, body = self.client.request("POST", "/mcp", key, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            self.assertEqual(status, 200, body)
            return body["result"]

        found = call(self.mom_key, "search_library", {"text": "heat"})
        self.assertEqual(found["structuredContent"]["titles"][0]["my_state"]["status"], "queue")
        refused = call(self.mom_key, "set_state", {"title_id": self.title_id, "set": {"heart": True}, "user_id": self.admin.id})
        self.assertTrue(refused["isError"])
        done = call(self.admin_key, "set_state", {"title_id": self.title_id, "set": {"heart": True}, "user_id": self.mom.id})
        self.assertFalse(done.get("isError"))
        dupe = call(self.admin_key, "add_title", {"title": "Heat", "year": 1995})
        self.assertFalse(dupe["structuredContent"]["created"])


if __name__ == "__main__":
    unittest.main()
