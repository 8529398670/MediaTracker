"""Bulk routes (bulk=True, see app/apidocs/bulk.py): each item runs through
the route's own handler, so its rules and words are the route's, item by item.
Go's twins are server/routes/bulk_test.go and bulk_mcp_test.go."""
from __future__ import annotations

import json
import unittest
from typing import Any

from app.models import users
from app.tests.route_support import RoutesTestCase

PATH = "/api/bulk/admin/users/disabled"


class BulkRouteTest(RoutesTestCase):
    def send(self, cookie: str, body: dict[str, Any]) -> tuple[int, Any]:
        return self.call("POST", PATH, cookie=cookie, body={**body, "csrf_token": self.csrf(cookie)})

    def test_a_bulk_route_runs_each_item(self) -> None:
        bob = users.create_user(self.store, "Bob", users.ROLE_USER)
        # shared gives every item disabled; one item's own value wins; a
        # missing account and your own fail with the single route's words,
        # the rest go on.
        status, reply = self.send(self.owner_cookie, {
            "items": [{"user_id": self.user.id}, {"user_id": 9999}, {"user_id": self.owner.id}, {"user_id": bob.id, "disabled": False}],
            "shared": {"disabled": True},
        })
        self.assertEqual((status, reply["done"], reply["failed"]), (200, 2, 2), reply)
        results = reply["results"]
        self.assertEqual(results[0], {"index": 0, "ok": True, "reply": {"ok": True}})
        self.assertEqual((results[1]["status"], results[1]["error"]), (404, "no such user"))
        self.assertEqual((results[2]["status"], results[2]["error"]), (400, "you cannot disable your own account"))
        self.assertEqual((results[3]["ok"], results[3]["index"]), (True, 3))
        self.assertTrue(users.get_user(self.store, self.user.id).disabled)
        self.assertFalse(users.get_user(self.store, bob.id).disabled)

        # An item the route would refuse as it stands fails alone.
        status, reply = self.send(self.owner_cookie, {"items": [{"user_id": self.user.id}, {"user_id": bob.id, "disabled": "yes"}], "shared": {"disabled": False}})
        self.assertEqual((status, reply["results"][0]["ok"], reply["results"][1]["status"]), (200, True, 400), reply)

    def test_a_bulk_request_is_checked_as_a_whole(self) -> None:
        too_many = [{"user_id": self.user.id}] * 101
        for body, want in (
            ({}, "items is required"),
            ({"items": []}, "items must hold 1 to 100 entries"),
            ({"items": too_many}, "items must hold 1 to 100 entries"),
            ({"items": [3]}, "malformed request body"),
            ({"items": [{"user_id": 3}], "extra": 1}, "unknown field: extra"),
            ({"items": [{"user_id": 3}], "shared": {"user_id": 3}}, "unknown field: shared.user_id"),
        ):
            self.assertEqual(self.send(self.owner_cookie, body), (400, {"error": want}), body)
        # The route's guards hold: no csrf token, or not an admin.
        self.assertEqual(self.call("POST", PATH, cookie=self.owner_cookie, body={"items": [{"user_id": self.user.id}]})[0], 403)
        self.assertEqual(self.send(self.user_cookie, {"items": [{"user_id": self.owner.id}]})[0], 403)


class BulkToolTest(RoutesTestCase):
    config_changes = {"mcp_enabled": True}

    def tool(self, key: str, name: str, arguments: Any) -> dict[str, Any]:
        status, reply = self.call("POST", "/mcp", key=key, body={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        self.assertEqual(status, 200, reply)
        return reply

    def test_a_bulk_tool_runs_each_item(self) -> None:
        reply = self.tool(self.admin_key, "admin_set_user_disabled_bulk", {"items": [{"user_id": self.user.id}, {"user_id": 9999}], "shared": {"disabled": True}})
        result = reply["result"]
        self.assertFalse(result.get("isError"), result)
        answer = json.loads(result["content"][0]["text"])
        self.assertEqual((answer["done"], answer["failed"]), (1, 1))
        self.assertTrue(users.get_user(self.store, self.user.id).disabled)

        # A shape the tool cannot take is invalid arguments; a count out of
        # bounds is a refusal in the route's words.
        reply = self.tool(self.admin_key, "admin_set_user_disabled_bulk", {"items": [{"user_id": 1}], "other": 1})
        self.assertEqual(reply["error"]["code"], -32602)
        result = self.tool(self.admin_key, "admin_set_user_disabled_bulk", {"items": []})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("items must hold 1 to 100 entries", result["content"][0]["text"])

        # A user-scoped key is not told the admin bulk tool exists.
        status, reply = self.call("POST", "/mcp", key=self.user_key, body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertNotIn("admin_set_user_disabled_bulk", [tool["name"] for tool in reply["result"]["tools"]])


if __name__ == "__main__":
    unittest.main()
