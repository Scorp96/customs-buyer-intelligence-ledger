from __future__ import annotations

import json
import unittest
from pathlib import Path

from unified_runtime import BUILD_ID, RUNTIME_VERSION


ROOT = Path(__file__).resolve().parents[1]


class V64ReleaseIdentityTests(unittest.TestCase):
    def test_runtime_reports_v64_identity(self) -> None:
        self.assertEqual(RUNTIME_VERSION, "6.4.0")
        self.assertTrue(BUILD_ID.startswith("CBI-V6.4-"))

    def test_plugin_manifest_is_promoted_to_v64(self) -> None:
        payload = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertTrue(str(payload["version"]).startswith("6.4.0+codex."))
        self.assertIn("v6.4", str(payload["description"]))
        self.assertIn("Crawl4AI", str(payload["description"]))
        self.assertIn("Playwright", str(payload["description"]))

    def test_readme_heading_is_v64(self) -> None:
        first = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first, "# Customs Buyer Intelligence v6.4")


if __name__ == "__main__":
    unittest.main()
