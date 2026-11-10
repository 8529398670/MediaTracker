"""Every theme has to stay readable. The script runs theme.js itself, so this is
the page's own maths and not a copy of it. Without Node there is nothing to run it
with."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_themes.js"


class ThemesTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is not installed")
    def test_every_theme_is_readable(self) -> None:
        done = subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
