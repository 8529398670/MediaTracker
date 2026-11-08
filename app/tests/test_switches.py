"""What auth.invite_links and webhooks.enabled do while they are off, and that
switching one back on restores what was there."""
from __future__ import annotations

from typing import Any

from app.models import api_keys
from app.models import invite_links
from app.models.users import ROLE_ADMIN
from app.tests.route_support import RoutesTestCase


class InviteLinkSwitch(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.credential, _ = invite_links.issue_invite_link_as(self.store, self.owner.id, "Club", 10, 1)

    def join(self, name: str) -> Any:
        return self.client.post("/api/join/create", json={"credential": self.credential, "display_name": name})

    def test_off_and_back_on(self) -> None:
        csrf = self.csrf(self.user_cookie)
        self.set_config(invite_links_enabled=False)
        for path in ("/api/join/info", "/api/join/match", "/api/join/claim", "/api/join/create"):
            self.assertEqual(self.client.post(path, json={"credential": self.credential}).status_code, 404, path)
        self.assertEqual(self.request("GET", f"/join/{self.credential}").status_code, 404)
        self.assertEqual(self.call("GET", "/api/admin/invite-links", cookie=self.admin_cookie)[0], 404)
        self.assertEqual(self.call("POST", "/api/account/pin", cookie=self.user_cookie, body={"pin": "1234", "csrf_token": csrf})[0], 404)
        self.assertIs(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["invite_links_enabled"], False)

        self.set_config(invite_links_enabled=True)
        self.assertEqual(self.join("Eve").status_code, 201)

    def test_an_old_link_keeps_its_referrer_rule_while_off(self) -> None:
        self.set_config(invite_links_enabled=False)
        response = self.request("GET", f"/join/{self.credential}")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")

    def test_the_tools_follow_the_switch(self) -> None:
        key = api_keys.issue_api_key(self.store, self.owner.id, "admin", ROLE_ADMIN, 3600)[0]
        headers = {"authorization": "Bearer " + key, "accept": "application/json, text/event-stream", "content-type": "application/json"}

        def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
            return self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).json()

        def listed() -> list[str]:
            return [tool["name"] for tool in rpc("tools/list", {})["result"]["tools"]]

        self.assertIn("admin_list_invite_links", listed())
        self.set_config(invite_links_enabled=False)
        self.assertNotIn("admin_list_invite_links", listed())
        self.assertIn("error", rpc("tools/call", {"name": "admin_list_invite_links", "arguments": {}}))


