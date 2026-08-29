from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductionLauncherRootBindingTests(unittest.TestCase):
    def test_mcp_launcher_explicitly_binds_standard_v6_session_root(self) -> None:
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["buyer-outreach-actions"]
        self.assertEqual(server["command"].casefold(), "powershell.exe")
        command = server["args"][-1]

        expected_root = "XingHuai\\CustomsBuyerIntelligenceV6\\sessions"
        self.assertIn(expected_root, command)
        self.assertIn("$env:CBI_SESSION_ROOT = $runtimeSessions", command)
        self.assertLess(
            command.index("$env:CBI_SESSION_ROOT = $runtimeSessions"),
            command.index("server_v61_backup_recovery.py"),
        )

    def test_launcher_does_not_bind_a_probe_or_candidate_root(self) -> None:
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        command = config["mcpServers"]["buyer-outreach-actions"]["args"][-1]
        lowered = command.casefold()
        self.assertNotIn("productioncandidate", lowered)
        self.assertNotIn("reconciliationprobe", lowered)
        self.assertNotIn("goldenresidualprobe", lowered)
        self.assertNotIn("goldenlifecycleprobe", lowered)

    def test_launcher_keeps_final_backup_recovery_entrypoint(self) -> None:
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        command = config["mcpServers"]["buyer-outreach-actions"]["args"][-1]
        self.assertIn("mcp\\server_v61_backup_recovery.py", command)
        self.assertTrue(command.rstrip().endswith("--stdio"))


if __name__ == "__main__":
    unittest.main()
