"""server.maintenance: what each mode leaves open, that only the owner's
browser session gets past it, and that switching it needs no restart."""
from __future__ import annotations

import unittest

from app.core.maintenance import allows
from app.tests.route_support import RoutesTestCase

NONE, READ_ONLY, FULL = "none", "read_only", "full"


class AllowsTest(unittest.TestCase):
    def test_what_each_mode_leaves_open(self) -> None:
        cases = [
            (NONE, "POST", "/api/admin/users", True),
            (READ_ONLY, "GET", "/", True),
            (READ_ONLY, "GET", "/api/team", True),
            (READ_ONLY, "POST", "/api/account/rename", False),
            (READ_ONLY, "POST", "/mcp", False),
            (READ_ONLY, "POST", "/api/logs/events", False),
            (READ_ONLY, "GET", "/join/abc", False),
            (READ_ONLY, "POST", "/api/join/create", False),
            (READ_ONLY, "POST", "/api/logout", True),
            (READ_ONLY, "POST", "/api/login", True),
            (FULL, "GET", "/", False),
            (FULL, "GET", "/index.html", False),
            (FULL, "GET", "/api/team", False),
            (FULL, "GET", "/join/abc", False),
            (FULL, "POST", "/mcp", False),
            (FULL, "GET", "/js/app.js", True),
            (FULL, "GET", "/api/health", True),
            (FULL, "GET", "/api/ready", True),
            (FULL, "GET", "/api/language", True),
            (FULL, "GET", "/api/me", True),
            (FULL, "GET", "/login/abc.def", True),
            (FULL, "POST", "/api/login/two-factor", True),
            # A spelling must not open anything, or pass for a file.
            (FULL, "GET", "/API/TEAM/", False),
            (FULL, "GET", "/API/ADMIN/USERS.JS", False),
            (READ_ONLY, "POST", "/API/JOIN/CREATE/", False),
            (READ_ONLY, "GET", "/JOIN/abc", False),
            (FULL, "GET", "/INDEX.HTML", False),
        ]
        for mode, method, path, allowed in cases:
            with self.subTest(f"{mode} {method} {path}"):
                self.assertEqual(allows(mode, method, path), allowed)


class MaintenanceRoutesTest(RoutesTestCase):
    def test_full_leaves_only_the_owners_session(self) -> None:
        self.set_config(maintenance=FULL)
        self.assertEqual(self.call("GET", "/api/team", cookie=self.owner_cookie)[0], 200)
        status, reply = self.call("GET", "/api/team", cookie=self.user_cookie)
        self.assertEqual((status, reply["maintenance"]), (503, FULL))
        # The owner's key is not the owner's session.
        response = self.request("GET", "/api/team", key=self.admin_key)
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.headers["retry-after"])
        # Still able to find out why.
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["maintenance"], FULL)

    def test_read_only_refuses_writes_but_not_reads(self) -> None:
        csrf = self.csrf(self.user_cookie)
        owner_csrf = self.csrf(self.owner_cookie)
        self.set_config(maintenance=READ_ONLY)
        self.assertEqual(self.call("GET", "/api/team", cookie=self.user_cookie)[0], 200)
        status, _ = self.call("POST", "/api/account/rename", cookie=self.user_cookie, body={"csrf_token": csrf, "display_name": "Al"})
        self.assertEqual(status, 503)
        status, _ = self.call("POST", "/api/account/rename", cookie=self.owner_cookie, body={"csrf_token": owner_csrf, "display_name": "Boss"})
        self.assertEqual(status, 200)

    def test_it_applies_without_a_restart(self) -> None:
        for mode, status in ((NONE, 200), (FULL, 503), (NONE, 200)):
            self.set_config(maintenance=mode)
            self.assertEqual(self.call("GET", "/api/team", cookie=self.user_cookie)[0], status)

    def test_a_browser_gets_the_page_not_json(self) -> None:
        self.set_config(maintenance=FULL)
        response = self.client.get("/", headers={"accept": "text/html"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Down for maintenance", response.text)
        self.assertTrue(response.headers["retry-after"])


if __name__ == "__main__":
    unittest.main()
