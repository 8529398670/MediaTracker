"""Portal contract v2, the parts every app has: /api/me says which contract
and capabilities it speaks, the viewer role reads and changes nothing, and an
account can expire (ProjectPortal's CROSS_PROJECT.md, "Portal contract v2")."""
from __future__ import annotations

from datetime import timedelta

from app.core.db import BUCKET_SESSIONS, BUCKET_USERS
from app.models import credentials, login_tokens, to_iso, users, utc_now
from app.models.sign_in import SignInRules
from app.models import api_keys
from app.tests.route_support import RoutesTestCase


class Discovery(RoutesTestCase):
    def test_me_names_the_contract_and_capabilities(self) -> None:
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["contract"], 2)
        self.assertIn("viewer_role", me["capabilities"])
        self.assertIn("account_expiry", me["capabilities"])
        self.set_config(api_keys_enabled=True)
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertIn("key_minting", me["capabilities"])
        self.assertIn("key_sign_in", me["capabilities"])
        self.set_config(invite_links_enabled=False)
        self.assertNotIn("invite_links", self.call("GET", "/api/me", cookie=self.user_cookie)[1]["capabilities"])
        self.set_config(invite_links_enabled=True)
        self.assertIn("invite_links", self.call("GET", "/api/me", cookie=self.user_cookie)[1]["capabilities"])


class ViewerRole(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.viewer = users.create_user(self.store, "Viewer", users.ROLE_VIEWER)
        self.viewer_cookie = self.session(self.viewer.id)

    def post(self, path: str, body: dict | None = None) -> tuple[int, dict]:
        return self.call("POST", path, cookie=self.viewer_cookie, body={"csrf_token": self.csrf(self.viewer_cookie), **(body or {})})

    def test_a_viewer_reads_and_is_told_so(self) -> None:
        status, me = self.call("GET", "/api/me", cookie=self.viewer_cookie)
        self.assertEqual((status, me["role"]), (200, "viewer"))

    def test_every_write_is_view_only(self) -> None:
        for path in ("/api/account/rename", "/api/account/login-link", "/api/admin/users"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, {"display_name": "x"}), (403, {"error": "view_only"}))
        self.assertEqual(self.store.get(BUCKET_USERS, self.viewer.id)["display_name"], "Viewer")

    def test_signing_out_and_taking_ways_in_away_still_work(self) -> None:
        self.assertEqual(self.post("/api/account/login-link/cancel")[0], 200)
        self.assertEqual(self.post("/api/logout")[0], 200)

    def test_an_admin_makes_someone_a_viewer(self) -> None:
        status, _ = self.call("POST", f"/api/admin/users/{self.user.id}/role", cookie=self.owner_cookie,
                              body={"csrf_token": self.csrf(self.owner_cookie), "role": "viewer"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("POST", "/api/account/rename", cookie=self.user_cookie,
                                   body={"csrf_token": self.csrf(self.user_cookie), "display_name": "x"}), (403, {"error": "view_only"}))

    def test_a_viewer_key_and_a_viewer_accounts_admin_key_both_view_only(self) -> None:
        self.set_config(api_keys_enabled=True)
        scoped, _ = api_keys.issue_api_key(self.store, self.owner.id, "look", users.ROLE_VIEWER, 3600)
        _, me = self.call("GET", "/api/me", key=scoped)
        self.assertEqual(me["role"], "viewer")
        self.assertEqual(self.call("POST", "/api/account/rename", key=scoped, body={"display_name": "x"}), (403, {"error": "view_only"}))
        # A key never outranks its account: the viewer cannot mint a user key.
        with self.assertRaises(api_keys.APIKeyRoleError):
            api_keys.issue_api_key(self.store, self.viewer.id, "more", users.ROLE_USER, 3600)


class AccountExpiry(RoutesTestCase):
    def post(self, cookie: str, path: str, body: dict) -> tuple[int, dict]:
        return self.call("POST", path, cookie=cookie, body={"csrf_token": self.csrf(cookie), **body})

    def soon(self, **delta: int) -> str:
        return to_iso(utc_now() + timedelta(**delta))

    def test_create_with_an_expiry_and_list_it(self) -> None:
        status, made = self.post(self.owner_cookie, "/api/admin/users", {"display_name": "Temp", "role": "user", "account_expires_at": self.soon(days=2)})
        self.assertEqual(status, 201)
        _, page = self.call("GET", "/api/admin/users", cookie=self.owner_cookie)
        row = next(user for user in page["users"] if user["id"] == made["user_id"])
        self.assertIsNotNone(row["expires_at"])
        self.assertFalse(row["expired"])
        self.assertEqual(self.post(self.owner_cookie, "/api/admin/users", {"display_name": "Late", "role": "user", "account_expires_at": "yesterday"})[0], 400)

    def test_set_and_clear(self) -> None:
        status, reply = self.post(self.owner_cookie, f"/api/admin/users/{self.user.id}/expiry", {"expires_at": self.soon(hours=1)})
        self.assertEqual((status, reply["ok"]), (200, True))
        self.assertIsNotNone(users.get_user(self.store, self.user.id).expires_at)
        status, reply = self.post(self.owner_cookie, f"/api/admin/users/{self.user.id}/expiry", {"expires_at": None})
        self.assertEqual((status, reply), (200, {"ok": True, "expires_at": None}))
        self.assertIsNone(users.get_user(self.store, self.user.id).expires_at)

    def test_the_owner_never_expires_and_only_the_owner_sets_an_admins(self) -> None:
        self.assertEqual(self.post(self.admin_cookie, f"/api/admin/users/{self.owner.id}/expiry", {"expires_at": self.soon(days=1)})[0], 403)
        self.assertEqual(self.post(self.admin_cookie, f"/api/admin/users/{self.admin.id}/expiry", {"expires_at": self.soon(days=1)})[0], 200)
        other = users.create_user(self.store, "Third admin", users.ROLE_ADMIN)
        self.assertEqual(self.post(self.admin_cookie, f"/api/admin/users/{other.id}/expiry", {"expires_at": self.soon(days=1)})[0], 403)

    def past(self, user_id: int) -> None:
        def mutate(record: dict) -> None:
            record["expires_at"] = to_iso(utc_now() - timedelta(minutes=1))

        self.store.update_value(BUCKET_USERS, user_id, mutate)

    def test_once_past_it_counts_as_disabled_at_once(self) -> None:
        link = login_tokens.issue_login_token(self.store, self.user.id, 3600)
        self.past(self.user.id)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[0], 401)
        _, page = self.call("GET", "/api/admin/users", cookie=self.owner_cookie)
        row = next(user for user in page["users"] if user["id"] == self.user.id)
        self.assertTrue(row["expired"] and row["disabled"])
        self.assertIsNone(login_tokens.redeem_login_token(self.store, link, SignInRules(3600)))

    def test_housekeeping_disables_and_revokes(self) -> None:
        key, _ = api_keys.issue_api_key(self.store, self.user.id, "bot", users.ROLE_USER, 3600)
        self.past(self.user.id)
        self.assertEqual(credentials.expire_due_accounts(self.store), 1)
        user = users.get_user(self.store, self.user.id)
        self.assertIsNotNone(user.disabled_at)
        self.assertFalse([r for _, r in self.store.all(BUCKET_SESSIONS) if r["user_id"] == self.user.id])
        self.assertTrue(api_keys.get_api_key(self.store, key.split(".")[0]).revoked)
        # Twice is a no-op, and the owner is never touched.
        self.assertEqual(credentials.expire_due_accounts(self.store), 0)


class ViewerInviteLinks(RoutesTestCase):
    def test_a_viewer_link_makes_viewers(self) -> None:
        from datetime import timedelta as days_of

        from app.models import invite_links

        credential, link = invite_links.issue_invite_link(self.store, "Club", 5, days_of(days=1), self.owner.id, role=users.ROLE_VIEWER)
        self.assertEqual(link.role, "viewer")
        _, user = invite_links.join_invite_link(self.store, credential, "Ann", 3600)
        self.assertEqual(user.role, "viewer")
        cookie = self.owner_cookie
        status, made = self.call("POST", "/api/admin/invite-links", cookie=cookie,
                                 body={"csrf_token": self.csrf(cookie), "label": "Look", "max_uses": 2, "days": 1, "role": "viewer"})
        self.assertEqual((status, made["role"]), (201, "viewer"))
        self.assertEqual(self.call("POST", "/api/admin/invite-links", cookie=cookie,
                                   body={"csrf_token": self.csrf(cookie), "label": "Boss", "max_uses": 2, "days": 1, "role": "admin"})[0], 400)
