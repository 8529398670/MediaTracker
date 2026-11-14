"""The shell scripts' own rules (scripts/lib.sh). Go's twin is
server/config/scripts_test.go."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib.sh"


@unittest.skipIf(sys.platform == "win32", "run.sh is for unix shells")
class RunDirTest(unittest.TestCase):
    def test_the_run_dir_is_private(self) -> None:
        """S5: scripts/run.sh keeps .run/ and its log readable by this account
        alone, whatever the umask -- a first run's log holds the owner's login
        link. A .run/ left open by an older run.sh is closed too."""
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / ".run"
                log_file = run_dir / "server.log"
                if existing:
                    run_dir.mkdir()
                    log_file.write_text("old")
                    run_dir.chmod(0o755)
                    log_file.chmod(0o644)
                subprocess.run(
                    ["bash", "-c", 'umask 022 && source "$1" && private_run_dir', "bash", str(LIB)],
                    cwd=directory, check=True, capture_output=True,
                )
                self.assertEqual(os.stat(run_dir).st_mode & 0o777, 0o700)
                self.assertEqual(os.stat(log_file).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
