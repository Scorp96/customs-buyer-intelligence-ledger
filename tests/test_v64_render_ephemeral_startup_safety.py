"""Guard against anonymous Render MCP and data loss on ephemeral Free instances."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from mcp.cloud_runtime_startup_guard import require_remote_environment_safety

ROOT = Path(__file__).resolve().parents[1]
ENV = {
    "RENDER": "true",
    "CBI_REQUIRE_EPHEMERAL_DURABILITY": "1",
    "CBI_REMOTE_AUTH_MODE": "bearer",
    "CBI_OBJECT_STORE_MODE": "r2",
    "CBI_OBJECT_STORE_ENDPOINT": "https://r2.example.invalid",
    "CBI_OBJECT_STORE_BUCKET": "synthetic-ledger",
    "CBI_OBJECT_STORE_ACCESS_KEY_ID": "synthetic-access",
    "CBI_OBJECT_STORE_SECRET_ACCESS_KEY": "synthetic-secret",
}


class RenderEphemeralStartupSafetyTests(unittest.TestCase):
    def test_configured_authenticated_r2_render_is_accepted(self):
        self.assertIsNone(require_remote_environment_safety(ENV))

    def test_unauthenticated_public_render_is_rejected(self):
        for mode in ("none", "off", "disabled"):
            with self.subTest(mode=mode):
                env = dict(ENV, CBI_REMOTE_AUTH_MODE=mode)
                with self.assertRaisesRegex(RuntimeError, "RENDER_PUBLIC_MCP_AUTH_REQUIRED"):
                    require_remote_environment_safety(env)

    def test_ephemeral_free_render_needs_object_store(self):
        for mode in ("", "none", "off"):
            with self.subTest(mode=mode):
                env = dict(ENV, CBI_OBJECT_STORE_MODE=mode)
                with self.assertRaisesRegex(RuntimeError, "RENDER_EPHEMERAL_OBJECT_STORE_REQUIRED"):
                    require_remote_environment_safety(env)

    def test_missing_r2_credentials_rejected_without_exposing_values(self):
        for key in (
            "CBI_OBJECT_STORE_ENDPOINT", "CBI_OBJECT_STORE_BUCKET",
            "CBI_OBJECT_STORE_ACCESS_KEY_ID", "CBI_OBJECT_STORE_SECRET_ACCESS_KEY",
        ):
            with self.subTest(key=key):
                env = {k: v for k, v in ENV.items() if k != key}
                with self.assertRaises(RuntimeError) as caught:
                    require_remote_environment_safety(env)
                self.assertEqual(
                    str(caught.exception),
                    "RENDER_EPHEMERAL_OBJECT_STORE_CONFIG_INCOMPLETE",
                )
                self.assertNotIn("synthetic", str(caught.exception))

    def test_ephemeral_flag_validation_is_strict(self):
        with self.assertRaisesRegex(RuntimeError, "CBI_REQUIRE_EPHEMERAL_DURABILITY_INVALID"):
            require_remote_environment_safety(dict(ENV, CBI_REQUIRE_EPHEMERAL_DURABILITY="sometimes"))

    def test_nonrender_offline_local_acceptance_is_not_affected(self):
        self.assertIsNone(require_remote_environment_safety({
            "RENDER": "false",
            "CBI_REMOTE_AUTH_MODE": "none",
            "CBI_OBJECT_STORE_MODE": "none",
            "CBI_REQUIRE_EPHEMERAL_DURABILITY": "1",
        }))

    def test_render_persistent_disk_mode_remains_compatible(self):
        env = {"RENDER": "true", "CBI_REMOTE_AUTH_MODE": "bearer"}
        self.assertIsNone(require_remote_environment_safety(env))

    def test_explicit_auth_modes_remain_supported(self):
        for mode in ("bearer", "mixed", "github_oauth"):
            with self.subTest(mode=mode):
                require_remote_environment_safety(dict(ENV, CBI_REMOTE_AUTH_MODE=mode))

    def test_render_blueprint_declares_r2_and_never_commits_secrets(self):
        text = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("plan: free", text)
        self.assertIn("key: CBI_REQUIRE_EPHEMERAL_DURABILITY\n        value: \"1\"", text)
        self.assertIn("key: CBI_OBJECT_STORE_MODE\n        value: r2", text)
        for key in (
            "CBI_OBJECT_STORE_ENDPOINT",
            "CBI_OBJECT_STORE_BUCKET",
            "CBI_OBJECT_STORE_ACCESS_KEY_ID",
            "CBI_OBJECT_STORE_SECRET_ACCESS_KEY",
        ):
            self.assertIn("key: " + key + "\n        sync: false", text)
        self.assertNotIn("synthetic-secret", text)

    def test_bootstrap_public_health_hides_storage_and_mcp_control_details(self):
        from mcp import render_bootstrap
        for path in ("/", "/healthz", "/readyz"):
            with self.subTest(path=path):
                handler = object.__new__(render_bootstrap.BootstrapHandler)
                captured = []
                handler._path = lambda p=path: p
                handler._json = lambda status, data: captured.append((status, data))
                with mock.patch.object(
                    render_bootstrap.RecoveryObjectStoreStateManagerV63,
                    "from_env",
                    side_effect=AssertionError("public health must not inspect secret configuration"),
                ):
                    handler.do_GET()
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0][0], 200)
                self.assertEqual(captured[0][1], {
                    "status": "bootstrap_required",
                    "service": "customs-buyer-intelligence",
                })

    def test_server_entrypoint_checks_safety_before_mutable_runtime_import(self):
        src = (ROOT / "mcp/server_v61_remote.py").read_text(encoding="utf-8")
        self.assertLess(
            src.index("sys.path.insert(0, str(ROOT))"),
            src.index("from mcp.cloud_runtime_startup_guard import require_remote_environment_safety"),
        )
        self.assertLess(
            src.index("require_remote_environment_safety(os.environ)"),
            src.index("from mcp import server_v61_backup_recovery as _production"),
        )
        boot = (ROOT / "mcp/render_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("require_remote_environment_safety(os.environ)", boot)
        self.assertLess(
            boot.index("require_remote_environment_safety(os.environ)"),
            boot.index("persistence = RecoveryObjectStoreStateManagerV63.from_env()"),
        )


if __name__ == "__main__":
    unittest.main()
