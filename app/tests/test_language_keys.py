"""Every piece of text the page asks for exists in language.yaml. A missing
key hides its element silently (that is how text is switched off on
purpose), so a typo would otherwise just make a label vanish."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
LITERAL = re.compile(r"I18n\.(?:get|fill)\(\s*\"([a-z_]+\.[a-z0-9_.]+)\"")
ATTRIBUTE = re.compile(r'data-i18n="([a-z_]+\.[a-z0-9_.]+)"')
ATTRIBUTE_PAIRS = re.compile(r'data-i18n-attr="([^"]+)"')


def lookup(data: dict, key: str) -> object:
    cursor: object = data
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


class LanguageKeysTest(unittest.TestCase):
    def test_every_literal_key_exists(self) -> None:
        data = yaml.safe_load((ROOT / "config" / "language.yaml").read_text(encoding="utf-8"))
        wanted: set[str] = set()
        for path in (ROOT / "static" / "js").rglob("*.js"):
            wanted.update(LITERAL.findall(path.read_text(encoding="utf-8")))
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        wanted.update(ATTRIBUTE.findall(html))
        for pairs in ATTRIBUTE_PAIRS.findall(html):
            wanted.update(pair.split(":", 1)[1].strip() for pair in pairs.split(","))
        # Keys the template deliberately leaves empty or absent to switch text off.
        optional = {"undo.nothing"}
        # "card.button_" + id and friends are prefixes completed at runtime;
        # the catalog test below covers the ones that matter.
        literal = {key for key in wanted - optional if not key.endswith(("_", "."))}
        missing = sorted(key for key in literal if not isinstance(lookup(data, key), str))
        self.assertEqual(missing, [])

    def test_card_catalog_has_names(self) -> None:
        data = yaml.safe_load((ROOT / "config" / "language.yaml").read_text(encoding="utf-8"))
        vocab = (ROOT / "static" / "js" / "media" / "vocab.js").read_text(encoding="utf-8")
        fields = re.search(r"FIELDS: \{(.*?)\n  \},", vocab, re.S).group(1)
        buttons = re.search(r"BUTTONS: \{(.*?)\n  \},", vocab, re.S).group(1)
        for name in re.findall(r"^\s+(\w+): \{", fields, re.M):
            self.assertIsInstance(lookup(data, f"card.field_{name}"), str, name)
        for name in re.findall(r"^\s+(\w+): \{", buttons, re.M):
            self.assertIsInstance(lookup(data, f"card.button_{name}"), str, name)


if __name__ == "__main__":
    unittest.main()
