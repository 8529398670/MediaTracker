"""The rule these hold: everything a person can do in the app, an API key can
do over HTTP and an agent can do through /mcp -- except managing users, keys
and sign-in, which need a browser session. config/openapi.json says which
routes take a key (their security lists apiKey); each of those has an MCP tool
naming it in route, or an "x-mcp-http" reason for staying HTTP only. Go's twin
is server/routes/mcp_parity_test.go."""
from __future__ import annotations

import json
import re
import unittest
from dataclasses import replace
from typing import Any

from app.core import assets
from app.mcp import manifest
from app.routes.mcp_tools import build_registry
from app.tests.route_support import RoutesTestCase

SPEC_PATH = assets.CODE_ROOT / "config" / "openapi.json"
SESSION_ONLY = "requires a signed-in session"


def operations() -> dict[str, dict[str, Any]]:
    """Every operation in config/openapi.json, by "METHOD /path"."""
    if not SPEC_PATH.is_file():
        raise unittest.SkipTest("no config/openapi.json")
    found = {}
    for path, item in json.loads(SPEC_PATH.read_text(encoding="utf-8"))["paths"].items():
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
        spec = operations()
        problems, covered = [], set()
        for tool in build_registry().tools():
            operation = spec.get(tool.route)
            if not tool.route:
                problems.append(f"tool {tool.name} has no route")
            elif operation is None:
                problems.append(f"tool {tool.name} names {tool.route}, which is not in config/openapi.json")
            elif not operation["key_ok"]:
                problems.append(f"tool {tool.name} names {tool.route}, which an API key may not call")
            elif operation["http_only"]:
                problems.append(f"{tool.route} has a tool ({tool.name}) and an x-mcp-http reason; drop one")
            covered.add(tool.route)
        for name, operation in spec.items():
            if operation["key_ok"] and name not in covered and not operation["http_only"]:
                problems.append(f"{name} takes an API key but has no MCP tool: add one in mcp_tools.py, or an x-mcp-http reason in config/openapi.json")
            if not operation["key_ok"] and operation["http_only"]:
                problems.append(f"{name} has an x-mcp-http reason but no key may call it; drop the reason")
        self.assertEqual(sorted(problems), [])

    def test_the_spec_says_who_may_call_each_route(self) -> None:
        """A route listed for API keys is not turned away for being called with
        one, and a session-only route is. With the owner's admin key, so only
        RequireSession and RequireOwner can say no to the key itself."""
        problems = []
        for name, operation in sorted(operations().items()):
            if operation["public"] or operation["path"] in ("/api/logout", "/api/owner/logs/stream"):
                continue
            path = re.sub(r"\{\w+\}", "999", operation["path"])
            status, reply = self.call(operation["method"], path, key=self.admin_key, body={})
            message = reply.get("error", "") if isinstance(reply, dict) else ""
            refused = (status == 403 and SESSION_ONLY in message) or (status == 404 and message == "not_found")
            if operation["key_ok"] and refused:
                problems.append(f"{name}: config/openapi.json lists apiKey, but a key is turned away")
            if not operation["key_ok"] and not refused:
                problems.append(f"{name}: config/openapi.json says session only, but a key got {status}")
        self.assertEqual(problems, [])

    def test_the_mcp_manifest_is_current(self) -> None:
        operations()  # skips without a spec, like the Go test
        want = manifest.build(build_registry(), manifest.spec_or_none())
        have = assets.MCP_MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(have, want, "config/mcp.json is out of date: run scripts/mcp_json.sh")

    def test_the_mcp_manifest_is_for_signed_in_callers(self) -> None:
        self.assertEqual(self.call("GET", "/api/mcp.json")[0], 401)
        status, reply = self.call("GET", "/api/mcp.json", key=self.user_key)
        self.assertEqual((status, reply["endpoint"]), (200, "/mcp"))

    def test_me_says_where_the_mcp_reference_is(self) -> None:
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["mcp_url"], "/api/mcp.json")
        self.set_config(repo="https://github.com/you/app")
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["mcp_url"], "https://github.com/you/app/blob/HEAD/config/mcp.json")



if __name__ == "__main__":
    unittest.main()
