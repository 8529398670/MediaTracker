"""Admins editing other accounts: who may touch whom, and what a change of role
does to what the account already holds. Go's twin is
server/routes/admin_test.go."""
from __future__ import annotations

import unittest
from datetime import timedelta
from typing import Any

from app.models import login_tokens, users
from app.models import invite_links
from app.models.sign_in import SignInRules
from app.tests.route_support import RoutesTestCase


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

    def test_an_admin_key_cannot_change_an_account(self) -> None:
        for verb in ("rename", "role"):
            status, _ = self.call("POST", f"/api/admin/users/{self.user.id}/{verb}", key=self.admin_key, body={"display_name": "x", "role": "admin"})
            self.assertEqual(status, 403, verb)


if __name__ == "__main__":
    unittest.main()
