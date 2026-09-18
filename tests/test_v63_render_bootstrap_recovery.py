from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "mcp" / "render_bootstrap.py"


class V63RenderBootstrapRecoveryTests(unittest.TestCase):
    def test_render_bootstrap_uses_v63_recovery_manager_for_restore_and_health(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn(
            "from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63",
            source,
        )
        self.assertGreaterEqual(
            source.count("RecoveryObjectStoreStateManagerV63.from_env()"),
            2,
            "bootstrap health and startup restore must both use the v6.3 recovery manager",
        )
        self.assertNotIn("ObjectStoreStateManager.from_env()", source)


if __name__ == "__main__":
    unittest.main()
