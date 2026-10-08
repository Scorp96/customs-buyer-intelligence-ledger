"""Installation-source regression: reject default-branch legacy MCP and stale policy."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.cbi_plugin_install_preflight import validate_checkout

ROOT = Path(__file__).resolve().parents[1]
COPIED = (
    "plugin.json",
    ".codex-plugin/plugin.json",
    "mcp.json",
    ".mcp.json",
    "skills/investigate-customs-buyers/SKILL.md",
)


class PluginInstallPreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="cbi-package-preflight-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for file in COPIED:
            dest = self.root / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / file, dest)

    def _update_json(self, file: str, change):
        path = self.root / file
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _blockers(self):
        report = validate_checkout(self.root)
        self.assertEqual(report["status"], "BLOCKED", report)
        self.assertFalse(report["local_runtime_started"])
        self.assertFalse(report["network_access_performed"])
        return report["blockers"]

    def test_canonical_cloud_package_is_offline_pass(self):
        report = validate_checkout(self.root)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["installed_connector_validated"])

    def test_rejects_legacy_windows_stdin_config(self):
        self._update_json(".mcp.json", lambda d: d["mcpServers"]["buyer-outreach-actions"].update({
            "command": "powershell.exe",
            "args": ["-Command", "historical-launcher"],
        }))
        blockers = self._blockers()
        self.assertIn("LOCAL_MCP_EXECUTION_FORBIDDEN:.mcp.json:command", blockers)
        self.assertIn("LOCAL_MCP_EXECUTION_FORBIDDEN:.mcp.json:args", blockers)

    def test_rejects_unsupported_codex_mcp_snake_case(self):
        self._update_json(".mcp.json", lambda d: d.update({
            "mcp_servers": d.pop("mcpServers"),
        }))
        blockers = self._blockers()
        self.assertIn("UNSUPPORTED_SNAKE_CASE_COMPATIBILITY", blockers)
        self.assertIn("MCP_SERVER_SET_MISMATCH:.mcp.json", blockers)

    def test_rejects_wrong_endpoint_even_with_successful_json_syntax(self):
        self._update_json("mcp.json", lambda d: d["mcpServers"]["buyer-outreach-actions"].update({
            "url": "https://another-service.invalid/mcp",
        }))
        self.assertIn("MCP_TARGET_NOT_CANONICAL_RENDER:mcp.json", self._blockers())

    def test_rejects_wrong_transport_and_extra_server(self):
        def corrupt(d):
            d["mcpServers"]["buyer-outreach-actions"]["type"] = "stdio"
            d["mcpServers"]["shadow"] = {"type": "http", "url": "https://example.invalid/mcp"}
        self._update_json(".mcp.json", corrupt)
        self.assertIn("MCP_SERVER_SET_MISMATCH:.mcp.json", self._blockers())

    def test_rejects_old_default_branch_identity_and_version(self):
        self._update_json("plugin.json", lambda d: d.update({"version": "6.4.0+codex.20260918"}))
        blockers = self._blockers()
        self.assertIn("PACKAGE_VERSION_MISMATCH", blockers)

    def test_rejects_old_version_even_when_matched(self):
        for p in ("plugin.json", ".codex-plugin/plugin.json"):
            self._update_json(p, lambda d: d.update({"version": "6.4.0+codex.20260918.r1"}))
        self.assertIn("OBSOLETE_OR_INVALID_PACKAGE_VERSION", self._blockers())

    def test_rejects_duplicate_investigation_skill_entry(self):
        self._update_json(".codex-plugin/plugin.json", lambda d: d["interface"]["defaultPrompt"].append(
            "Use $customs-buyer-one-shot as an alternative investigation route."
        ))
        self.assertIn("RETIRED_ONE_SHOT_MODE_REFERENCED", self._blockers())

    def test_rejects_missing_authority_preflight_in_skill(self):
        target = self.root / "skills/investigate-customs-buyers/SKILL.md"
        target.write_text("# old skill\nFULL_AUDIT\nEXHAUSTIVE\n", encoding="utf-8")
        self.assertTrue(any("MANDATORY_SAFETY_SKILL_CONTRACT_MISSING" in x for x in self._blockers()))

    def test_rejects_missing_required_file(self):
        (self.root / "mcp.json").unlink()
        self.assertIn("MISSING_REQUIRED_FILE:mcp.json", self._blockers())

    def test_rejects_invalid_json(self):
        (self.root / ".mcp.json").write_text("{invalid", encoding="utf-8")
        self.assertIn("INVALID_REQUIRED_JSON:.mcp.json", self._blockers())


if __name__ == "__main__":
    unittest.main()
