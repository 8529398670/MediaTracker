"""A declared route checks its request against its type before the handler
runs (see app/apidocs/route.py). Each fault answers the same 400 whichever
route it is, and the Go template answers the same words. Go's twin is
server/routes/typed_routes_test.go."""
from __future__ import annotations

import json
import unittest
from typing import Any

from app.core.error_codes import ERROR_CODES
from app.tests.route_support import RoutesTestCase

LINK_LIMITS = "max_uses must be 0 (unlimited) or 1-1000, expires_in_minutes 0 (never) or 1-525600"


def plain(result: Any) -> Any:
    """A refusal as these tests read it: the status and the sentence. Its code
    (and field) are checked here to be listed, and in test_error_codes.py to
    be the right one."""
    if isinstance(result, dict):
        assert result.get("code") in ERROR_CODES, result
        return {"error": result["error"]}
    status, reply = result
    assert reply.get("code") in ERROR_CODES, reply
    return status, {"error": reply["error"]}


class DeclaredRoutesTest(RoutesTestCase):
    def send(self, path: str, **body: Any) -> tuple[int, Any]:
        return self.call("POST", path, cookie=self.owner_cookie, body={**body, "csrf_token": self.csrf(self.owner_cookie)})

    def test_a_declared_route_checks_its_body(self) -> None:
        cases = [
            ("a missing field", {"role": "user"}, "display name must be 1-80 characters"),
            ("another missing field", {"display_name": "Bea"}, "role must be admin, user or viewer"),
            ("a wrong type", {"display_name": 5, "role": "user"}, "malformed request body"),
            ("a value not in the enum", {"display_name": "Bea", "role": "boss"}, "role must be admin, user or viewer"),
            ("too long", {"display_name": "x" * 81, "role": "user"}, "display name must be 1-80 characters"),
            ("out of range", {"display_name": "Bea", "role": "user", "max_uses": 5000}, LINK_LIMITS),
            ("below range", {"display_name": "Bea", "role": "user", "expires_in_minutes": -1}, LINK_LIMITS),
            ("an unknown field", {"display_name": "Bea", "role": "user", "colour": "red"}, "unknown field: colour"),
        ]
        for name, body, message in cases:
            with self.subTest(name):
                self.assertEqual(plain(self.send("/api/admin/users", **body)), (400, {"error": message}))
        status, _ = self.send("/api/admin/users", display_name="Bea", role="user", max_uses=None)
        self.assertEqual(status, 201, "a null optional field")

    def test_a_declared_route_checks_its_url(self) -> None:
        cases = [
            ("/api/admin/users?limit=0", "limit must be 1-1000"),
            ("/api/admin/users?limit=lots", "limit must be 1-1000"),
            ("/api/admin/users?offset=-1", "offset must be 0 or more"),
            ("/api/admin/users?dir=up", "dir must be asc or desc"),
            ("/api/admin/users?sort=shoe_size", "sort must be one of: display_name, role, disabled, created_at"),
        ]
        for path, message in cases:
            with self.subTest(path):
                self.assertEqual(plain(self.call("GET", path, cookie=self.owner_cookie)), (400, {"error": message}))
        self.assertEqual(plain(self.send("/api/admin/users/abc/rename", display_name="Bea")), (400, {"error": "invalid user id"}))

    def test_a_declared_route_checks_the_sessions_csrf_token(self) -> None:
        status, reply = self.call("POST", "/api/admin/users", cookie=self.owner_cookie, body={"display_name": "Bea", "role": "user"})
        self.assertEqual(plain((status, reply)), (403, {"error": "invalid csrf token"}))
        # The token is checked before the body, as before.
        self.assertEqual(self.call("POST", "/api/admin/users", cookie=self.owner_cookie, body={"colour": "red"})[0], 403)

    def test_an_optional_number_in_the_query(self) -> None:
        path = "/api/owner/logs/days/2020-01-02"
        self.assertEqual(plain(self.call("GET", path + "?before=-1", cookie=self.owner_cookie)), (400, {"error": "before must be a line number"}))
        self.assertEqual(plain(self.call("GET", path + "?before=lots", cookie=self.owner_cookie)), (400, {"error": "before must be a line number"}))
        self.assertEqual(self.call("GET", path + "?before=3", cookie=self.owner_cookie)[0], 200)
        self.assertEqual(self.call("GET", path, cookie=self.owner_cookie)[0], 200)


class ToolArgumentsTest(RoutesTestCase):
    config_changes = {"mcp_enabled": True}

    def tool(self, name: str, arguments: Any) -> dict[str, Any]:
        status, reply = self.call("POST", "/mcp", key=self.admin_key, body={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        self.assertEqual(status, 200, reply)
        return reply

    def failed(self, reply: dict[str, Any]) -> str:
        result = reply.get("result", {})
        return json.loads(result["content"][0]["text"]).get("error", "") if result.get("isError") else ""

    def test_a_tool_checks_its_arguments_like_its_route(self) -> None:
        self.assertIn(LINK_LIMITS, self.failed(self.tool("admin_create_user", {"display_name": "Bea", "role": "user", "max_uses": 5000})))
        self.assertIn("display name must be 1-80 characters", self.failed(self.tool("admin_create_user", {"role": "user"})))
        self.assertIn("error", self.tool("admin_create_user", {"display_name": 5, "role": "user"}))
        self.assertIn("sort must be one of", self.failed(self.tool("admin_list_users", {"sort": "shoe_size"})))
        self.assertEqual(self.failed(self.tool("admin_list_users", {"sort": "display_name", "dir": "desc", "q": "use"})), "")


if __name__ == "__main__":
    unittest.main()
