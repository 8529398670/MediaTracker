"""The shape every list route and paged MCP tool shares."""
from __future__ import annotations

import unittest
from datetime import timedelta
from typing import Any

from app.core.db import BUCKET_API_KEYS
from app.models import users
from app.models import api_keys, to_iso, utc_now
from app.routes.helpers import match_rows, page_body, sort_rows
from app.tests.route_support import RoutesTestCase


class PageBodyTests(unittest.TestCase):
    def test_cuts_and_points_at_the_next_page(self) -> None:
        rows = [1, 2, 3, 4, 5]
        for limit, offset, count, following in [(2, 0, 2, 2), (2, 2, 2, 4), (2, 4, 1, None), (5, 0, 5, None), (2, 99, 0, None)]:
            body = page_body("rows", rows, limit, offset)
            self.assertEqual(len(body["rows"]), count, (limit, offset))
            self.assertEqual(body["next"], following, (limit, offset))
            self.assertEqual(body["total"], 5)


class MatchRowsTests(unittest.TestCase):
    def test_looks_in_the_named_fields_only(self) -> None:
        rows = [
            {"id": 1, "name": "Team Chat", "url": "https://a.example", "note": "zebra"},
            {"id": 2, "name": "alerts", "url": "https://chat.example", "size": 5},
            {"id": 3, "name": "backups", "url": "https://b.example"},
        ]
        for query, want in [
            ("", [1, 2, 3]),
            ("   ", [1, 2, 3]),
            ("CHAT", [1, 2]),  # any case, and either field
            (" backups ", [3]),  # the spaces around it do not count
            ("zebra", []),  # a field it was not told to look in
            ("5", []),  # nor a number
        ]:
            self.assertEqual([row["id"] for row in match_rows(rows, query, "name", "url")], want, query)


class SortRowsTests(unittest.TestCase):
    def test_each_kind_goes_in_order(self) -> None:
        rows = [
            {"id": 1, "name": "bob", "size": 30, "on": True, "seen": "2026-01-01T01:00:00+00:00"},
            {"id": 2, "name": "Alice", "size": 4, "on": False, "seen": None},
            {"id": 3, "name": "", "size": 200, "on": True, "seen": "2026-01-01T00:00:00+00:00"},
            {"id": 4, "name": "carol", "size": 4, "on": False},
        ]
        for field, descending, want in [
            ("name", False, [2, 1, 4, 3]),  # any case, nothing goes last
            ("name", True, [4, 1, 2, 3]),  # and last this way too
            ("size", False, [2, 4, 1, 3]),  # numbers, not text; a tie keeps its order
            ("size", True, [3, 1, 2, 4]),  # a tie keeps it this way too
            ("on", True, [1, 3, 2, 4]),
            ("seen", False, [3, 1, 2, 4]),  # never seen is not the oldest
            ("seen", True, [1, 3, 2, 4]),
        ]:
            self.assertEqual([row["id"] for row in sort_rows(rows, field, descending)], want, (field, descending))


class ListRouteTests(RoutesTestCase):
    def test_searching_narrows_the_total_and_sort_still_applies(self) -> None:
        person = users.create_user(self.store, "Priya", users.ROLE_USER)
        cookie = self.session(person.id)
        for name in ("Zebra deploy", "alpha deploy", "backup"):
            api_keys.issue_api_key(self.store, person.id, name, users.ROLE_USER, 3600)
        _, page = self.call("GET", "/api/keys?q=deploy&sort=name&limit=1", cookie=cookie)
        self.assertEqual((page["total"], page["keys"][0]["name"]), (2, "alpha deploy"))
        _, page = self.call("GET", "/api/admin/keys?q=priya", cookie=self.owner_cookie)
        self.assertEqual(page["total"], 3)
        _, page = self.call("GET", "/api/keys?q=priya", cookie=cookie)
        self.assertEqual(page["total"], 0)

    def test_the_users_list_says_who_and_since(self) -> None:
        _, page = self.call("GET", "/api/admin/users?sort=created_at&dir=desc", cookie=self.owner_cookie)
        row = page["users"][0]
        self.assertTrue(row["created_at"])
        self.assertIn("username", row)
        self.assertNotIn("password_hash", row)

    def test_hiding_dead_keys(self) -> None:
        api_keys.issue_api_key(self.store, self.user.id, "live", users.ROLE_USER, 3600)
        _, revoked = api_keys.issue_api_key(self.store, self.user.id, "revoked", users.ROLE_USER, 3600)
        api_keys.revoke_api_key(self.store, revoked.id)
        _, expired = api_keys.issue_api_key(self.store, self.user.id, "expired", users.ROLE_USER, 3600)
        self.store.update_value(BUCKET_API_KEYS, expired.id, lambda record: record.update(expires_at=to_iso(utc_now() - timedelta(hours=1))))

        self.assertEqual(self.call("GET", "/api/keys", cookie=self.user_cookie)[1]["total"], 3)
        _, page = self.call("GET", "/api/keys?live=true", cookie=self.user_cookie)
        self.assertEqual([row["name"] for row in page["keys"]], ["live"])
        _, page = self.call("GET", "/api/admin/keys?live=true&q=expired", cookie=self.owner_cookie)
        self.assertEqual(page["total"], 0)

    def test_a_list_sorts_before_it_is_cut(self) -> None:
        for name in ("Yara", "aaron", "Zed"):
            users.create_user(self.store, name, users.ROLE_USER)
        status, page = self.call("GET", "/api/admin/users?sort=display_name&limit=1", cookie=self.owner_cookie)
        self.assertEqual((status, page["users"][0]["display_name"]), (200, "aaron"))
        _, page = self.call("GET", "/api/admin/users?sort=display_name&dir=desc&limit=1", cookie=self.owner_cookie)
        self.assertEqual(page["users"][0]["display_name"], "Zed")
        for query in ("sort=password_hash", "sort=id", "sort=display_name&dir=up"):
            self.assertEqual(self.call("GET", "/api/admin/users?" + query, cookie=self.owner_cookie)[0], 400, query)

    def test_pages(self) -> None:
        for index in range(5):
            users.create_user(self.store, f"Person {index}", users.ROLE_USER)

        status, first = self.call("GET", "/api/admin/users?limit=3", cookie=self.owner_cookie)
        self.assertEqual(status, 200)
        self.assertEqual((len(first["users"]), first["next"], first["total"]), (3, 3, 8))
        _, last = self.call("GET", "/api/admin/users?limit=3&offset=6", cookie=self.owner_cookie)
        self.assertEqual((len(last["users"]), last["next"]), (2, None))
        _, past = self.call("GET", "/api/admin/users?offset=50", cookie=self.owner_cookie)
        self.assertEqual(past["users"], [])

    def test_each_list_answers_under_its_own_name(self) -> None:
        for path, name in {
            "/api/team": "members",
            "/api/admin/invite-links": "invite_links",
        }.items():
            status, reply = self.call("GET", path, cookie=self.owner_cookie)
            self.assertEqual(status, 200, path)
            self.assertIsInstance(reply[name], list, path)

    def test_key_lists_need_a_session_and_page_too(self) -> None:
        for path in ["/api/keys", "/api/admin/keys"]:
            status, reply = self.call("GET", path, cookie=self.owner_cookie)
            self.assertEqual(status, 200, path)
            self.assertIsInstance(reply["keys"], list, path)

    def test_refuses_a_bad_page(self) -> None:
        for query in ["limit=0", "limit=1001", "limit=x", "offset=-1", "offset=x"]:
            self.assertEqual(self.call("GET", "/api/admin/users?" + query, cookie=self.owner_cookie)[0], 400, query)


class MCPPagingTests(RoutesTestCase):
    def tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            "/mcp",
            headers={"authorization": "Bearer " + self.admin_key, "accept": "application/json, text/event-stream", "content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
        )
        return response.json()

    def test_pages(self) -> None:
        page = self.tool("admin_list_users", {"limit": 1})["result"]["structuredContent"]
        self.assertEqual((len(page["users"]), page["next"], page["total"]), (1, 1, 3))

    def test_no_arguments_still_works(self) -> None:
        page = self.tool("list_team", {})["result"]["structuredContent"]
        self.assertEqual((len(page["members"]), page["next"]), (3, None))

    def test_a_limit_over_the_maximum_is_refused(self) -> None:
        self.assertTrue(self.tool("admin_list_users", {"limit": 5000})["result"]["isError"])

    def test_an_unknown_argument_is_invalid(self) -> None:
        self.assertIn("error", self.tool("admin_list_users", {"page": 1}))
