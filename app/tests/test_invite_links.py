"""Editing an invite link after it is made: its label, places and expiry, and
switching it back on."""
from __future__ import annotations

import unittest
from datetime import timedelta

from app.core.db import BUCKET_INVITE_LINKS
from app.models import invite_links, to_iso, utc_now
from app.models import api_keys, users
from app.tests.route_support import RoutesTestCase


class EditInviteLinkTest(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.credential, self.link = invite_links.issue_invite_link(
            self.store, "Book club", 10, timedelta(days=1), self.owner.id
        )
        self.base = f"/api/admin/invite-links/{self.link.id}"

    def post(self, cookie: str, route: str, **body: object) -> tuple[int, dict]:
        return self.call("POST", self.base + route, cookie=cookie, body={"csrf_token": self.csrf(cookie), **body})

    def stored(self) -> invite_links.InviteLink:
        return invite_links.get_invite_link(self.store, self.link.id)

    def join(self, name: str) -> None:
        invite_links.join_invite_link(self.store, self.credential, name, 3600)

    def test_renaming(self) -> None:
        status, reply = self.post(self.owner_cookie, "/rename", label="  Choir  ")
        self.assertEqual((status, reply["label"]), (200, "Choir"))
        self.assertEqual(self.post(self.user_cookie, "/rename", label="x")[0], 403)
        self.assertEqual(self.post(self.owner_cookie, "/rename", label="  ")[0], 400)

        # An undo that finds a different label leaves it alone, and says what is there.
        status, reply = self.post(self.owner_cookie, "/rename", label="old", expect="stale")
        self.assertEqual((status, reply["label"]), (409, "Choir"))

        invite_links.delete_invite_link(self.store, self.link.id, self.owner.id)
        self.assertEqual(self.post(self.owner_cookie, "/rename", label="gone")[0], 404)

    def test_changing_the_limits(self) -> None:
        self.join("Ann")
        self.join("Bo")
        for bad in ({}, {"max_uses": 1001}, {"max_uses": 5, "days": 0}, {"max_uses": 5, "days": 366}, {"max_uses": True}):
            with self.subTest(bad):
                self.assertEqual(self.post(self.owner_cookie, "/limits", **bad)[0], 400)

        # Nobody can be left over the limit.
        self.assertEqual(self.post(self.owner_cookie, "/limits", max_uses=1)[0], 400)

        # Leaving days out keeps the expiry.
        status, reply = self.post(self.owner_cookie, "/limits", max_uses=2)
        self.assertEqual((status, reply["remaining"]), (200, 0))
        self.assertEqual(self.stored().expires_at, self.link.expires_at)
        with self.assertRaises(invite_links.InviteLinkFullError):
            self.join("Cy")

        self.assertEqual(self.post(self.owner_cookie, "/limits", max_uses=3, days=30)[0], 200)
        self.assertGreater(self.stored().expires_at, utc_now() + timedelta(days=29))
        self.join("Cy")

    def test_an_expired_link_can_be_extended(self) -> None:
        """A replacement would lock out the people who joined."""

        def lapse(record: dict) -> None:
            record["expires_at"] = to_iso(utc_now() - timedelta(minutes=1))

        self.store.update_value(BUCKET_INVITE_LINKS, self.link.id, lapse)
        with self.assertRaises(invite_links.InviteLinkInvalidError):
            invite_links.load_invite_link(self.store, self.credential)
        self.assertEqual(self.post(self.owner_cookie, "/limits", max_uses=10, days=7)[0], 200)
        invite_links.load_invite_link(self.store, self.credential)

    def test_switching_back_on(self) -> None:
        invite_links.revoke_invite_link(self.store, self.link.id)
        with self.assertRaises(invite_links.InviteLinkInvalidError):
            invite_links.load_invite_link(self.store, self.credential)
        self.assertEqual(self.post(self.user_cookie, "/switch-on")[0], 403)

        status, reply = self.post(self.owner_cookie, "/switch-on")
        self.assertEqual(status, 200)
        self.assertIs(reply["live"], True)
        invite_links.load_invite_link(self.store, self.credential)

        invite_links.delete_invite_link(self.store, self.link.id, self.owner.id)
        self.assertEqual(self.post(self.owner_cookie, "/switch-on")[0], 404)

    def test_a_key_that_reopens_or_grows_a_link_owns_it(self) -> None:
        credential, key = api_keys.issue_api_key(self.store, self.owner.id, "script", users.ROLE_ADMIN, 3600)
        invite_links.revoke_invite_link(self.store, self.link.id)
        for route, body in (("/rename", {"label": "x"}), ("/limits", {"max_uses": 999}), ("/switch-on", {})):
            with self.subTest(route):
                status, reply = self.call("POST", self.base + route, key=credential, body=body)
                self.assertEqual(status, 200, reply)
        stored = self.stored()
        self.assertIsNone(stored.revoked_at)
        self.assertEqual((stored.max_uses, stored.label, stored.minted_by_key), (999, "x", key.id))

        # The link is the key's now: revoking the key switches it off again.
        api_keys.revoke_api_key(self.store, key.id)
        self.assertIsNotNone(self.stored().revoked_at)

    def test_deleting_a_key_switches_off_the_invite_links_it_made(self) -> None:
        credential, key = api_keys.issue_api_key(self.store, self.owner.id, "script", users.ROLE_ADMIN, 3600)
        status, reply = self.call("POST", "/api/admin/invite-links", key=credential, body={"label": "Club", "max_uses": 5, "days": 1})
        self.assertEqual(status, 201, reply)
        join = reply["join_path"].removeprefix("/join/")
        api_keys.delete_api_key(self.store, key.id, self.owner.id)
        with self.assertRaises(invite_links.InviteLinkInvalidError):
            invite_links.load_invite_link(self.store, join)
        self.assertIsNone(self.stored().revoked_at, "a person's invite link was switched off")


if __name__ == "__main__":
    unittest.main()
