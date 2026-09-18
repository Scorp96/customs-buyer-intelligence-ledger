from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unified_runtime import mcp_surface_evidence_v63 as module
from unified_runtime.mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_v63_mcp_surface_evidence.py"
REQUIRED = set(V63_READ_ONLY_TOOL_NAMES) | set(V63_MUTATION_TOOL_NAMES)


class V63McpSurfaceEvidenceTests(unittest.TestCase):
    def test_real_exact_checkout_captures_complete_source_bound_surface(self):
        evidence = module.capture_v63_active_mcp_surface_evidence(
            ROOT,
            expected_git_sha=module._checkout_git_sha(ROOT),
        )
        self.assertEqual(evidence["schema"], "cbi.v63-mcp-surface-evidence.v1")
        self.assertTrue(evidence["verified"])
        self.assertTrue(evidence["active_entrypoint_observed"])
        self.assertTrue(evidence["tools_list_observed"])
        self.assertEqual(evidence["active_entrypoint"], "mcp/server_v61_backup_recovery.py")
        self.assertTrue(REQUIRED <= set(evidence["tool_names"]))
        self.assertEqual(evidence["missing_tools"], [])
        self.assertEqual(len(evidence["production_source_snapshot_sha256"]), 64)
        self.assertTrue(evidence["source_snapshot_validation"]["valid"])

    def test_wrong_expected_git_sha_blocks_before_mcp_process_start(self):
        with mock.patch.object(module.ExactCheckoutMcpHarness, "start") as start:
            with self.assertRaisesRegex(RuntimeError, "GIT_SHA_MISMATCH"):
                module.capture_v63_active_mcp_surface_evidence(
                    ROOT,
                    expected_git_sha="0" * 40,
                )
        start.assert_not_called()

    def test_missing_required_tool_fails_closed(self):
        observed = set(REQUIRED)
        observed.remove("create_product_opportunity")
        with mock.patch.object(module.ExactCheckoutMcpHarness, "active_entrypoint", return_value="mcp/server_v61_backup_recovery.py"), \
             mock.patch.object(module.ExactCheckoutMcpHarness, "start"), \
             mock.patch.object(module.ExactCheckoutMcpHarness, "list_tool_names", return_value=observed), \
             mock.patch.object(module.ExactCheckoutMcpHarness, "stop"):
            with self.assertRaisesRegex(RuntimeError, "V63_ACTIVE_MCP_SURFACE_INCOMPLETE:create_product_opportunity"):
                module.capture_v63_active_mcp_surface_evidence(
                    ROOT,
                    expected_git_sha=module._checkout_git_sha(ROOT),
                )

    def test_cli_invalid_git_sha_issues_no_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "out"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--expected-git-sha", "not-a-sha", "--output-dir", str(output_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((output_dir / "V63_ACTIVE_MCP_SURFACE_EVIDENCE.json").exists())


if __name__ == "__main__":
    unittest.main()
