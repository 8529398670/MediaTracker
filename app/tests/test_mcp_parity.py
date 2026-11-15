"""The rule these hold: everything a person can do in the app, an API key can
do over HTTP and an agent can do through /mcp -- except managing API keys, your
own password, PIN and two-factor, other people's files and the owner's screens,
which need a browser session. The API docs say which routes take
a key (their access lets apiKey in); each of those has an MCP tool naming it in
route, or an mcp_http reason for staying HTTP only. Go's twin is
server/routes/mcp_parity_test.go."""
from __future__ import annotations

import json
import re
import unittest
from dataclasses import replace
from typing import Any

from app.apidocs.generate import spec as api_spec
from app.routes.mcp_tools import build_registry
from app.tests.route_support import RoutesTestCase

SESSION_ONLY = "requires a signed-in session"


def operations(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every operation the API docs list, by "METHOD /path"."""
    found = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method.startswith("x-"):
                continue
            security = operation.get("security", [])
            found[f"{method.upper()} {path}"] = {
                "path": path,
                "method": method.upper(),
                "key_ok": any("apiKey" in scheme for scheme in security),
                "public": not security,
                "http_only": operation.get("x-mcp-http", ""),
            }
    return found


class MCPParity(RoutesTestCase):
    """The app with every switch on, so no feature hides behind a 404."""

    config_changes = {
        "mcp_enabled": True,
        "api_keys_enabled": True,
        "invite_links_enabled": True,
        "passwords_enabled": True,
        "two_factor_enabled": True,
    }

    def setUp(self) -> None:
        super().setUp()
        cfg = self.holder.get()

    def test_every_key_route_is_an_mcp_tool(self) -> None:
        spec = operations(api_spec()[0])
        problems, covered = [], set()
        for tool in build_registry().tools():
            operation = spec.get(tool.route_name())
            if not tool.route_name():
                problems.append(f"tool {tool.name} has no route")
            elif operation is None:
                problems.append(f"tool {tool.name} names {tool.route_name()}, which has no API docs")
            elif not operation["key_ok"]:
                problems.append(f"tool {tool.name} names {tool.route_name()}, which an API key may not call")
            elif operation["http_only"]:
                problems.append(f"{tool.route_name()} has a tool ({tool.name}) and an x-mcp-http reason; drop one")
            covered.add(tool.route_name())
        for name, operation in spec.items():
            if operation["key_ok"] and name not in covered and not operation["http_only"]:
                problems.append(f"{name} takes an API key but has no MCP tool: add one in mcp_tools.py, or an mcp_http reason in its @route(...)")
            if not operation["key_ok"] and operation["http_only"]:
                problems.append(f"{name} has an x-mcp-http reason but no key may call it; drop the reason")
        self.assertEqual(sorted(problems), [])

    def test_the_spec_says_who_may_call_each_route(self) -> None:
        """A route listed for API keys is not turned away for being called with
        one, and a session-only route is. With the owner's admin key, so only
        RequireSession and RequireOwner can say no to the key itself."""
        problems = []
        for name, operation in sorted(operations(api_spec()[0]).items()):
            if operation["public"] or operation["path"] in ("/api/logout", "/api/owner/logs/stream"):
                continue
            path = re.sub(r"\{\w+\}", "999", operation["path"])
            status, reply = self.call(operation["method"], path, key=self.admin_key, body={})
            message = reply.get("error", "") if isinstance(reply, dict) else ""
            refused = (status == 403 and SESSION_ONLY in message) or (status == 404 and message == "not_found")
            if operation["key_ok"] and refused:
                problems.append(f"{name}: the API docs let an API key in, but a key is turned away")
            if not operation["key_ok"] and not refused:
                problems.append(f"{name}: the API docs say session only, but a key got {status}")
        self.assertEqual(problems, [])

    def test_the_mcp_manifest_is_for_signed_in_callers(self) -> None:
        self.assertEqual(self.call("GET", "/api/mcp.json")[0], 401)
        status, reply = self.call("GET", "/api/mcp.json", key=self.user_key)
        self.assertEqual((status, reply["endpoint"]), (200, "/mcp"))

    def test_me_says_where_the_mcp_reference_is(self) -> None:
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["mcp_url"], "/api/mcp.json")
        self.set_config(repo="https://github.com/you/app")
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["mcp_url"], "https://github.com/you/app/blob/HEAD/config/mcp.json")

    def test_account_tools(self) -> None:
        def tool(name: str, arguments: dict[str, Any], as_key: str) -> tuple[bool, dict[str, Any]]:
            status, reply = self.call("POST", "/mcp", key=as_key, body={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            self.assertEqual(status, 200, reply)
            result = reply["result"]
            return bool(result.get("isError")), json.loads(result["content"][0]["text"])

        # An admin key makes an account and gets a full address to hand over.
        failed, reply = tool("admin_create_user", {"display_name": "Bob", "role": "user", "max_uses": 2}, self.admin_key)
        self.assertFalse(failed, reply)
        self.assertTrue(reply["login_url"].startswith("http") and "/login/" in reply["login_url"], reply)

        # S9: a key makes itself a login link only once its account allowed it.
        failed, reply = tool("create_my_login_link", {}, self.admin_key)
        self.assertTrue(failed)
        self.assertIn("may not make sign-in links", reply["error"])
        from app.models import api_keys

        api_keys.set_api_key_sign_in(self.store, self.admin_key.split(".", 1)[0], self.owner.id, True)
        failed, reply = tool("create_my_login_link", {}, self.admin_key)
        self.assertFalse(failed, reply)
        self.assertIn("login_url", reply)

        # The owner rules hold through the tools.
        self.assertTrue(tool("admin_set_user_role", {"user_id": self.owner.id, "role": "user"}, self.admin_key)[0])
        self.assertFalse(tool("admin_rename_user", {"user_id": self.user.id, "display_name": "Mem"}, self.admin_key)[0])

        # S1: a non-owner admin's key gets neither the owner nor another admin
        # a login link; the owner's key still may.
        from app.models import api_keys, users

        third = users.create_user(self.store, "Third", users.ROLE_ADMIN)
        other_key, _ = api_keys.issue_api_key(self.store, self.admin.id, "ops", users.ROLE_ADMIN, 3600)
        for name in ("admin_reissue_login", "admin_cancel_login_link"):
            for target in (self.owner.id, third.id):
                with self.subTest(tool=name, target=target):
                    failed, reply = tool(name, {"user_id": target}, other_key)
                    self.assertTrue(failed, reply)
                    self.assertIn("owner", reply["error"])
        failed, reply = tool("admin_reissue_login", {"user_id": third.id}, self.admin_key)
        self.assertFalse(failed, reply)



if __name__ == "__main__":
    unittest.main()
