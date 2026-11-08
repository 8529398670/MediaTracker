"""secret.key (app/core/config_secret.py): where it is, how an older
config.yaml's key moves into it, and when a new one may be made."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.core import config, config_secret
from app.core.config import ConfigError
from app.tests.support import in_container

LEGACY = """server:
  port: 8000
  # Encrypts session cookies and, with encrypt_at_rest, every database record.
  # 64 hex characters. Generated when this file is created.
  secret_key: "{key}"
  encrypt_at_rest: true
"""


class SecretTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def legacy(self, key: str) -> Path:
        path = self.dir / "config.yaml"
        path.write_text(LEGACY.format(key=key), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_migrate_moves_the_key(self) -> None:
        key = config_secret.generate_secret()
        path = self.legacy(key)
        result = config_secret.migrate_legacy_secret(path)
        self.assertTrue(result.moved and result.removed)
        secret = config_secret.secret_path_for(path)
        self.assertEqual(config_secret.read_secret(secret), key)
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        after = path.read_text(encoding="utf-8")
        self.assertNotIn(key, after)
        self.assertNotIn("secret_key:", after)
        self.assertIn("encrypt_at_rest: true", after)
        self.assertIn("port: 8000", after)
        again = config_secret.migrate_legacy_secret(path)
        self.assertFalse(again.moved or again.removed)

    def test_migrate_finishes_an_interrupted_move(self) -> None:
        key = config_secret.generate_secret()
        path = self.legacy(key)
        config_secret.write_secret(config_secret.secret_path_for(path), key)
        result = config_secret.migrate_legacy_secret(path)
        self.assertFalse(result.moved)
        self.assertTrue(result.removed)

    def test_migrate_refuses_two_different_keys(self) -> None:
        path = self.legacy(config_secret.generate_secret())
        config_secret.write_secret(config_secret.secret_path_for(path), config_secret.generate_secret())
        before = path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "different key"):
            config_secret.migrate_legacy_secret(path)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_migrate_refuses_a_malformed_key(self) -> None:
        path = self.legacy("not-a-key")
        with self.assertRaises(ConfigError):
            config_secret.migrate_legacy_secret(path)
        self.assertFalse(config_secret.secret_path_for(path).exists())

    def test_migrate_keeps_crlf(self) -> None:
        key = config_secret.generate_secret()
        path = self.dir / "config.yaml"
        path.write_bytes(LEGACY.format(key=key).replace("\n", "\r\n").encode())
        config_secret.migrate_legacy_secret(path)
        after = path.read_bytes()
        self.assertNotIn(b"secret_key", after)
        self.assertEqual(after.count(b"\n"), after.count(b"\r\n"))

    def test_container_points_at_docker_run(self) -> None:
        path = self.legacy(config_secret.generate_secret())
        with in_container(path, self.dir / "data"):
            file = config.read_file(path)
            with self.assertRaisesRegex(ConfigError, "docker/run.sh"):
                config_secret.resolve_secret(file, path, self.dir / "app.db")

    def test_fresh_install_gets_a_key_but_existing_data_does_not(self) -> None:
        path = self.dir / "config.yaml"
        path.write_text(config.new_file_content(), encoding="utf-8")
        file = config.read_file(path)
        database = self.dir / "app.db"
        database.write_bytes(b"x")
        with self.assertRaisesRegex(ConfigError, "Restore secret.key"):
            config_secret.resolve_secret(file, path, database)
        database.unlink()
        state = config_secret.resolve_secret(file, path, database)
        self.assertTrue(state.created)
        self.assertEqual(len(state.key), 64)

    def test_defaults_carry_no_secret(self) -> None:
        self.assertNotIn("secret_key:", config.new_file_content())
        self.assertNotIn("secret_key:", config.example_file_content())

    def test_permission_warning(self) -> None:
        if os.name == "nt":
            return
        path = self.dir / "config.yaml"
        path.write_text("", encoding="utf-8")
        secret = self.dir / "secret.key"
        config_secret.write_secret(secret, config_secret.generate_secret())
        self.assertEqual(config.permission_warning(path, secret), "")
        secret.chmod(0o640)
        self.assertEqual(config.permission_warning(path, secret), "")
        secret.chmod(0o644)
        self.assertIn("secret.key", config.permission_warning(path, secret))


if __name__ == "__main__":
    unittest.main()
