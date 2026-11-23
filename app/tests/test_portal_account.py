"""ProjectPortal's own account (portal contract v3, item 2): a service
account the owner connects from the API keys screen, with keys only, never
signed into, and run only by the owner."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import sessions

from app.core.error_codes import CODE_OWNER_REQUIRED, CODE_SERVICE_ACCOUNT
from app.models import api_keys, login_tokens, users
from app.models.login_tokens import LinkOptions
from app.tests.route_support import RoutesTestCase


class PortalAccountTest(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.set_config(api_keys_enabled=True)

    def send(self, cookie: str, path: str, **body: object) -> tuple[int, dict]:
        return self.call("POST", path, cookie=cookie, body={"csrf_token": self.csrf(cookie), **body})

    def connect(self, **body: object) -> tuple[str, dict]:
        status, reply = self.send(self.owner_cookie, "/api/owner/portal/connect", **body)
        self.assertEqual(status, 201, reply)
        return reply["credential"], reply

    def test_connect_makes_the_service_account_and_its_key(self) -> None:
        credential, reply = self.connect(days=365)
        self.assertEqual((reply["display_name"], reply["role"], reply["may_mint_keys"], reply["may_sign_in"]), ("ProjectPortal", "admin", True, False))
        user_id = reply["user_id"]
        status, me = self.call("GET", "/api/me", key=credential)
        self.assertEqual((status, me["kind"], me["owner"], me["role"]), (200, "service", False, "admin"))
        self.assertEqual((me["key"]["may_mint_keys"], me["key"]["may_sign_in"]), (True, False))
        days = (datetime.fromisoformat(me["key"]["expires_at"]) - datetime.now(timezone.utc)).total_seconds() / 86400
        self.assertTrue(364 < days <= 365, days)
        self.assertIn("service_accounts", me["capabilities"])

        # Connect again: the same account, one more key.
        _, again = self.connect(name="ProjectPortal", days=30)
        self.assertEqual(again["user_id"], user_id)
        status, page = self.call("GET", "/api/owner/portal", cookie=self.owner_cookie)
        self.assertEqual(status, 200)
        self.assertEqual([(each["id"], len(each["keys"])) for each in page["accounts"]], [(user_id, 2)])

        # The accounts list says which account is a service account.
        _, listed = self.call("GET", "/api/admin/users", cookie=self.owner_cookie)
        for row in listed["users"]:
            self.assertEqual(row["kind"], "service" if row["id"] == user_id else "person", row)

        # The key lifetime is required, 1-365 days.
        for body in ({"days": 0}, {"days": 366}, {}):
            status, reply = self.send(self.owner_cookie, "/api/owner/portal/connect", **body)
            self.assertEqual((status, reply.get("field")), (400, "days"), f"{body}: {reply}")

    def test_only_the_owner_connects_the_portal(self) -> None:
        for path in ("/api/owner/portal/connect", "/api/owner/portal/disconnect"):
            self.assertEqual(self.send(self.admin_cookie, path, days=30, user_id=1)[0], 404, path)
        self.assertEqual(self.call("GET", "/api/owner/portal", cookie=self.admin_cookie)[0], 404)

    def test_a_service_account_is_never_signed_into(self) -> None:
        credential, reply = self.connect(days=30)
        user_id, key_id = reply["user_id"], reply["id"]
        service = f"/api/admin/users/{user_id}"
        for what, (status, refusal) in {
            "creating one by hand": self.send(self.owner_cookie, "/api/admin/users", display_name="Bot", role="admin", kind="service"),
            "a login link": self.send(self.owner_cookie, f"{service}/reissue-login"),
            "a role change": self.send(self.owner_cookie, f"{service}/role", role="user"),
        }.items():
            self.assertEqual((status, refusal.get("code")), (403, CODE_SERVICE_ACCOUNT), f"{what}: {refusal}")
        self.assertEqual(self.call("POST", "/api/account/login-link", key=credential, body={"max_uses": 1, "expires_in_minutes": 15})[0], 403)
        with self.assertRaises(users.ServiceAccountError):
            api_keys.set_api_key_sign_in(self.store, key_id, user_id, True)
        with self.assertRaises(users.ServiceAccountError):
            login_tokens.issue_login_link(self.store, user_id, LinkOptions(max_uses=1, ttl_seconds=60))

    def test_the_service_account_is_the_owners_alone(self) -> None:
        _, reply = self.connect(days=30)
        user_id = reply["user_id"]
        service = f"/api/admin/users/{user_id}"
        for action, body in (("revoke-access", {}), ("disabled", {"disabled": True}), ("delete", {})):
            status, refusal = self.send(self.admin_cookie, f"{service}/{action}", **body)
            self.assertEqual((status, refusal.get("code")), (403, CODE_OWNER_REQUIRED), f"{action}: {refusal}")
        self.assertEqual(self.call("GET", f"{service}/keys", cookie=self.admin_cookie)[0], 403)
        with self.assertRaises(users.ServiceAccountError):
            users.transfer_owner(self.store, user_id)

    def test_the_owner_lets_a_service_key_mint(self) -> None:
        _, reply = self.connect(days=30)
        key_id = reply["id"]
        status, reply = self.send(self.owner_cookie, f"/api/keys/{key_id}/mint-keys", may_mint_keys=False)
        self.assertEqual((status, reply.get("may_mint_keys")), (200, False), reply)
        status, reply = self.send(self.owner_cookie, f"/api/keys/{key_id}/mint-keys", may_mint_keys=True)
        self.assertEqual((status, reply.get("may_mint_keys")), (200, True), reply)
        # Still nobody else's key: another admin's admin key stays out of reach.
        _, theirs = api_keys.issue_api_key(self.store, self.admin.id, "theirs", users.ROLE_ADMIN, 3600)
        self.assertNotEqual(self.send(self.owner_cookie, f"/api/keys/{theirs.id}/mint-keys", may_mint_keys=True)[0], 200)

    def test_disconnect_ends_the_portal_and_all_it_made(self) -> None:
        credential, reply = self.connect(days=30)
        user_id = reply["user_id"]
        status, minted = self.call("POST", f"/api/admin/users/{self.user.id}/keys", key=credential, body={"name": "for user", "role": "user", "expires_in_days": 30})
        self.assertEqual(status, 201, minted)
        status, reply = self.send(self.owner_cookie, "/api/owner/portal/disconnect", user_id=user_id)
        self.assertEqual((status, reply.get("revoked")), (200, 1), reply)
        for what, key in (("the portal's key", credential), ("a key it made", minted["credential"])):
            self.assertEqual(self.call("GET", "/api/me", key=key)[0], 401, what)
        # Only a service account is disconnected this way.
        self.assertEqual(self.send(self.owner_cookie, "/api/owner/portal/disconnect", user_id=self.user.id)[0], 404)

    def test_the_shell_connects_the_portal(self) -> None:
        """`manage portal-connect`: the shell is the owner's say-so."""
        import contextlib
        import io
        from argparse import Namespace

        from app import manage
        from app.models import portal

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            manage.command_portal_connect(self.store, self.holder.get(), Namespace(name="ProjectPortal", days=30))
        accounts = portal.portal_accounts(self.store)
        self.assertEqual([(each.user.is_service, len(each.keys), each.keys[0].may_mint_keys) for each in accounts], [(True, 1, True)])
        self.assertIn("ProjectPortal", printed.getvalue())
        with self.assertRaises(manage.ManageError):
            manage.command_portal_connect(self.store, self.holder.get(), Namespace(name="ProjectPortal", days=366))

    def test_the_portal_reads_an_accounts_devices(self) -> None:
        """admin_sessions: the portal reads an ordinary account's devices to
        tell who is who across apps. Its service account sees the addresses,
        which other admins do not, and the rows carry no secret."""
        credential, _ = self.connect(days=30)
        device = sessions.list_sessions(self.store, self.user.id)[0].id
        sessions.remember_client(self.store, device, "10.0.0.7", "Mozilla/5.0 (Test)")
        status, reply = self.send(self.user_cookie, f"/api/account/sessions/{device}/label", label="Phone")
        self.assertEqual(status, 200, reply)

        status, me = self.call("GET", "/api/me", key=credential)
        self.assertEqual(status, 200)
        self.assertIn("admin_sessions", me["capabilities"])

        status, page = self.call("GET", f"/api/admin/users/{self.user.id}/sessions", key=credential)
        self.assertEqual((status, len(page["sessions"])), (200, 1), page)
        row = page["sessions"][0]
        allowed = {"id", "current", "created_at", "expires_at", "last_seen_at", "ip", "user_agent", "label"}
        self.assertLessEqual(set(row), allowed, row)
        self.assertEqual((row["id"], row["ip"], row["user_agent"], row["label"]), (device, "10.0.0.7", "Mozilla/5.0 (Test)", "Phone"))
        for name in ("created_at", "last_seen_at"):
            if name in row:
                self.assertIsNotNone(datetime.fromisoformat(row[name].replace("Z", "+00:00")).tzinfo, f"{name}: {row[name]}")
