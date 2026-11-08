"""Backups: one comes back whole, leaves the key out unless asked, is refused
rather than half-restored when the key or the file is wrong, and a restore
keeps what it replaced."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app.core import backup, config, db, encryption, server_lock
from app.models import users
from app.models import two_factor
from app.tests.support import new_holder


class BackupTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        holder, _ = new_holder(self, app_dir=str(self.root / "data"))
        self.cfg = holder.boot()
        self.cfg.app_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.storage_dir / "photos").mkdir(parents=True)
        (self.cfg.storage_dir / "photos" / "a.txt").write_text("original")
        self.store = db.open_store(self.cfg.database_path, self.cfg.secret_key, True)

    def names(self, cfg: config.Config | None = None) -> list[str]:
        cfg = cfg or self.cfg
        store = db.open_store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
        return [user.display_name for user in users.list_users(store)]

    def members(self, path: Path) -> set[str]:
        with tarfile.open(path, "r:gz") as archive:
            return set(archive.getnames())

    def write_tar(self, name: str, members: list[tarfile.TarInfo]) -> Path:
        path = self.root / name
        with tarfile.open(path, "w:gz") as archive:
            for member in members:
                archive.addfile(member, io.BytesIO(b"x" * member.size))
        return path


class CreateTest(BackupTestCase):
    def test_leaves_the_key_out_unless_asked(self) -> None:
        plain = backup.create(self.store, self.cfg)
        names = self.members(plain.path)
        self.assertLessEqual({"manifest.json", "app.db", "config.yaml", "storage/photos/a.txt"}, names)
        self.assertNotIn("secret.key", names)
        self.assertFalse(plain.manifest.contains_key)
        self.assertEqual(plain.manifest.key_fingerprint, encryption.key_fingerprint(self.cfg.secret_key))
        self.assertNotIn(plain.manifest.key_fingerprint, self.cfg.secret_key)
        self.assertEqual(plain.path.stat().st_mode & 0o777, 0o600)

        keyed = backup.create(self.store, self.cfg, out=str(self.root / "with-key.tar.gz"), include_key=True)
        self.assertIn("secret.key", self.members(keyed.path))
        self.assertTrue(keyed.manifest.contains_key)

    def test_sees_writes_still_in_the_wal(self) -> None:
        """Copying app.db by hand would miss these. The connection stays open
        so nothing checkpoints them into the main file first."""
        keeper = self.store.connect()
        self.addCleanup(keeper.close)
        keeper.execute("SELECT count(*) FROM users").fetchone()  # connect() alone opens nothing
        users.create_user(self.store, "In the wal", users.ROLE_USER)
        self.assertGreater(self.cfg.database_path.with_name("app.db-wal").stat().st_size, 0)
        made = backup.create(self.store, self.cfg)
        keeper.close()
        self.store = None  # type: ignore[assignment]
        backup.restore(self.cfg, str(made.path))
        self.assertEqual(self.names(), ["In the wal"])


class RestoreTest(BackupTestCase):
    def test_brings_the_data_back_and_keeps_what_it_replaced(self) -> None:
        users.create_user(self.store, "Before", users.ROLE_USER)
        made = backup.create(self.store, self.cfg)
        users.create_user(self.store, "After", users.ROLE_USER)
        (self.cfg.storage_dir / "photos" / "a.txt").write_text("changed")

        result = backup.restore(self.cfg, str(made.path))
        self.assertFalse(result.rekeyed)
        self.assertEqual(self.names(), ["Before"])
        self.assertEqual((self.cfg.storage_dir / "photos" / "a.txt").read_text(), "original")
        self.assertEqual((result.saved_storage / "photos" / "a.txt").read_text(), "changed")
        self.assertTrue(result.saved_database.is_file())
        self.assertTrue(result.saved_config.is_file())

    def test_refused_while_a_server_runs(self) -> None:
        made = backup.create(self.store, self.cfg)
        path = self.cfg.app_dir / config.SERVER_LOCK_NAME
        lock = server_lock.acquire(path)
        self.addCleanup(lock.release)
        self.assertTrue(server_lock.held(path))
        with self.assertRaises(backup.ServerRunningError):
            backup.restore(self.cfg, str(made.path))

    def test_refuses_the_wrong_key_before_touching_anything(self) -> None:
        users.create_user(self.store, "Kept", users.ROLE_USER)
        made = backup.create(self.store, self.cfg)
        other = replace(self.cfg, secret_key=encryption.generate_key_hex())
        with self.assertRaisesRegex(backup.BackupError, "different key"):
            backup.restore(other, str(made.path))
        wrong = self.root / "wrong.key"
        wrong.write_text(encryption.generate_key_hex() + "\n")
        with self.assertRaisesRegex(backup.BackupError, "not the key"):
            backup.restore(other, str(made.path), key_file=str(wrong))
        self.assertEqual(self.names(), ["Kept"])
        left = [name for name in os.listdir(self.cfg.app_dir) if "before-restore" in name or name.startswith(".restore-")]
        self.assertEqual(left, [])

    def test_moves_an_old_backup_onto_the_current_key(self) -> None:
        """Two-factor secret included, so secret.key itself never changes."""
        user = users.create_user(self.store, "Second factor", users.ROLE_USER)
        secret = two_factor.start_setup(self.store, user.id, self.cfg.secret_key)
        made = backup.create(self.store, self.cfg)
        old_key = self.root / "secret.key.retired"
        old_key.write_text(self.cfg.secret_key + "\n")

        current = replace(self.cfg, secret_key=encryption.generate_key_hex())
        result = backup.restore(current, str(made.path), key_file=str(old_key))
        self.assertTrue(result.rekeyed)
        store = db.open_store(current.database_path, current.secret_key, True)
        record = store.get(db.BUCKET_USERS, user.id)
        self.assertEqual(encryption.xchacha_decrypt_string(current.secret_key, record["totp_pending"]), secret)

    def without_bucket(self, made: Path, bucket: str) -> Path:
        """A backup as code from before bucket existed made it: the same file
        with that table gone, as the Python template's every backup would be
        once a new bucket is added."""
        unpacked = self.root / "unpacked"
        with tarfile.open(made, "r:gz") as archive:
            archive.extractall(unpacked, filter="data")
        connection = sqlite3.connect(unpacked / backup.DATABASE_NAME)
        connection.execute(f'DROP TABLE "{bucket}"')
        connection.commit()
        connection.close()
        older = self.root / "older.tar.gz"
        with tarfile.open(older, "w:gz") as archive:
            for name in sorted(os.listdir(unpacked)):
                archive.add(unpacked / name, arcname=name)
        return older

    def test_brings_back_a_backup_from_before_a_bucket_existed(self) -> None:
        users.create_user(self.store, "Older", users.ROLE_USER)
        older = self.without_bucket(backup.create(self.store, self.cfg).path, db.BUCKET_JOBS)
        users.create_user(self.store, "Newer", users.ROLE_USER)
        result = backup.restore(self.cfg, str(older))
        self.assertFalse(result.rekeyed)
        self.assertEqual(self.names(), ["Older"])
        store = db.open_store(self.cfg.database_path, self.cfg.secret_key, True)
        self.assertEqual(store.all(db.BUCKET_JOBS), [])

    def test_moves_such_a_backup_onto_the_current_key_too(self) -> None:
        users.create_user(self.store, "Older", users.ROLE_USER)
        older = self.without_bucket(backup.create(self.store, self.cfg).path, db.BUCKET_JOBS)
        old_key = self.root / "secret.key.retired"
        old_key.write_text(self.cfg.secret_key + "\n")
        current = replace(self.cfg, secret_key=encryption.generate_key_hex())
        result = backup.restore(current, str(older), key_file=str(old_key))
        self.assertTrue(result.rekeyed)
        self.assertEqual(self.names(current), ["Older"])

    def test_a_missing_bucket_does_not_excuse_the_ones_present(self) -> None:
        users.create_user(self.store, "Older", users.ROLE_USER)
        self.without_bucket(backup.create(self.store, self.cfg).path, db.BUCKET_JOBS)
        with self.assertRaises(db.DecodeError):
            db.check_file(self.root / "unpacked" / backup.DATABASE_NAME, encryption.generate_key_hex(), True)

    def test_uses_a_key_packed_in_the_backup(self) -> None:
        users.create_user(self.store, "Packed", users.ROLE_USER)
        made = backup.create(self.store, self.cfg, include_key=True)
        current = replace(self.cfg, secret_key=encryption.generate_key_hex())
        backup.restore(current, str(made.path))
        self.assertEqual(self.names(current), ["Packed"])

    def test_refuses_entries_a_backup_never_holds(self) -> None:
        cases = {"parent": "../evil", "nested": "storage/../../evil", "absolute": "/tmp/evil", "stranger": "something-else"}
        for label, name in cases.items():
            with self.subTest(label):
                member = tarfile.TarInfo(name)
                member.size = 1
                with self.assertRaises(backup.BackupError):
                    backup.restore(self.cfg, str(self.write_tar(f"{label}.tar.gz", [member])))
        link = tarfile.TarInfo("storage/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        with self.assertRaises(backup.BackupError):
            backup.restore(self.cfg, str(self.write_tar("symlink.tar.gz", [link])))
        text = self.root / "plain.txt"
        text.write_text("hello")
        with self.assertRaises(backup.BackupError):
            backup.restore(self.cfg, str(text))

    def test_refuses_a_newer_format(self) -> None:
        staging = self.root / "staging"
        staging.mkdir()
        (staging / "manifest.json").write_text(f'{{"format": {backup.FORMAT_VERSION + 1}}}')
        with self.assertRaisesRegex(backup.BackupError, "format"):
            backup._read_manifest(staging)


    def test_refuses_a_newer_schema(self) -> None:
        staging = self.root / "staging"
        staging.mkdir()
        fields = {
            "format": backup.FORMAT_VERSION, "app": "x", "created_at": "", "encrypt_at_rest": True,
            "key_fingerprint": "", "contains_key": False, "schema_version": db.latest_schema_version() + 1,
        }
        (staging / "manifest.json").write_text(json.dumps(fields))
        with self.assertRaisesRegex(backup.BackupError, "newer version"):
            backup._read_manifest(staging)




if __name__ == "__main__":
    unittest.main()
