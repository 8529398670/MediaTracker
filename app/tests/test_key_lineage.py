"""What a key can leave behind (security round 3, from the ProjectPortal +
TodoBoard audit of 2026-11-22). Revoking a key, or its expiry, must end
everything it made, however indirectly: through a login link it reissued for
its own account, through the browser session such a link opened, or through a
key it minted."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from starlette.testclient import TestClient

from app.core.db import BUCKET_API_KEYS
from app.models import api_keys, users
from app.tests.route_support import RoutesTestCase


class KeyLineage(RoutesTestCase):
    config_changes = {
        "api_keys_enabled": True,
        "passwords_enabled": True,
        "two_factor_enabled": True,
        "invite_links_enabled": True,
    }

    def browser(self) -> TestClient:
        # https, or the Secure session cookie is dropped.
        return TestClient(self.app, base_url="https://testserver")

    def send(self, who: str | TestClient, path: str, **body: object) -> tuple[int, dict]:
        if isinstance(who, str):
            return self.call("POST", path, cookie=who, body={**body, "csrf_token": self.csrf(who)})
        token = self.call("GET", "/api/me", client=who)[1]["csrf_token"]
        return self.call("POST", path, body={**body, "csrf_token": token}, client=who)

    def signed_in(self, client: TestClient) -> bool:
        return self.call("GET", "/api/me", client=client)[0] == 200

    def logs_in(self, login_path: str) -> bool:
        return self.call("POST", "/api/login", body={"credential": login_path.removeprefix("/login/")}, client=self.browser())[0] == 200

    def key_born_session(self, key: str) -> TestClient:
        """A browser signed in through a login link the key made for its own
        account, the way ProjectPortal's Open does."""
        status, reply = self.call("POST", "/api/account/login-link", key=key, body={})
        self.assertEqual(status, 200, reply)
        client = self.browser()
        status, reply = self.call("POST", "/api/login", body={"credential": reply["login_path"].removeprefix("/login/")}, client=client)
        self.assertEqual(status, 200, reply)
        return client

    def allow_sign_in(self, key_id: str) -> None:
        status, reply = self.send(self.owner_cookie, f"/api/keys/{key_id}/sign-in", may_sign_in=True)
        self.assertEqual(status, 200, reply)

    def test_a_key_cannot_reissue_its_own_login_link(self) -> None:
        """H1: reissue-login pointed at your own account was a way round
        may_sign_in and its once-and-15-minutes cap."""
        key, stored = api_keys.issue_api_key(self.store, self.owner.id, "script", users.ROLE_ADMIN, 0)
        own = f"/api/admin/users/{self.owner.id}/reissue-login"
        forever = {"max_uses": 0, "expires_in_minutes": 0}
        status, reply = self.call("POST", own, key=key, body=forever)
        self.assertEqual(status, 403, f"a key without sign-in links reissued its own: {reply}")

        # Allowed to sign in, it gets what /api/account/login-link gives a key.
        self.allow_sign_in(stored.id)
        status, reply = self.call("POST", own, key=key, body=forever)
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["max_uses"], 1)
        self.assertLessEqual(reply["expires_in_seconds"], 15 * 60)

        # A browser session reissuing its own (the Users screen) is unchanged.
        status, reply = self.send(self.owner_cookie, own, **forever)
        self.assertEqual((status, reply.get("unlimited")), (200, True), reply)

    def test_a_key_born_session_leaves_nothing_behind(self) -> None:
        """H2: a session a key opened made keys, links and credentials that
        outlived revoking the key."""
        key, stored = api_keys.issue_api_key(self.store, self.owner.id, "portal", users.ROLE_ADMIN, 0)
        _, other = api_keys.issue_api_key(self.store, self.owner.id, "ci", users.ROLE_ADMIN, 0)
        self.allow_sign_in(stored.id)
        borrowed = self.key_born_session(key)

        # What it makes records the key.
        status, reply = self.send(borrowed, "/api/keys", name="left behind", role="admin", expires_in_days=0)
        self.assertEqual((status, reply.get("minted_by_key")), (201, stored.id), reply)
        left = reply["credential"]
        status, reply = self.send(borrowed, "/api/account/login-link", max_uses=0, expires_in_minutes=0)
        self.assertEqual(status, 200, reply)
        spare = reply["login_path"]

        # What would hand out a credential nothing ties to the key is refused.
        status, reply = self.send(borrowed, f"/api/keys/{other.id}/rotate")
        self.assertEqual((status, reply.get("code")), (403, "session_only"), reply)
        password = hashlib.sha256(b"correct horse battery staple").hexdigest()[:43]
        self.assertEqual(self.send(borrowed, "/api/account/password", username="owner", password_digest=password, code="")[0], 403)
        self.assertEqual(self.send(borrowed, "/api/account/two-factor/start")[0], 403)
        self.assertEqual(self.send(borrowed, "/api/account/pin", pin="482913")[0], 403)

        # The owner's own session still does all of it.
        self.assertEqual(self.send(self.owner_cookie, f"/api/keys/{other.id}/rotate")[0], 200)

        # Revoking the key ends all of it.
        status, reply = self.send(self.owner_cookie, f"/api/keys/{stored.id}/revoke")
        self.assertEqual(status, 200, reply)
        self.assertFalse(self.signed_in(borrowed), "the key's session outlived it")
        self.assertEqual(self.call("GET", "/api/me", key=left)[0], 401, "a key made in its session outlived it")
        self.assertFalse(self.logs_in(spare), "a link made in its session outlived it")

    def test_a_key_born_session_ends_when_the_key_expires(self) -> None:
        """A key's expiry ends the sessions its links opened, as revoking it
        does: nothing runs at the expiry, so the session is checked as it is
        loaded."""
        key, stored = api_keys.issue_api_key(self.store, self.owner.id, "portal", users.ROLE_ADMIN, 3600)
        self.allow_sign_in(stored.id)
        borrowed = self.key_born_session(key)
        self.assertTrue(self.signed_in(borrowed))
        with self.store.transaction() as tx:
            record = tx.get(BUCKET_API_KEYS, stored.id)
            record["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            tx.put(BUCKET_API_KEYS, stored.id, record)
        self.assertFalse(self.signed_in(borrowed), "the key's session outlived its expiry")
        self.assertEqual(self.call("GET", "/api/me", cookie=self.owner_cookie)[0], 200, "the owner's own session ended too")

    def test_a_minted_key_dies_with_its_parent(self) -> None:
        """M1: a minted key lived past the key that made it."""
        parent, stored = api_keys.issue_api_key(self.store, self.owner.id, "portal", users.ROLE_ADMIN, 24 * 3600)
        status, reply = self.send(self.owner_cookie, f"/api/keys/{stored.id}/mint-keys", may_mint_keys=True)
        self.assertEqual(status, 200, reply)
        status, reply = self.call("POST", f"/api/admin/users/{self.user.id}/keys", key=parent, body={"name": "long", "role": "user", "expires_in_days": 365})
        self.assertEqual(status, 201, reply)
        child_id = reply["id"]
        parent_expires = api_keys.get_api_key(self.store, stored.id).expires_at
        self.assertLessEqual(datetime.fromisoformat(reply["expires_at"].replace("Z", "+00:00")), parent_expires)

        # Its account cannot stretch it past the parent either.
        status, _ = self.send(self.user_cookie, f"/api/keys/{child_id}/expiry", expires_in_days=0)
        if status == 200:
            child = api_keys.get_api_key(self.store, child_id)
            self.assertIsNotNone(child.expires_at)
            self.assertLessEqual(child.expires_at, parent_expires)

    def test_an_admin_cannot_change_their_own_expiry(self) -> None:
        """M2: an admin cleared the expiry the owner set on them."""
        path = f"/api/admin/users/{self.admin.id}/expiry"
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.assertEqual(self.send(self.owner_cookie, path, expires_at=soon)[0], 200)
        status, reply = self.send(self.admin_cookie, path, expires_at=None)
        self.assertEqual(status, 403, f"an admin cleared their own expiry: {reply}")
        key, _ = api_keys.issue_api_key(self.store, self.admin.id, "theirs", users.ROLE_ADMIN, 0)
        self.assertEqual(self.call("POST", path, key=key, body={"expires_at": None})[0], 403)
        self.assertIsNotNone(users.get_user(self.store, self.admin.id).expires_at)


if __name__ == "__main__":
    import unittest
    unittest.main()
