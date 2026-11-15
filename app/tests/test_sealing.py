"""S12: every database value is sealed to its bucket and key, and each purpose
secret.key is put to seals with its own subkey."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core import db, encryption

# The same vector as the Go template's TestTheSubkeyMatchesTheOtherTemplate.
VECTOR_KEY = bytes(range(32)).hex()
VECTOR_DB = "5e724771cefe68145ad1684f85845a31bd5bf8cdeb61a78bd6a1bde0656139fd"


class SealingTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "app.db"
        self.key = encryption.generate_key_hex()

    def test_a_record_moved_to_another_place_does_not_open(self) -> None:
        """Someone who can write app.db but has no secret.key copies the
        owner's users record over another account's: that account must not
        read back as the owner."""
        store = db.open_store(self.path, self.key, True)
        store.put(db.BUCKET_USERS, 1, {"name": "owner"})
        store.put(db.BUCKET_USERS, 2, {"name": "other"})
        with store._connection() as connection:
            (sealed,) = connection.execute('SELECT value FROM "users" WHERE key = 1').fetchone()
            connection.execute('UPDATE "users" SET value = ? WHERE key = 2', (sealed,))
            connection.execute('INSERT INTO "sessions" (key, value) VALUES (1, ?)', (sealed,))
        with self.assertRaises(db.DecodeError):
            store.get(db.BUCKET_USERS, 2)
        with self.assertRaises(db.DecodeError):
            store.get(db.BUCKET_SESSIONS, 1)
        self.assertEqual(store.get(db.BUCKET_USERS, 1), {"name": "owner"})

    def test_an_old_database_is_resealed_once(self) -> None:
        """A database sealed the old way (secret.key itself, bound to nothing)
        is brought up to date the first time it is opened, once, the file
        before is kept beside it, and a field sealed on its own (a two-factor
        secret) moves to its subkey."""
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # a 20-byte base32 secret, as two-factor makes
        record = {"name": "owner", "totp_secret": encryption.xchacha_encrypt_string(self.key, secret)}
        old = db.Store(self.path, self.key, True)
        old.initialise()
        with old._connection() as connection:
            connection.execute("DROP TABLE sealing")
            sealed = encryption.xchacha_encrypt_bytes(self.key, json.dumps(record).encode())
            connection.execute('INSERT INTO "users" (key, value) VALUES (1, ?)', (sealed,))
        self.assertTrue(db.sealed_the_old_way(self.path))
        with self.assertRaises(db.DecodeError):
            db.check_file(self.path, self.key, True)

        for _ in range(2):
            store = db.open_store(self.path, self.key, True)
            got = store.get(db.BUCKET_USERS, 1)
            self.assertEqual(got["name"], "owner")
        self.assertEqual(len(list(self.path.parent.glob("app.db.before-reseal-*"))), 1)
        self.assertFalse(db.sealed_the_old_way(self.path))
        db.check_file(self.path, self.key, True)
        totp_key = encryption.subkey(self.key, encryption.PURPOSE_TOTP)
        self.assertEqual(encryption.xchacha_decrypt_string(totp_key, got["totp_secret"]), secret)

    def test_a_value_sealed_for_one_purpose_does_not_open_for_another(self) -> None:
        """A session cookie is not a log line, and neither opens with
        secret.key itself."""
        cookie = encryption.xchacha_encrypt_string(encryption.subkey(self.key, encryption.PURPOSE_COOKIE), "credential")
        for other in (encryption.subkey(self.key, encryption.PURPOSE_LOGS), self.key):
            with self.assertRaises(encryption.CipherTextError):
                encryption.xchacha_decrypt_string(other, cookie)
        purposes = [encryption.PURPOSE_DB, encryption.PURPOSE_LOGS, encryption.PURPOSE_COOKIE, encryption.PURPOSE_TOTP, encryption.PURPOSE_FILES, encryption.PURPOSE_WEBHOOKS]
        keys = {encryption.subkey(self.key, purpose) for purpose in purposes} | {self.key}
        self.assertEqual(len(keys), len(purposes) + 1)
        self.assertEqual(encryption.subkey(VECTOR_KEY, encryption.PURPOSE_DB), VECTOR_DB)
        self.assertEqual(encryption.subkey("not hex", encryption.PURPOSE_DB), "")


if __name__ == "__main__":
    unittest.main()
