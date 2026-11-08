"""Making a key that acts as someone else (POST /api/admin/keys): who may do it
for whom, that the key acts as them, and that they can see who made it."""
from __future__ import annotations

import unittest
from datetime import timedelta

from app.core.db import BUCKET_API_KEYS
from app.models import api_keys, to_iso, users, utc_now
from app.tests.route_support import RoutesTestCase


class MintForTest(RoutesTestCase):
    def mint(self, cookie: str, user_id: int, role: str = "user") -> tuple[int, dict]:
        return self.call("POST", "/api/admin/keys", cookie=cookie, body={
            "csrf_token": self.csrf(cookie), "user_id": user_id, "name": "deploy", "role": role,
        })

    def test_who_may_mint_for_whom(self) -> None:
        third = users.create_user(self.store, "Third admin", users.ROLE_ADMIN)
        cases = [
            ("an admin for a user", self.admin_cookie, self.user.id, "user", 201),
            ("the owner for a user", self.owner_cookie, self.user.id, "user", 201),
            ("the owner for an admin", self.owner_cookie, self.admin.id, "admin", 201),
            ("an admin for themselves", self.admin_cookie, self.admin.id, "admin", 201),
            ("an admin for another admin", self.admin_cookie, third.id, "user", 403),
            ("an admin for the owner", self.admin_cookie, self.owner.id, "user", 403),
            ("an admin role for a user", self.owner_cookie, self.user.id, "admin", 403),
            ("a user for anyone", self.user_cookie, self.admin.id, "user", 403),
            ("nobody there", self.admin_cookie, 99999, "user", 404),
        ]
        for name, cookie, target, role, status in cases:
            with self.subTest(name):
                self.assertEqual(self.mint(cookie, target, role)[0], status)

    def test_a_key_made_for_someone_acts_as_them_and_says_who_made_it(self) -> None:
        status, reply = self.mint(self.owner_cookie, self.user.id)
        self.assertEqual(status, 201)
        self.assertEqual(reply["created_by"], self.owner.id)
        self.assertEqual(self.call("GET", "/api/me", key=reply["credential"])[1]["id"], self.user.id)

        _, page = self.call("GET", "/api/keys", cookie=self.user_cookie)
        self.assertEqual(len(page["keys"]), 1)
        self.assertEqual(page["keys"][0]["created_by_name"], "Owner")
        self.assertNotIn("secret_hash", page["keys"][0])

    def test_a_key_cannot_mint_a_key_for_anyone(self) -> None:
        status, _ = self.call("POST", "/api/admin/keys", key=self.admin_key, body={"user_id": self.user.id, "name": "x"})
        self.assertEqual(status, 403)
        self.assertEqual(api_keys.list_api_keys_for_user(self.store, self.user.id), [])

    def test_a_shell_still_mints_for_the_owner(self) -> None:
        _, key = api_keys.issue_api_key(self.store, self.owner.id, "script", users.ROLE_ADMIN, 3600)
        self.assertIsNone(key.created_by)

    def test_a_row_from_before_the_field_still_loads(self) -> None:
        _, key = api_keys.issue_api_key(self.store, self.owner.id, "old", users.ROLE_USER, 3600)
        record = key.to_record()
        del record["created_by"]
        self.assertIsNone(api_keys.APIKey.from_record(record).created_by)


class EditKeyTest(RoutesTestCase):
    def post(self, cookie: str, path: str, **body: object) -> tuple[int, dict]:
        return self.call("POST", path, cookie=cookie, body={"csrf_token": self.csrf(cookie), **body})

    def issued(self, user_id: int) -> api_keys.APIKey:
        return api_keys.issue_api_key(self.store, user_id, "deploy", users.ROLE_USER, 3600)[1]

    def test_renaming_a_key(self) -> None:
        key = self.issued(self.user.id)
        path = f"/api/keys/{key.id}/rename"

        status, reply = self.post(self.user_cookie, path, name="  bot  ")
        self.assertEqual((status, reply["name"]), (200, "bot"))

        # Someone else's key is not there, even for an admin on the own-keys route.
        self.assertEqual(self.post(self.admin_cookie, path, name="x")[0], 404)
        self.assertEqual(self.post(self.user_cookie, path, name="   ")[0], 400)

        # An undo that finds a different name leaves it alone, and says what is there.
        status, reply = self.post(self.user_cookie, path, name="old", expect="stale")
        self.assertEqual((status, reply["name"]), (409, "bot"))

        status, _ = self.post(self.admin_cookie, f"/api/admin/keys/{key.id}/rename", name="by admin", expect="bot")
        self.assertEqual(status, 200)
        self.assertEqual(api_keys.get_api_key(self.store, key.id).name, "by admin")

        # A dead key keeps its history readable, so it can be tidied; a deleted one is gone.
        api_keys.revoke_api_key(self.store, key.id)
        self.assertEqual(self.post(self.user_cookie, path, name="retired")[0], 200)
        api_keys.delete_api_key(self.store, key.id, self.user.id)
        self.assertEqual(self.post(self.user_cookie, path, name="gone")[0], 404)

    def test_who_may_change_a_keys_expiry(self) -> None:
        third = users.create_user(self.store, "Third admin", users.ROLE_ADMIN)
        cases = [
            ("your own", self.user_cookie, self.user.id, "/api/keys/", 200),
            ("an admin's own, as an admin", self.admin_cookie, self.admin.id, "/api/admin/keys/", 200),
            ("an admin for a user", self.admin_cookie, self.user.id, "/api/admin/keys/", 200),
            ("the owner for an admin", self.owner_cookie, self.admin.id, "/api/admin/keys/", 200),
            ("an admin for another admin", self.admin_cookie, third.id, "/api/admin/keys/", 403),
            ("an admin for the owner", self.admin_cookie, self.owner.id, "/api/admin/keys/", 403),
            ("a user on the admin route", self.user_cookie, self.admin.id, "/api/admin/keys/", 403),
            ("someone else's on the own route", self.user_cookie, self.admin.id, "/api/keys/", 404),
        ]
        for name, cookie, holder, prefix, status in cases:
            with self.subTest(name):
                key = self.issued(holder)
                self.assertEqual(self.post(cookie, f"{prefix}{key.id}/expiry", expires_in_days=30)[0], status)
                stored = api_keys.get_api_key(self.store, key.id)
                self.assertEqual(stored.expires_at > key.expires_at + timedelta(days=1), status == 200)

    def test_changing_a_keys_expiry(self) -> None:
        key = self.issued(self.user.id)
        path = f"/api/keys/{key.id}/expiry"
        for bad in ({}, {"expires_in_days": -1}, {"expires_in_days": 3651}, {"expires_in_days": True}):
            with self.subTest(bad):
                self.assertEqual(self.post(self.user_cookie, path, **bad)[0], 400)

        status, reply = self.post(self.user_cookie, path, expires_in_days=0)
        self.assertEqual(status, 200)
        self.assertNotIn("expires_at", reply)

        # Revoking is final, so an edit cannot be the way back.
        api_keys.revoke_api_key(self.store, key.id)
        self.assertEqual(self.post(self.user_cookie, path, expires_in_days=30)[0], 400)

        # Nor round an expiry.
        expired = self.issued(self.user.id)

        def lapse(record: dict) -> None:
            record["expires_at"] = to_iso(utc_now() - timedelta(minutes=1))

        self.store.update_value(BUCKET_API_KEYS, expired.id, lapse)
        self.assertEqual(self.post(self.user_cookie, f"/api/keys/{expired.id}/expiry", expires_in_days=30)[0], 400)

    def test_a_key_cannot_extend_itself(self) -> None:
        credential, key = api_keys.issue_api_key(self.store, self.owner.id, "script", users.ROLE_ADMIN, 3600)
        for prefix in ("/api/keys/", "/api/admin/keys/"):
            with self.subTest(prefix):
                status, _ = self.call("POST", f"{prefix}{key.id}/expiry", key=credential, body={"expires_in_days": 0})
                self.assertEqual(status, 403)
        self.assertIsNotNone(api_keys.get_api_key(self.store, key.id).expires_at)


if __name__ == "__main__":
    unittest.main()
