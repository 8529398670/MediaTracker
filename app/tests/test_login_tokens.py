"""Login links: once by default, or up to N times, or any number of times,
until a chosen expiry or never -- and every way of ending one."""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Callable

from app.core import db
from app.core.db import BUCKET_LOGIN_TOKENS
from app.models import credentials, login_tokens, to_iso, users, utc_now
from app.models.login_tokens import BadLoginLinkError, LinkOptions
from app.models.sign_in import SignInRules

RULES = SignInRules(3600)


class LoginTokenModelTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = db.open_store(Path(directory.name) / "test.db", "ab" * 32, True)
        self.admin = users.create_user(self.store, "Admin", users.ROLE_ADMIN)
        users.ensure_owner(self.store)
        self.ana = users.create_user(self.store, "Ana", users.ROLE_USER)

    def redeem(self, credential: str) -> bool:
        return login_tokens.redeem_login_token(self.store, credential, RULES) is not None

    def rewrite(self, change: Callable[[dict], None]) -> None:
        """Rewrite every stored link, to stand in for time passing or for a
        row an older build wrote."""
        for key, record in self.store.all(BUCKET_LOGIN_TOKENS):
            change(record)
            self.store.put(BUCKET_LOGIN_TOKENS, key, record)

    def test_once_by_default(self) -> None:
        credential = login_tokens.issue_login_token(self.store, self.ana.id, 3600)
        self.assertTrue(self.redeem(credential))
        self.assertFalse(self.redeem(credential))
        self.assertIsNone(login_tokens.live_login_link(self.store, self.ana.id))

    def test_up_to_its_uses(self) -> None:
        credential, info = login_tokens.issue_login_link(self.store, self.ana.id, LinkOptions(max_uses=3, ttl_seconds=3600))
        self.assertEqual(info["max_uses"], 3)
        self.assertIsNotNone(info["expires_at"])
        for _ in range(3):
            self.assertTrue(self.redeem(credential))
        self.assertFalse(self.redeem(credential))

    def test_unlimited_and_never_expiring(self) -> None:
        credential, info = login_tokens.issue_login_link(self.store, self.ana.id, LinkOptions(unlimited=True))
        self.assertEqual((info["unlimited"], info["max_uses"], info["expires_at"]), (True, 0, None))
        for _ in range(5):
            self.assertTrue(self.redeem(credential))
        live = login_tokens.live_login_link(self.store, self.ana.id)
        self.assertEqual(live["uses"], 5)
        self.assertIsNotNone(live["last_used_at"])
        # Nothing about it ages out: the purge leaves it alone.
        self.assertEqual(login_tokens.purge_expired_login_tokens(self.store), 0)
        self.assertTrue(self.redeem(credential))

    def test_an_expired_reusable_link(self) -> None:
        credential, _ = login_tokens.issue_login_link(self.store, self.ana.id, LinkOptions(unlimited=True, ttl_seconds=3600))
        self.assertTrue(self.redeem(credential))
        self.rewrite(lambda record: record.update(expires_at=to_iso(utc_now() - timedelta(minutes=1))))
        self.assertFalse(self.redeem(credential))
        self.assertEqual(login_tokens.purge_expired_login_tokens(self.store), 1)

    def test_ending_a_used_reusable_link(self) -> None:
        """Reissue, disable, promotion, revoke and cancel each stop a reusable
        link that has already been used: what matters is whether it would
        still let someone in, not whether it is fresh."""
        ends = {
            "reissue": lambda: login_tokens.issue_login_token(self.store, self.ana.id, 3600),
            "disable": lambda: credentials.set_user_disabled(self.store, self.ana.id, True),
            "promote": lambda: credentials.set_user_role(self.store, self.ana.id, self.admin.id, users.ROLE_ADMIN),
            "revoke": lambda: credentials.revoke_all_credentials(self.store, self.ana.id, True),
            "cancel": lambda: login_tokens.cancel_login_link(self.store, self.ana.id),
        }
        for name, end in ends.items():
            with self.subTest(name):
                self.ana = users.create_user(self.store, "Ana " + name, users.ROLE_USER)
                credential, _ = login_tokens.issue_login_link(self.store, self.ana.id, LinkOptions(unlimited=True, ttl_seconds=3600))
                self.assertTrue(self.redeem(credential))
                end()
                if name == "disable":
                    credentials.set_user_disabled(self.store, self.ana.id, False)
                self.assertFalse(self.redeem(credential))

    def test_old_rows_still_mean_once(self) -> None:
        """A row written before links could be reused has no max_uses or
        uses. Unused, it works exactly once; used, it stays used."""
        credential = login_tokens.issue_login_token(self.store, self.ana.id, 3600)
        self.rewrite(lambda record: [record.pop(name) for name in ("max_uses", "unlimited", "uses")])
        self.assertTrue(self.redeem(credential))
        self.rewrite(lambda record: [record.pop(name, None) for name in ("max_uses", "unlimited", "uses")])
        self.assertFalse(self.redeem(credential))

    def test_a_used_up_link_that_never_expires_is_purged_later(self) -> None:
        credential, _ = login_tokens.issue_login_link(self.store, self.ana.id, LinkOptions(max_uses=1))
        self.assertTrue(self.redeem(credential))
        self.assertEqual(login_tokens.purge_expired_login_tokens(self.store), 0)
        long_ago = utc_now() - login_tokens.LOGIN_LINK_RETENTION - timedelta(hours=1)
        self.rewrite(lambda record: record.update(used_at=to_iso(long_ago)))
        self.assertEqual(login_tokens.purge_expired_login_tokens(self.store), 1)

    def test_limits(self) -> None:
        for bad in (
            LinkOptions(max_uses=0, ttl_seconds=3600),
            LinkOptions(max_uses=1001, ttl_seconds=3600),
            LinkOptions(max_uses=1, ttl_seconds=-1),
            LinkOptions(max_uses=1, ttl_seconds=366 * 86400),
        ):
            with self.subTest(bad):
                with self.assertRaises(BadLoginLinkError):
                    login_tokens.issue_login_link(self.store, self.ana.id, bad)

    def test_resolving_a_request(self) -> None:
        once, multi = 1800, 7 * 86400
        cases = [
            ((None, None), LinkOptions(1, False, once)),
            ((5, None), LinkOptions(5, False, multi)),
            ((0, None), LinkOptions(0, True, multi)),
            ((None, 60), LinkOptions(1, False, 3600)),
            ((0, 0), LinkOptions(0, True, 0)),
        ]
        for (uses, minutes), want in cases:
            self.assertEqual(login_tokens.resolve_link(uses, minutes, once, multi), want)
        for uses, minutes in ((-1, None), (1001, None), (True, None), ("5", None), (None, -5), (None, 525601), (None, False)):
            with self.subTest((uses, minutes)):
                with self.assertRaises(BadLoginLinkError):
                    login_tokens.resolve_link(uses, minutes, once, multi)

    def test_parsing_cli_flags(self) -> None:
        good = {
            ("", ""): (None, None),
            ("3", "30m"): (3, 30),
            ("unlimited", "7d"): (0, 10080),
            ("Unlimited", "never"): (0, 0),
            ("", "12h"): (None, 720),
        }
        for flags, want in good.items():
            self.assertEqual(login_tokens.parse_link_flags(*flags), want)
        for flags in (("0", ""), ("1001", ""), ("lots", ""), ("", "7"), ("", "7w"), ("", "366d"), ("", "0m")):
            with self.subTest(flags):
                with self.assertRaises(ValueError):
                    login_tokens.parse_link_flags(*flags)


try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:  # no httpx2: the model tests above still run
    RoutesTestCase = None  # type: ignore[assignment,misc]

if RoutesTestCase is not None:
    from starlette.testclient import TestClient

    class LoginLinkRoutesTest(RoutesTestCase):
        def setUp(self) -> None:
            super().setUp()
            self.set_config(login_token_ttl_seconds=1800, multi_use_login_token_ttl_seconds=7 * 86400)

        def post(self, cookie: str, path: str, **body: object) -> tuple[int, dict]:
            return self.call("POST", path, cookie=cookie, body={"csrf_token": self.csrf(cookie), **body})

        def sign_in_with(self, reply: dict) -> int:
            credential = reply["login_path"].removeprefix("/login/")
            return TestClient(self.app).post("/api/login", json={"credential": credential}).status_code

        def row(self, user_id: int) -> dict:
            rows = self.call("GET", "/api/admin/users", cookie=self.owner_cookie)[1]["users"]
            return next(row for row in rows if row["id"] == user_id)

        def test_making_a_reusable_link(self) -> None:
            # The default is still once, for the configured half hour.
            status, reply = self.post(self.owner_cookie, "/api/admin/users", display_name="Bea", role="user")
            self.assertEqual((status, reply["max_uses"], reply["unlimited"]), (201, 1, False))
            self.assertTrue(1790 <= reply["expires_in_seconds"] <= 1800)

            # Three uses, and a link that works more than once lasts the multi-use default.
            path = f"/api/admin/users/{self.user.id}/reissue-login"
            status, reply = self.post(self.owner_cookie, path, max_uses=3)
            self.assertEqual((status, reply["max_uses"]), (200, 3))
            self.assertGreater(reply["expires_in_seconds"], 7 * 86400 - 10)
            for _ in range(3):
                self.assertEqual(self.sign_in_with(reply), 200)
            self.assertEqual(self.sign_in_with(reply), 400)

            # Unlimited and never expiring; the user list shows it with its uses.
            status, reply = self.post(self.owner_cookie, path, max_uses=0, expires_in_minutes=0)
            self.assertEqual((status, reply["unlimited"], reply["expires_at"], reply["expires_in_seconds"]), (200, True, None, 0))
            for _ in range(2):
                self.sign_in_with(reply)
            link = self.row(self.user.id)["login_link"]
            self.assertEqual((link["uses"], link["unlimited"], link["expires_at"]), (2, True, None))

            # Cancelling stops it, and the row no longer shows one.
            self.assertEqual(self.post(self.owner_cookie, f"/api/admin/users/{self.user.id}/cancel-login-link")[0], 200)
            self.assertEqual(self.sign_in_with(reply), 400)
            self.assertIsNone(self.row(self.user.id)["login_link"])

        def test_options_are_checked(self) -> None:
            path = f"/api/admin/users/{self.user.id}/reissue-login"
            for bad in ({"max_uses": -1}, {"max_uses": 1001}, {"max_uses": True}, {"max_uses": "5"},
                        {"expires_in_minutes": -1}, {"expires_in_minutes": 525601}, {"expires_in_minutes": False}):
                with self.subTest(bad):
                    self.assertEqual(self.post(self.owner_cookie, path, **bad)[0], 400)
            # A refused create makes no account.
            before = len(users.list_users(self.store))
            self.assertEqual(self.post(self.owner_cookie, "/api/admin/users", display_name="Cy", role="user", max_uses=5000)[0], 400)
            self.assertEqual(len(users.list_users(self.store)), before)

        def test_your_own_reusable_link(self) -> None:
            status, reply = self.post(self.user_cookie, "/api/account/login-link", max_uses=2, expires_in_minutes=60)
            self.assertEqual((status, reply["max_uses"]), (200, 2))
            self.sign_in_with(reply)
            link = self.call("GET", "/api/me", cookie=self.user_cookie)[1]["login_link"]
            self.assertEqual((link["uses"], link["max_uses"]), (1, 2))

            self.assertEqual(self.post(self.user_cookie, "/api/account/login-link/cancel")[0], 200)
            self.assertEqual(self.sign_in_with(reply), 400)
            self.assertIsNone(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["login_link"])

        def test_only_an_admin_cancels_someone_elses_link(self) -> None:
            self.assertEqual(self.post(self.user_cookie, f"/api/admin/users/{self.owner.id}/cancel-login-link")[0], 403)
            self.assertEqual(self.post(self.owner_cookie, "/api/admin/users/999/cancel-login-link")[0], 404)


if __name__ == "__main__":
    unittest.main()
