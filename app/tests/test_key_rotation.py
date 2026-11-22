"""A key rotates itself (portal contract v3, item 5): a new secret, the same
key -- id, grants, lineage, expiry -- so what it made keeps working, and a
leaked key that rotates still dies on schedule."""
from __future__ import annotations

from app.core.error_codes import CODE_OWNER_REQUIRED
from app.models import api_keys, portal, users
from app.tests.route_support import RoutesTestCase


class KeyRotationTest(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.set_config(api_keys_enabled=True)

    def send(self, cookie: str, path: str, **body: object) -> tuple[int, dict]:
        return self.call("POST", path, cookie=cookie, body={"csrf_token": self.csrf(cookie), **body})

    def test_a_key_rotates_itself(self) -> None:
        old, _, account = portal.connect_portal(self.store, self.owner.id, "ProjectPortal", 30 * 24 * 3600)
        status, me = self.call("GET", "/api/me", key=old)
        self.assertEqual(status, 200)
        self.assertIn("key_rotation", me["capabilities"])
        before = me["key"]
        status, minted = self.call("POST", f"/api/admin/users/{self.user.id}/keys", key=old, body={"name": "for user", "role": "user", "expires_in_days": 30})
        self.assertEqual(status, 201, minted)

        status, reply = self.call("POST", "/api/keys/self/rotate", key=old)
        self.assertEqual(status, 200, reply)
        self.assertEqual(list(reply), ["credential"])
        fresh = reply["credential"]
        self.assertNotEqual(fresh, old)
        self.assertEqual(self.call("GET", "/api/me", key=old)[0], 401)
        status, me = self.call("GET", "/api/me", key=fresh)
        self.assertEqual((status, me["id"]), (200, account.id))
        self.assertEqual(me["key"], before)
        self.assertEqual(self.call("GET", "/api/me", key=minted["credential"])[0], 200, "what it made stopped working")
        # A session has no key to rotate.
        self.assertEqual(self.send(self.owner_cookie, "/api/keys/self/rotate")[0], 403)

    def test_a_viewer_key_rotates_too(self) -> None:
        credential, _ = api_keys.issue_api_key(self.store, self.user.id, "reader", users.ROLE_VIEWER, 3600)
        status, reply = self.call("POST", "/api/keys/self/rotate", key=credential)
        self.assertEqual(status, 200, reply)

    def test_the_owner_rotates_an_own_key_from_a_session(self) -> None:
        old, key = api_keys.issue_api_key(self.store, self.owner.id, "cron", users.ROLE_ADMIN, 3600)
        status, reply = self.send(self.owner_cookie, f"/api/keys/{key.id}/rotate")
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.call("GET", "/api/me", key=old)[0], 401)
        self.assertEqual(api_keys.get_api_key(self.store, key.id).expires_at, key.expires_at)
        # Someone else's key is no such key; another admin's own is the owner's say-so.
        _, users_key = api_keys.issue_api_key(self.store, self.user.id, "theirs", users.ROLE_USER, 3600)
        self.assertEqual(self.send(self.owner_cookie, f"/api/keys/{users_key.id}/rotate")[0], 404)
        _, admins_key = api_keys.issue_api_key(self.store, self.admin.id, "his", users.ROLE_ADMIN, 3600)
        status, reply = self.send(self.admin_cookie, f"/api/keys/{admins_key.id}/rotate")
        self.assertEqual((status, reply.get("code")), (403, CODE_OWNER_REQUIRED), reply)
