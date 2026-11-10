"""The running configuration (app/core/config_live.py): one validate-then-
apply path for the Settings screen and for hand edits, and the writer that
puts config.yaml back on disk."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.core import config_live
from app.core.config import ValidationError
from app.core.config import repo_file
from app.tests.support import new_holder
from app.tests.support import in_container


def version_of(path: Path) -> str:
    return config_live.version(config_live.read_raw(path))


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


class HolderTest(unittest.TestCase):
    def test_save_applies_live_keys(self) -> None:
        holder, path = new_holder(self)
        result = holder.save(version_of(path), {"server.rate_limit_max": 7, "server.port": 9999, "server.secure_cookies": True})
        self.assertEqual(holder.get().rate_limit_max, 7)
        self.assertNotEqual(holder.get().port, 9999)
        self.assertEqual(result["applied"], ["server.rate_limit_max"])
        self.assertEqual(result["restart"], ["server.port"])
        self.assertEqual(result["unchanged"], ["server.secure_cookies"])
        raw = config_live.read_raw(path)
        self.assertIn("rate_limit_max: 7 ", raw)
        self.assertIn("# [live]", raw)
        port = next(k for s in holder.snapshot()["sections"] for k in s["keys"] if k["key"] == "server.port")
        self.assertTrue(port["pending_restart"])
        self.assertEqual(port["running"], holder.boot().port)

    def test_save_refuses_a_stale_version(self) -> None:
        holder, path = new_holder(self)
        before = config_live.read_raw(path)
        with self.assertRaises(config_live.ConflictError) as caught:
            holder.save("sha256:old", {"server.rate_limit_max": 7})
        self.assertEqual(caught.exception.version, config_live.version(before))
        self.assertEqual(config_live.read_raw(path), before)

    def test_save_refuses_invalid_values(self) -> None:
        holder, path = new_holder(self)
        for changes in ({"server.port": 0}, {"server.port": "eighty"}, {"server.port": True}, {"server.trust_proxy": True}):
            with self.subTest(changes), self.assertRaises(ValidationError):
                holder.save(version_of(path), changes)
        self.assertEqual(holder.get().port, holder.boot().port)
        for key in ("server.secret_key", "server.nope"):
            with self.subTest(key), self.assertRaises(config_live.UnknownSettingError):
                holder.save(version_of(path), {key: "x"})

    def test_repo_is_live_and_cleaned(self) -> None:
        """app.repo is live, loses a trailing / or .git, and builds file links;
        an address that is not https is refused."""
        holder, path = new_holder(self)
        # A scaffold given --repo starts with one, so start from none.
        holder.save(version_of(path), {"app.repo": ""})
        self.assertEqual(repo_file(holder.get(), "config/openapi.json"), "")
        holder.save(version_of(path), {"app.repo": "https://github.com/you/app.git/"})
        self.assertEqual(holder.get().repo, "https://github.com/you/app")
        self.assertEqual(repo_file(holder.get(), "/config/openapi.json"), "https://github.com/you/app/blob/HEAD/config/openapi.json")
        for bad in ("http://github.com/you/app", "github.com/you/app", "https://github.com/you/app?x=1", "javascript:alert(1)"):
            with self.subTest(bad), self.assertRaises(ValidationError):
                holder.save(version_of(path), {"app.repo": bad})

    def test_poll_applies_a_hand_edit(self) -> None:
        holder, path = new_holder(self)
        notified = []
        holder.on_change(lambda old, new: notified.append(new))

        raw = config_live.read_raw(path)
        edited = raw.replace("rate_limit_max: 120", "rate_limit_max: 7  ", 1)
        write(path, edited)
        holder.poll()
        self.assertEqual(holder.get().rate_limit_max, 120, "applied on the first sighting -- it should wait for a second")
        holder.poll()
        self.assertEqual(holder.get().rate_limit_max, 7)
        self.assertEqual(len(notified), 1)

        # An invalid edit keeps the last good config and says why.
        write(path, edited.replace(f"port: {holder.boot().port}", "port: 0", 1))
        holder.poll()
        holder.poll()
        snapshot = holder.snapshot()
        self.assertIsNotNone(snapshot["error"])
        self.assertIn("server.port", snapshot["error"]["message"])
        self.assertEqual(holder.get().rate_limit_max, 7)

        # Fixing it clears the error.
        write(path, edited.replace("rate_limit_max: 7  ", "rate_limit_max: 8  ", 1))
        holder.poll()
        holder.poll()
        snapshot = holder.snapshot()
        self.assertIsNone(snapshot["error"])
        self.assertEqual(holder.get().rate_limit_max, 8)

        # The server's own save is not news to the watcher.
        before = len(notified)
        holder.save(snapshot["version"], {"server.secure_cookies": False})
        holder.poll()
        holder.poll()
        self.assertEqual(len(notified), before + 1)

    def test_snapshot_never_holds_the_key(self) -> None:
        holder, _ = new_holder(self)
        encoded = json.dumps(holder.snapshot())
        self.assertNotIn(holder.get().secret_key, encoded)
        self.assertNotIn("secret_key", encoded)

    def test_container_locks_script_keys(self) -> None:
        holder, path = new_holder(self)
        with in_container(path, path.parent / "data"):
            with self.assertRaises(config_live.LockedError):
                holder.save(version_of(path), {"docker.data_dir": "/home"})

    def test_write_in_place_keeps_the_file_and_a_backup(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.yaml"
        path.write_text("a long first version\n", encoding="utf-8")
        path.chmod(0o640)
        before = os.stat(path)
        backup = Path(directory.name) / "data" / "config.yaml.bak"
        backup.parent.mkdir()
        config_live.write_config_file(path, "short\n", True, backup)
        after = os.stat(path)
        self.assertEqual((before.st_ino, before.st_dev), (after.st_ino, after.st_dev))
        self.assertEqual(path.read_text(encoding="utf-8"), "short\n")
        self.assertEqual(backup.read_text(encoding="utf-8"), "a long first version\n")

        config_live.write_config_file(path, "renamed\n", False, None)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)
        self.assertEqual(path.read_text(encoding="utf-8"), "renamed\n")


if __name__ == "__main__":
    unittest.main()
