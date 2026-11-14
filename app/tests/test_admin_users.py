"""Admins editing other accounts: who may touch whom, and what a change of role
does to what the account already holds. Go's twin is
server/routes/admin_test.go."""
from __future__ import annotations

import unittest
from datetime import timedelta
from typing import Any

from app.models import login_tokens, users
from app.models import api_keys
from app.models import invite_links
from app.models.sign_in import SignInRules
from app.tests.route_support import RoutesTestCase, TestClient


class EditUsersTest(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.admin_cookie = self.session(self.admin.id)

    def post(self, cookie: str, user_id: int, verb: str, **body: Any) -> tuple[int, Any]:
        path = f"/api/admin/users/{user_id}/{verb}"
        return self.call("POST", path, cookie=cookie, body={**body, "csrf_token": self.csrf(cookie)})

    def test_renaming_someone_else(self) -> None:
        status, reply = self.post(self.owner_cookie, self.user.id, "rename", display_name="  Alice B  ")
        self.assertEqual((status, reply["display_name"]), (200, "Alice B"))
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "rename", display_name="  ")[0], 400)
        self.assertEqual(self.post(self.user_cookie, self.user.id, "rename", display_name="x")[0], 403)

        # An undo that finds a different name leaves it alone, and says what is there.
        status, reply = self.post(self.owner_cookie, self.user.id, "rename", display_name="old", expect="stale")
        self.assertEqual((status, reply["display_name"]), (409, "Alice B"))

        self.assertEqual(self.post(self.owner_cookie, 9999, "rename", display_name="x")[0], 404)

    def test_only_the_owner_renames_an_admin(self) -> None:
        self.assertEqual(self.post(self.admin_cookie, self.user.id, "rename", display_name="fine")[0], 200)
        self.assertEqual(self.post(self.admin_cookie, self.owner.id, "rename", display_name="x")[0], 403)
        self.assertEqual(self.post(self.admin_cookie, self.admin.id, "rename", display_name="x")[0], 403)
        self.assertEqual(self.post(self.owner_cookie, self.admin.id, "rename", display_name="Sam")[0], 200)

    def test_becoming_an_admin_ends_what_was_open(self) -> None:
        credential = login_tokens.issue_login_token(self.store, self.user.id, 3600)
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "role", role="owner")[0], 400)
        self.assertEqual(self.post(self.user_cookie, self.user.id, "role", role="admin")[0], 403)
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "role", role="admin")[0], 200)

        self.assertTrue(users.get_user(self.store, self.user.id).is_admin)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[0], 401)
        self.assertIsNone(login_tokens.redeem_login_token(self.store, credential, SignInRules(3600)))
        status, reply = self.call("GET", "/api/me", cookie=self.session(self.user.id))
        self.assertEqual((status, reply["role"]), (200, "admin"))

    def test_granting_showing(self) -> None:
        self.assertEqual(self.post(self.user_cookie, self.user.id, "showing", can_show_others=True, default_subject=None)[0], 403)
        status, reply = self.call("POST", f"/api/admin/users/{self.user.id}/showing", cookie=self.owner_cookie, body={"can_show_others": True})
        self.assertEqual(status, 403)  # no csrf token
        self.assertEqual(self.post(self.owner_cookie, 9999, "showing", can_show_others=True, default_subject=None)[0], 404)
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "showing", can_show_others=True, default_subject=9999)[0], 404)
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "showing", can_show_others="yes", default_subject=None)[0], 400)

        status, reply = self.post(self.admin_cookie, self.user.id, "showing", can_show_others=True, default_subject=self.owner.id)
        self.assertEqual((status, reply["can_show_others"], reply["default_subject"]), (200, True, self.owner.id))
        row = next(row for row in self.call("GET", "/api/admin/users?q=", cookie=self.owner_cookie)[1]["users"] if row["id"] == self.user.id)
        self.assertEqual((row["can_show_others"], row["default_subject"]), (True, self.owner.id))

        # Starting on yourself is the same as your own lists.
        status, reply = self.post(self.owner_cookie, self.user.id, "showing", can_show_others=True, default_subject=self.user.id)
        self.assertEqual((status, reply["default_subject"]), (200, None))

        # Choosing someone to start on grants Showing, since it needs it.
        status, reply = self.post(self.owner_cookie, self.user.id, "showing", can_show_others=False, default_subject=self.owner.id)
        self.assertEqual((status, reply["can_show_others"], reply["default_subject"]), (200, True, self.owner.id))
        # No one chosen and the box cleared takes it away again.
        status, reply = self.post(self.owner_cookie, self.user.id, "showing", can_show_others=False, default_subject=None)
        self.assertEqual((status, reply["can_show_others"], reply["default_subject"]), (200, False, None))

    def test_locking_showing(self) -> None:
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "showing", can_show_others=True, default_subject=None, showing_locked="yes")[0], 400)
        self.assertEqual(self.post(self.user_cookie, self.user.id, "showing", can_show_others=True, default_subject=None, showing_locked=True)[0], 403)
        status, reply = self.post(self.owner_cookie, self.user.id, "showing", can_show_others=True, default_subject=self.owner.id, showing_locked=True)
        self.assertEqual((status, reply["showing_locked"]), (200, True))
        row = next(row for row in self.call("GET", "/api/admin/users?q=", cookie=self.owner_cookie)[1]["users"] if row["id"] == self.user.id)
        self.assertTrue(row["showing_locked"])
        self.assertTrue(self.call("GET", "/api/me", cookie=self.user_cookie)[1]["showing_locked"])
        # Left out, the lock comes off.
        status, reply = self.post(self.owner_cookie, self.user.id, "showing", can_show_others=True, default_subject=self.owner.id)
        self.assertEqual((status, reply["showing_locked"]), (200, False))
        # Nothing to lock without Showing and no one chosen.
        status, reply = self.post(self.owner_cookie, self.user.id, "showing", can_show_others=False, default_subject=None, showing_locked=True)
        self.assertEqual((status, reply["showing_locked"]), (200, False))

    def test_asking_for_the_role_they_have_changes_nothing(self) -> None:
        self.assertEqual(self.post(self.owner_cookie, self.user.id, "role", role="user")[0], 200)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[0], 200)

    def test_losing_admin_rights_applies_at_once(self) -> None:
        credential, _ = invite_links.issue_invite_link(self.store, "Club", 5, timedelta(hours=1), self.admin.id)
        self.assertEqual(self.post(self.owner_cookie, self.admin.id, "role", role="user")[0], 200)

        # Still signed in, but as a user, and the link they made has stopped.
        status, reply = self.call("GET", "/api/me", cookie=self.admin_cookie)
        self.assertEqual((status, reply["role"]), (200, "user"))
        self.assertEqual(self.call("GET", "/api/admin/users", cookie=self.admin_cookie)[0], 403)
        with self.assertRaises(invite_links.InviteLinkInvalidError):
            invite_links.load_invite_link(self.store, credential)

        # Made an admin again, the link is back, as the screen's question says.
        self.assertEqual(self.post(self.owner_cookie, self.admin.id, "role", role="admin")[0], 200)
        self.assertIsNotNone(invite_links.load_invite_link(self.store, credential))

    def test_who_may_change_whose_role(self) -> None:
        third = users.create_user(self.store, "Third", users.ROLE_ADMIN)
        cases = (
            (self.owner_cookie, self.owner.id, "user", 400),  # yourself
            (self.admin_cookie, self.admin.id, "user", 400),  # yourself
            (self.admin_cookie, self.owner.id, "user", 403),  # the owner
            (self.admin_cookie, third.id, "user", 403),  # another admin
            (self.admin_cookie, self.user.id, "admin", 200),  # anyone may make one
        )
        for cookie, target, role, want in cases:
            with self.subTest(target=target, role=role):
                self.assertEqual(self.post(cookie, target, "role", role=role)[0], want)
        self.assertEqual(self.post(self.owner_cookie, 9999, "role", role="admin")[0], 404)

    def test_only_the_owner_hands_out_an_admins_login_link(self) -> None:
        """S1: a login link is a way in, so reissuing or cancelling one follows
        the owner rule. Before this, any admin could mint the owner a link and
        sign in as the owner."""
        third = users.create_user(self.store, "Third", users.ROLE_ADMIN)
        for verb in ("reissue-login", "cancel-login-link"):
            for target in (self.owner.id, third.id):
                with self.subTest(verb=verb, target=target):
                    status, reply = self.post(self.admin_cookie, target, verb)
                    self.assertEqual(status, 403, reply)
                    self.assertNotIn("login_path", reply)
            self.assertEqual(self.post(self.admin_cookie, self.user.id, verb)[0], 200)
        # The owner still reissues an admin's link, and it signs in.
        status, reply = self.post(self.owner_cookie, third.id, "reissue-login")
        self.assertEqual(status, 200, reply)
        credential = reply["login_path"].removeprefix("/login/")
        self.assertEqual(self.call("POST", "/api/login", body={"credential": credential})[0], 200)
        self.assertEqual(self.post(self.owner_cookie, third.id, "cancel-login-link")[0], 200)

    def test_only_the_owner_disables_or_revokes_an_admin(self) -> None:
        """S3: disabling and revoking another admin follow the owner rule too,
        so a non-owner admin cannot lock a peer out."""
        third = users.create_user(self.store, "Third", users.ROLE_ADMIN)
        third_cookie = self.session(third.id)
        self.assertEqual(self.post(self.admin_cookie, third.id, "disabled", disabled=True)[0], 403)
        self.assertEqual(self.post(self.admin_cookie, third.id, "revoke-access")[0], 403)
        self.assertFalse(users.get_user(self.store, third.id).disabled)
        self.assertEqual(self.call("GET", "/api/me", cookie=third_cookie)[0], 200)

        # Any admin still does both to an ordinary user; the owner to an admin.
        self.assertEqual(self.post(self.admin_cookie, self.user.id, "disabled", disabled=True)[0], 200)
        self.assertEqual(self.post(self.admin_cookie, self.user.id, "revoke-access")[0], 200)
        self.assertEqual(self.post(self.owner_cookie, third.id, "disabled", disabled=True)[0], 200)
        # Switching an admin back on is the owner's too.
        self.assertEqual(self.post(self.admin_cookie, third.id, "disabled", disabled=False)[0], 403)
        self.assertEqual(self.post(self.owner_cookie, third.id, "revoke-access")[0], 200)

    def test_an_admin_key_cannot_reissue_the_owners_link(self) -> None:
        third = users.create_user(self.store, "Third", users.ROLE_ADMIN)
        key, _ = api_keys.issue_api_key(self.store, self.admin.id, "ops", users.ROLE_ADMIN, 3600)
        for verb in ("reissue-login", "cancel-login-link"):
            for target in (self.owner.id, third.id):
                with self.subTest(verb=verb, target=target):
                    status, reply = self.by_key(key, f"/api/admin/users/{target}/{verb}")
                    self.assertEqual(status, 403, reply)
                    self.assertNotIn("login_path", reply)
        self.assertEqual(self.by_key(key, f"/api/admin/users/{self.user.id}/reissue-login")[0], 200)

    def by_key(self, key: str, path: str, **body: Any) -> tuple[int, Any]:
        return self.call("POST", path, key=key, body=body)

    def signs_in(self, login_path: str) -> bool:
        credential = login_path.removeprefix("/login/")
        return self.call("POST", "/api/login", body={"credential": credential})[0] == 200

    def test_an_admin_key_manages_accounts(self) -> None:
        status, reply = self.by_key(self.admin_key, "/api/admin/users", display_name="Bob", role="user")
        self.assertEqual(status, 201, reply)
        self.assertTrue(self.signs_in(reply["login_path"]), "the new account's link did not sign in")

        status, reply = self.by_key(self.admin_key, f"/api/admin/users/{self.user.id}/reissue-login")
        self.assertEqual(status, 200, reply)
        self.assertTrue(self.signs_in(reply["login_path"]), "the reissued link did not sign in")

        self.assertEqual(self.by_key(self.admin_key, f"/api/admin/users/{self.user.id}/rename", display_name="Alicia")[0], 200)
        self.assertEqual(self.by_key(self.admin_key, f"/api/admin/users/{self.user.id}/role", role="admin")[0], 200)
        # The owner rules hold through a key as through a browser.
        self.assertEqual(self.by_key(self.admin_key, f"/api/admin/users/{self.owner.id}/delete")[0], 400)
        self.assertEqual(self.by_key(self.admin_key, f"/api/admin/users/{self.user.id}/delete")[0], 200)

        # A user-scoped key on the same admin account is not an admin.
        self.assertEqual(self.by_key(self.user_key, "/api/admin/users", display_name="Eve", role="admin")[0], 403)

    def test_only_a_full_role_key_makes_its_own_login_link(self) -> None:
        """A login link becomes a full-role session, so only a key carrying the
        account's full role may make one for its own account."""
        status, reply = self.by_key(self.user_key, "/api/account/login-link")
        self.assertEqual(status, 403)
        self.assertIn("less than your account's role", reply["error"])
        full_key, _ = api_keys.issue_api_key(self.store, self.user.id, "full", users.ROLE_USER, 3600)
        status, reply = self.by_key(full_key, "/api/account/login-link")
        self.assertEqual(status, 200, reply)
        self.assertTrue(self.signs_in(reply["login_path"]))

    def test_revoking_a_key_voids_the_links_it_made(self) -> None:
        """Revoking or deleting a key voids the login links it made that are
        still unused; a link a person made in the browser is left alone."""
        for how in ("revoke", "delete"):
            with self.subTest(how):
                credential, key = api_keys.issue_api_key(self.store, self.owner.id, how, users.ROLE_ADMIN, 3600)
                _, made_by_key = self.by_key(credential, "/api/admin/users", display_name="Bob", role="user")
                _, made_by_person = self.post(self.owner_cookie, self.user.id, "reissue-login")
                if how == "revoke":
                    api_keys.revoke_api_key(self.store, key.id)
                else:
                    api_keys.delete_api_key(self.store, key.id, self.owner.id)
                self.assertFalse(self.signs_in(made_by_key["login_path"]), "the key's link still signs in")
                self.assertTrue(self.signs_in(made_by_person["login_path"]), "a person's link stopped working")


    def test_revoking_a_key_ends_the_sessions_its_links_made(self) -> None:
        """S8: a browser signed in through a link a key made is signed out
        when the key is revoked or deleted; one signed in through a person's
        link is not. Before, the session outlived the key that made its way
        in."""
        for how in ("revoke", "delete"):
            with self.subTest(how):
                credential, key = api_keys.issue_api_key(self.store, self.owner.id, how, users.ROLE_ADMIN, 3600)
                _, by_key = self.by_key(credential, f"/api/admin/users/{self.user.id}/reissue-login", max_uses=2)
                # https, or the Secure session cookie is dropped and this
                # browser was never signed in at all.
                through_key = TestClient(self.app, base_url="https://testserver")
                link = by_key["login_path"].removeprefix("/login/")
                self.assertEqual(through_key.post("/api/login", json={"credential": link}).status_code, 200)
                self.assertEqual(through_key.get("/api/me").status_code, 200, "the key's link did not sign in")
                by_person = self.session(self.user.id)
                if how == "revoke":
                    api_keys.revoke_api_key(self.store, key.id)
                else:
                    api_keys.delete_api_key(self.store, key.id, self.owner.id)
                self.assertEqual(through_key.get("/api/me").status_code, 401, "the key's session is still signed in")
                self.assertEqual(self.call("GET", "/api/me", cookie=by_person)[0], 200, "a person's session was signed out")
                if how == "delete":
                    api_keys.restore_api_key(self.store, key.id, self.owner.id, True)
                    self.assertEqual(through_key.get("/api/me").status_code, 401, "restoring the key restored its session")

if __name__ == "__main__":
    unittest.main()
