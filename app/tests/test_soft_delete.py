"""Deleting an API key or invite link is undoable for RESTORE_WINDOW (see
app/models/__init__.py). What matters, and what these pin down: a deleted
row is dead at once, only the right people can bring it back, only for a
while, and the purge removes it once the window has passed."""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.core import db
from app.core.db import BUCKET_API_KEYS, BUCKET_INVITE_LINKS
from app.models import (
    RESTORE_WINDOW,
    RestoreExpiredError,
    RestoreForbiddenError,
    RestoreGoneError,
    api_keys,
    invite_links,
    to_iso,
    users,
    utc_now,
)


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = db.Store(Path(self.directory.name) / "app.db", "", False)
        self.store.initialise()
        self.admin = users.create_user(self.store, "Admin", users.ROLE_ADMIN)
        self.alice = users.create_user(self.store, "Alice", users.ROLE_USER)
        self.bob = users.create_user(self.store, "Bob", users.ROLE_USER)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def backdate(self, bucket: str, key: str) -> None:
        """Move a deletion to just past the restore window."""

        def mutate(record: dict) -> None:
            record["deleted_at"] = to_iso(utc_now() - RESTORE_WINDOW - timedelta(seconds=1))

        self.store.update_value(bucket, key, mutate)


class APIKeySoftDeleteTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.credential, self.key = api_keys.issue_api_key(self.store, self.alice.id, "ci", users.ROLE_USER, 0)

    def test_deleted_key_is_refused_and_hidden_at_once(self) -> None:
        self.assertTrue(api_keys.delete_api_key(self.store, self.key.id, self.alice.id))
        self.assertIsNone(api_keys.load_api_key(self.store, self.credential))
        self.assertEqual(api_keys.list_api_keys_for_user(self.store, self.alice.id), [])
        self.assertEqual(api_keys.list_api_keys(self.store), [])
        self.assertEqual(api_keys.count_live_api_keys_for_user(self.store, self.alice.id), 0)

    def test_deleting_twice_is_not_found(self) -> None:
        api_keys.delete_api_key(self.store, self.key.id, self.alice.id)
        self.assertFalse(api_keys.delete_api_key(self.store, self.key.id, self.alice.id))

    def test_restore_inside_the_window_brings_it_back_working(self) -> None:
        api_keys.delete_api_key(self.store, self.key.id, self.alice.id)
        api_keys.restore_api_key(self.store, self.key.id, self.alice.id, False)
        self.assertIsNotNone(api_keys.load_api_key(self.store, self.credential))
        self.assertEqual([key.id for key in api_keys.list_api_keys_for_user(self.store, self.alice.id)], [self.key.id])

    def test_restore_after_the_window_is_refused(self) -> None:
        api_keys.delete_api_key(self.store, self.key.id, self.alice.id)
        self.backdate(BUCKET_API_KEYS, self.key.id)
        with self.assertRaises(RestoreExpiredError):
            api_keys.restore_api_key(self.store, self.key.id, self.alice.id, False)
        self.assertIsNone(api_keys.load_api_key(self.store, self.credential))

    def test_only_the_deleter_or_an_admin_may_restore(self) -> None:
        api_keys.delete_api_key(self.store, self.key.id, self.admin.id)
        with self.assertRaises(RestoreForbiddenError):
            api_keys.restore_api_key(self.store, self.key.id, self.alice.id, False)
        api_keys.restore_api_key(self.store, self.key.id, self.admin.id, True)
        self.assertIsNotNone(api_keys.load_api_key(self.store, self.credential))

    def test_restoring_a_key_that_is_not_deleted_is_refused(self) -> None:
        with self.assertRaises(RestoreGoneError):
            api_keys.restore_api_key(self.store, self.key.id, self.alice.id, False)

    def test_restore_keeps_the_live_key_cap(self) -> None:
        api_keys.delete_api_key(self.store, self.key.id, self.alice.id)
        for index in range(api_keys.API_KEY_MAX_PER_USER):
            api_keys.issue_api_key(self.store, self.alice.id, f"k{index}", users.ROLE_USER, 0)
        with self.assertRaises(api_keys.APIKeyLimitError):
            api_keys.restore_api_key(self.store, self.key.id, self.alice.id, False)

    def test_purge_removes_only_expired_deletions(self) -> None:
        _, recent = api_keys.issue_api_key(self.store, self.bob.id, "recent", users.ROLE_USER, 0)
        api_keys.delete_api_key(self.store, self.key.id, self.alice.id)
        api_keys.delete_api_key(self.store, recent.id, self.bob.id)
        self.backdate(BUCKET_API_KEYS, self.key.id)
        self.assertEqual(api_keys.purge_dead_api_keys(self.store), 1)
        self.assertIsNone(api_keys.get_api_key(self.store, self.key.id))
        self.assertIsNotNone(api_keys.get_api_key(self.store, recent.id))

    def test_purge_api_key_is_a_hard_delete(self) -> None:
        self.assertTrue(api_keys.purge_api_key(self.store, self.key.id))
        self.assertIsNone(api_keys.get_api_key(self.store, self.key.id))


class InviteLinkSoftDeleteTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.credential, self.link = invite_links.issue_invite_link(
            self.store, "team", 5, timedelta(days=7), self.admin.id
        )

    def test_deleted_link_is_refused_and_hidden_at_once(self) -> None:
        self.assertTrue(invite_links.delete_invite_link(self.store, self.link.id, self.admin.id))
        with self.assertRaises(invite_links.InviteLinkInvalidError):
            invite_links.load_invite_link(self.store, self.credential)
        self.assertEqual(invite_links.list_invite_links(self.store), [])

    def test_restore_inside_the_window_brings_it_back_working(self) -> None:
        invite_links.delete_invite_link(self.store, self.link.id, self.admin.id)
        invite_links.restore_invite_link(self.store, self.link.id, self.admin.id, True)
        self.assertEqual(invite_links.load_invite_link(self.store, self.credential).id, self.link.id)

    def test_restore_after_the_window_is_refused(self) -> None:
        invite_links.delete_invite_link(self.store, self.link.id, self.admin.id)
        self.backdate(BUCKET_INVITE_LINKS, self.link.id)
        with self.assertRaises(RestoreExpiredError):
            invite_links.restore_invite_link(self.store, self.link.id, self.admin.id, True)

    def test_a_non_admin_who_did_not_delete_it_may_not_restore(self) -> None:
        invite_links.delete_invite_link(self.store, self.link.id, self.admin.id)
        with self.assertRaises(RestoreForbiddenError):
            invite_links.restore_invite_link(self.store, self.link.id, self.alice.id, False)

    def test_purge_removes_expired_deletions(self) -> None:
        invite_links.delete_invite_link(self.store, self.link.id, self.admin.id)
        self.backdate(BUCKET_INVITE_LINKS, self.link.id)
        self.assertEqual(invite_links.purge_dead_invite_links(self.store), 1)
        self.assertIsNone(invite_links.get_invite_link(self.store, self.link.id))


class RenameExpectTest(StoreTestCase):
    def test_rename_with_a_stale_expect_is_refused(self) -> None:
        users.rename_user(self.store, self.alice.id, "Alice B", expect="Alice")
        with self.assertRaises(users.RenameConflictError) as caught:
            users.rename_user(self.store, self.alice.id, "Alice", expect="Alice C")
        self.assertEqual(caught.exception.current, "Alice B")
        self.assertEqual(users.get_user(self.store, self.alice.id).display_name, "Alice B")


if __name__ == "__main__":
    unittest.main()
