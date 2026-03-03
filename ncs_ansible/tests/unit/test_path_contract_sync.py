from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync_path_contract.py"


class TestPathContractSync(unittest.TestCase):
    def test_sync_check_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
