from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "mcp" / "render_bootstrap.py"


class V63RenderBootstrapRecoveryTests(unittest.TestCase):
    def test_render_bootstrap_uses_v63_recovery_manager_for_restore_without_public_leak(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn(
            "from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63",
            source,
        )
        self.assertEqual(
            source.count("RecoveryObjectStoreStateManagerV63.from_env()"),
            1,
            "startup must restore R2 while anonymous health must not enumerate object-store settings",
        )
        self.assertNotIn('"object_store_configured":', source)
        self.assertNotIn("ObjectStoreStateManager.from_env()", source)


if __name__ == "__main__":
    unittest.main()
