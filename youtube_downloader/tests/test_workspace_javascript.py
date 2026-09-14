"""Run the dependency-free JavaScript regressions when Node is available."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is required for the workspace JavaScript tests")
class WorkspaceJavaScriptTestCase(unittest.TestCase):
    def test_workspace_module(self):
        result = subprocess.run(
            [NODE, "--test", str(Path(__file__).with_name("test_workspace.js"))],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
