"""Portal contract v2's key minting: only the owner lets a key mint keys, a
minting key mints for other accounts at most at their role, and revoking a key
revokes every key below it, down the whole chain."""
from __future__ import annotations

from app.models import api_keys, users
from app.tests.route_support import RoutesTestCase


class KeyMinting(RoutesTestCase):
    config_changes = {"api_keys_enabled": True}

    def setUp(self) -> None:
        super().setUp()
        self.minter_id = self.admin_key.split(".")[0]

    def allow(self, key_id: str, on: bool = True, cookie: str = "") -> tuple[int, dict]:
        cookie = cookie or self.owner_cookie
        return self.call("POST", f"/api/keys/{key_id}/mint-keys", cookie=cookie,
                         body={"csrf_token": self.csrf(cookie), "may_mint_keys": on})

    def mint(self, key: str, user_id: int, role: str = "user", days: int = 30) -> tuple[int, dict]:
        return self.call("POST", f"/api/admin/users/{user_id}/keys", key=key,
                         body={"name": "portal", "role": role, "expires_in_days": days})

    def test_a_key_needs_the_owners_say_so(self) -> None:
        self.assertEqual(self.mint(self.admin_key, self.user.id), (403, {"error": "key_minting_off"}))
        self.assertEqual(self.call("GET", f"/api/admin/users/{self.user.id}/keys", key=self.admin_key), (403, {"error": "key_minting_off"}))
        status, row = self.allow(self.minter_id)
        self.assertEqual((status, row["may_mint_keys"]), (200, True))
        status, minted = self.mint(self.admin_key, self.user.id)
        self.assertEqual(status, 201)
        self.assertEqual(minted["minted_by_key"], self.minter_id)
        self.assertTrue(minted["credential"])
        _, listed = self.call("GET", f"/api/admin/users/{self.user.id}/keys", key=self.admin_key)
        self.assertEqual([key["minted_by_key"] for key in listed["keys"]], [self.minter_id])

    def test_only_the_owner_on_an_admin_key_from_a_session(self) -> None:
        other_admin_key, other = api_keys.issue_api_key(self.store, self.admin.id, "theirs", users.ROLE_ADMIN, 3600)
        self.assertEqual(self.allow(other.id, cookie=self.admin_cookie)[0], 403)
        self.assertEqual(self.allow(self.user_key.split(".")[0])[0], 400)
        # Never from a key, not even the owner's own.
        status, _ = self.call("POST", f"/api/keys/{self.minter_id}/mint-keys", key=self.admin_key, body={"may_mint_keys": True})
        self.assertEqual(status, 403)

    def test_role_is_capped_and_the_owner_is_off_limits(self) -> None:
        self.allow(self.minter_id)
        _, minted = self.mint(self.admin_key, self.user.id, role="admin")
        self.assertEqual(minted["role"], "user")
        self.assertEqual(self.mint(self.admin_key, self.owner.id)[0], 403)
        self.assertEqual(self.mint(self.admin_key, self.user.id, days=0)[0], 400)
        self.assertEqual(self.mint(self.admin_key, self.user.id, days=366)[0], 400)
        owner_key = self.user_key.split(".")[0]
        self.assertEqual(self.call("POST", f"/api/admin/keys/{owner_key}/revoke", key=self.admin_key, body={}), (403, {"error": "the owner's keys cannot be minted or revoked this way"}))

    def test_a_minted_key_never_mints_or_signs_in(self) -> None:
        self.allow(self.minter_id)
        _, minted = self.mint(self.admin_key, self.admin.id, role="admin")
        self.assertEqual(self.mint(minted["credential"], self.user.id), (403, {"error": "key_minting_off"}))
        with self.assertRaises(api_keys.APIKeyMintedError):
            api_keys.set_api_key_sign_in(self.store, minted["id"], self.admin.id, True)

    def test_revoking_cascades_down_the_whole_chain(self) -> None:
        self.allow(self.minter_id)
        _, child = self.mint(self.admin_key, self.admin.id, role="admin")
        # A grandchild, as a shell or a later hop would leave it.
        _, grandchild = api_keys.issue_api_key(self.store, self.user.id, "deep", users.ROLE_USER, 3600, minted_by_key=child["id"])
        _, sibling = self.mint(self.admin_key, self.user.id)
        status, _ = self.call("POST", f"/api/admin/keys/{child['id']}/revoke", key=self.admin_key, body={})
        self.assertEqual(status, 200)
        self.assertTrue(api_keys.get_api_key(self.store, child["id"]).revoked)
        self.assertTrue(api_keys.get_api_key(self.store, grandchild.id).revoked)
        self.assertFalse(api_keys.get_api_key(self.store, sibling["id"]).revoked)
        # Revoking the minter takes everything it led to.
        api_keys.revoke_api_key(self.store, self.minter_id)
        self.assertTrue(api_keys.get_api_key(self.store, sibling["id"]).revoked)
        self.assertEqual(self.call("GET", "/api/me", key=sibling["credential"])[0], 401)

    def test_deleting_cascades_too(self) -> None:
        self.allow(self.minter_id)
        _, minted = self.mint(self.admin_key, self.user.id)
        api_keys.delete_api_key(self.store, self.minter_id, None)
        self.assertTrue(api_keys.get_api_key(self.store, minted["id"]).revoked)
