"""The schema (app/core/config_schema.py): every key says how it applies,
and the tags agree with what live_config actually does."""
from __future__ import annotations

import unittest
from pathlib import Path

from app.core import config, config_live, config_schema
from app.tests.support import sample_changes


class SchemaTest(unittest.TestCase):
    def test_every_key_is_tagged(self) -> None:
        seen = set()
        for section in config_schema.schema():
            for key in section.keys:
                seen.add(key.path)
                self.assertTrue(key.tagged, f"{key.path} has no [live], [restart] or [scripts] tag in defaults.yaml")
        self.assertEqual(seen, set(config_schema.field_types()), "defaults.yaml and config.py's dataclasses differ")

    def test_live_tags_match_live_config(self) -> None:
        """Changing a [live] key changes the running Config, and changing any
        other key does not. A new live key live_config forgets fails here."""
        defaults = config.defaults()
        path = Path("/project/config/config.yaml")
        boot = config.build_config(defaults, path, config.resolve_paths(defaults, path), "ab" * 32)
        raw = config.DEFAULTS_PATH.read_text(encoding="utf-8")
        for section in config_schema.schema():
            for key in section.keys:
                with self.subTest(key.path):
                    edited, _ = config_live.edit_changes(raw, sample_changes(key), "defaults.yaml", False)
                    new = config_live.live_config(boot, defaults, config.parse(edited, "edited"))
                    changed = new != boot  # file is compare=False
                    if key.mode == config_schema.MODE_LIVE:
                        self.assertTrue(changed, f"{key.path} is tagged [live] but live_config does not apply it")
                    else:
                        self.assertFalse(changed, f"{key.path} is tagged [{key.mode}] but live_config applies it")

    def test_help_comes_from_comments(self) -> None:
        language_file = config_schema.schema_key("server.language_file")
        self.assertTrue(language_file.help)
        self.assertEqual(language_file.mode, config_schema.MODE_RESTART)
        self.assertEqual(config_schema.schema_key("server.rate_limit_max").mode, config_schema.MODE_LIVE)
        self.assertEqual(config_schema.schema_key("docker.memory").mode, config_schema.MODE_SCRIPTS)
        self.assertEqual(config_schema.schema_key("server.trust_proxy").mode, config_schema.MODE_LIVE)
        self.assertIsNone(config_schema.schema_key("server.secret_key"))


if __name__ == "__main__":
    unittest.main()
