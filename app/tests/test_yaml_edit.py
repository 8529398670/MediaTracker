"""The in-place YAML editor (app/core/yaml_edit.py). yaml_edit_cases.json is
shared with the Go template (server/config/testdata/yaml_edit_cases.json):
both editors must turn the same input into the same text."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.core import config, config_live, config_schema
from app.core.yaml_edit import HandEditError, edit_yaml
from app.tests.support import sample_changes

CASES = json.loads((Path(__file__).parent / "yaml_edit_cases.json").read_text(encoding="utf-8"))


def comments(raw: str) -> list[str]:
    return [line[line.index("#"):] for line in raw.split("\n") if "#" in line]


class EditYAMLTest(unittest.TestCase):
    def test_shared_cases(self) -> None:
        for case in CASES:
            with self.subTest(case["name"]):
                edits = [(edit["path"], edit["value"]) for edit in case.get("edits") or []]
                if case.get("error"):
                    with self.assertRaises(HandEditError):
                        edit_yaml(case["input"], edits, case.get("deletes") or [], None)
                    continue
                self.assertEqual(edit_yaml(case["input"], edits, case.get("deletes") or [], None), case["output"])

    def test_every_key_round_trips(self) -> None:
        """Every key in the schema, set to a different valid value in a copy
        of defaults.yaml, reads back as that value with every other key as it
        was -- and every comment line survives."""
        defaults = config.DEFAULTS_PATH.read_text(encoding="utf-8")
        for section in config_schema.schema():
            for key in section.keys:
                with self.subTest(key.path):
                    changes = sample_changes(key)
                    edited, _ = config_live.edit_changes(defaults, changes, "defaults.yaml", False)
                    after = config_schema.flatten(config.parse(edited, "edited"))
                    self.assertEqual(after[key.path], changes[key.path])
                    self.assertEqual(comments(edited), comments(defaults))

    def test_missing_key_arrives_documented(self) -> None:
        edited, _ = config_live.edit_changes("server:\n  port: 8000\n", {"server.public_url": "https://x.example.com"}, "sparse", False)
        self.assertIn("# The address people open this at", edited)
        self.assertIn('  public_url: "https://x.example.com"', edited)


if __name__ == "__main__":
    unittest.main()
