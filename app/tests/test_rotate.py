"""Key rotation: everything the key protects comes through still readable, a
failure before the marker changes nothing, and a stop at any point after it
ends with the key and the data matching."""
from __future__ import annotations

import base64
import gzip
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Callable

from app.core import config, config_secret, db, encryption, rotate, server_lock
from app.core import backup
from app.core import logs
from app.models import users
from app.models import two_factor
from app.tests.support import pin_switches


class Deployment:
    """A real config.yaml and secret.key, so that load does what it does after
    a crash, with a database holding a two-factor user and a log with one
    plain day, one gzipped day and a broken line."""

    def __init__(self, test: unittest.TestCase) -> None:
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "config.yaml"
        config.write_new(self.path)
        pin_switches(self.path)
        raw = self.path.read_text(encoding="utf-8").replace('app_dir: ""', f'app_dir: "{self.root / "data"}"', 1)
        self.path.write_text(raw, encoding="utf-8")
        self.cfg = config.load_path(self.path, True)

        store = db.open_store(self.cfg.database_path, self.cfg.secret_key, True)
        self.user = users.create_user(store, "Second factor", users.ROLE_USER)
        self.secret = two_factor.start_setup(store, self.user.id, self.cfg.secret_key)

        def line(text: str) -> bytes:
            sealed = encryption.xchacha_encrypt_bytes(self.cfg.secret_key, json.dumps({"msg": text}).encode())
            return base64.b64encode(sealed) + b"\n"

        (self.cfg.logs.dir / "2026-11-01.jsonl").write_bytes(line("plain day") + b"this line was cut sho")
        with gzip.open(self.cfg.logs.dir / "2026-10-31.jsonl.gz", "wb") as zipped:
            zipped.write(line("gzipped day"))

    def assert_whole(self, test: unittest.TestCase) -> config.Config:
        """As a fresh process would find it: the key on disk opens the
        database, the two-factor secret and the log."""
        cfg = config.load_path(self.path, True)
        store = db.open_store(cfg.database_path, cfg.secret_key, True)
        record = store.get(db.BUCKET_USERS, self.user.id)
        test.assertIsNotNone(record)
        test.assertEqual(encryption.xchacha_decrypt_string(cfg.secret_key, record["totp_pending"]), self.secret)
        reader = logs.Logger(cfg.logs, cfg.secret_key, cfg.encrypt_at_rest)
        for day, wanted in (("2026-11-01", "plain day"), ("2026-10-31", "gzipped day")):
            records, _ = reader.read_day(day, logs.Query(""), -1, 10)
            test.assertEqual(len(records), 1, day)
            test.assertIn(wanted, json.dumps(records))
        test.assertFalse(config_secret.rotation_pending(cfg.app_dir))
        test.assertFalse(config_secret.rotation_dir(cfg.app_dir).exists())
        return cfg


class RotateTest(unittest.TestCase):
    def test_keeps_everything_readable(self) -> None:
        d = Deployment(self)
        old_key = d.cfg.secret_key
        result = rotate.run(d.cfg)
        self.assertEqual(result.log_files, 2)

        cfg = d.assert_whole(self)
        self.assertNotEqual(cfg.secret_key, old_key)
        self.assertEqual(encryption.key_fingerprint(cfg.secret_key), result.new_fingerprint)
        self.assertEqual(config_secret.read_secret(result.retired_key), old_key)
        self.assertEqual(result.retired_key.stat().st_mode & 0o777, 0o600)
        self.assertTrue((cfg.logs.dir / "2026-11-01.jsonl").read_bytes().endswith(b"this line was cut sho"), "a broken line was dropped")

    def test_refuses_a_running_server(self) -> None:
        d = Deployment(self)
        lock = server_lock.acquire(d.cfg.app_dir / config.SERVER_LOCK_NAME)
        self.addCleanup(lock.release)
        with self.assertRaises(rotate.ServerRunningError):
            rotate.run(d.cfg)

    def test_a_failure_before_the_marker_changes_nothing(self) -> None:
        d = Deployment(self)
        wrong = replace(d.cfg, secret_key=encryption.generate_key_hex())
        with self.assertRaises(rotate.RotateError):
            rotate.run(wrong)
        self.assertFalse(d.cfg.secret_file.with_name("secret.key.next").exists())
        self.assertEqual(d.assert_whole(self).secret_key, d.cfg.secret_key)

    def test_a_stop_after_the_marker_finishes_forward(self) -> None:
        def nothing(cfg: config.Config) -> None:
            pass

        def database_only(cfg: config.Config) -> None:
            os.replace(config_secret.rotation_dir(cfg.app_dir) / "app.db", cfg.database_path)

        def one_log_file(cfg: config.Config) -> None:
            database_only(cfg)
            os.replace(config_secret.rotation_dir(cfg.app_dir) / "logs" / "2026-11-01.jsonl", cfg.logs.dir / "2026-11-01.jsonl")

        def all_the_data(cfg: config.Config) -> None:
            config_secret.finish_rotation_data(cfg.app_dir, cfg.database_path, cfg.logs.dir)

        def the_key(cfg: config.Config) -> None:
            all_the_data(cfg)
            config_secret.finish_rotation_key(cfg.secret_file)

        stops: list[Callable[[config.Config], None]] = [nothing, database_only, all_the_data, the_key]
        stops.append(one_log_file)
        for stop in stops:
            with self.subTest(stop.__name__):
                d = Deployment(self)
                new_key = config_secret.generate_secret()
                rotate.stage(d.cfg, new_key)
                config_secret.write_secret(d.cfg.secret_file.with_name("secret.key.next"), new_key)
                config_secret.mark_rotation(d.cfg.app_dir)
                stop(d.cfg)
                self.assertEqual(d.assert_whole(self).secret_key, new_key)

    def test_a_stop_before_the_marker_is_forgotten(self) -> None:
        d = Deployment(self)
        new_key = config_secret.generate_secret()
        rotate.stage(d.cfg, new_key)
        config_secret.write_secret(d.cfg.secret_file.with_name("secret.key.next"), new_key)
        cfg = config.load_path(d.path, True)
        self.assertEqual(cfg.secret_key, d.cfg.secret_key, "an uncommitted key was picked up")
        rotate.run(cfg)
        d.assert_whole(self)

    def test_a_leftover_log_is_not_replayed_onto_the_new_database(self) -> None:
        """A crash can leave app.db-wal behind. Moved over a new app.db it
        would be replayed onto a file it does not belong to."""
        d = Deployment(self)
        keeper = db.Store(d.cfg.database_path, d.cfg.secret_key, True).connect()
        self.addCleanup(keeper.close)
        keeper.execute("SELECT count(*) FROM users").fetchone()  # connect() alone opens nothing
        users.create_user(db.Store(d.cfg.database_path, d.cfg.secret_key, True), "In the wal", users.ROLE_USER)
        new_key = config_secret.generate_secret()
        rotate.stage(d.cfg, new_key)
        config_secret.write_secret(d.cfg.secret_file.with_name("secret.key.next"), new_key)
        config_secret.mark_rotation(d.cfg.app_dir)
        wal = d.cfg.database_path.with_name("app.db-wal")
        self.assertTrue(wal.exists())
        leftover = wal.read_bytes()
        config_secret.finish_rotation_data(d.cfg.app_dir, d.cfg.database_path, d.cfg.logs.dir)
        self.assertFalse(wal.exists())
        self.assertTrue(leftover)
        config_secret.finish_rotation_key(d.cfg.secret_file)
        config_secret.clear_rotation(d.cfg.app_dir)
        store = db.open_store(d.cfg.database_path, new_key, True)
        self.assertIn("In the wal", [user.display_name for user in users.list_users(store)])

    def test_the_container_half_leaves_the_key_to_the_host(self) -> None:
        d = Deployment(self)
        new_key = config_secret.generate_secret()
        key_file = d.root / "next.key"
        key_file.write_text(new_key + "\n")
        rotate.run(d.cfg, new_key_file=str(key_file))
        self.assertTrue(config_secret.rotation_pending(d.cfg.app_dir))
        self.assertEqual(config_secret.read_secret(d.cfg.secret_file), d.cfg.secret_key)
        self.assertTrue(rotate.run(d.cfg, new_key_file=str(key_file)).resumed)

        # What docker/rotate-key.sh does on the host.
        d.cfg.secret_file.write_text(new_key + "\n")
        config_secret.clear_rotation(d.cfg.app_dir)
        cfg = d.assert_whole(self)
        self.assertEqual(cfg.secret_key, new_key)
        with self.assertRaisesRegex(rotate.RotateError, "already in use"):
            rotate.run(cfg, new_key_file=str(key_file))

    def test_a_backup_from_before_a_rotation_restores_with_the_retired_key(self) -> None:
        d = Deployment(self)
        store = db.open_store(d.cfg.database_path, d.cfg.secret_key, True)
        made = backup.create(store, d.cfg)
        result = rotate.run(d.cfg)
        cfg = d.assert_whole(self)
        with self.assertRaises(backup.BackupError):
            backup.restore(cfg, str(made.path))
        restored = backup.restore(cfg, str(made.path), key_file=str(result.retired_key))
        self.assertTrue(restored.rekeyed)
        d.assert_whole(self)


if __name__ == "__main__":
    unittest.main()
