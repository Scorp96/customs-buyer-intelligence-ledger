from __future__ import annotations

import os
import subprocess
import sys
import unittest

# Importing mcp installs the production Windows process-liveness probe.
import mcp  # noqa: F401
from unified_runtime.resilience import _pid_is_alive


@unittest.skipUnless(os.name == "nt", "Windows-only process liveness regression")
class V61WindowsProcessProbeTests(unittest.TestCase):
    def test_terminated_process_is_not_alive_while_popen_handle_remains(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        pid = process.pid
        process.wait(timeout=10)
        # Keep the Popen object reachable: on Windows this can keep a process
        # object handle open even though execution has already terminated.
        self.assertFalse(_pid_is_alive(pid))

    def test_live_process_remains_alive(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            self.assertTrue(_pid_is_alive(process.pid))
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
