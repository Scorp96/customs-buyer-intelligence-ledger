"""Authenticated MCP runtime policy attestation, never external state access."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from mcp.cloud_runtime_startup_guard import (
    install_remote_startup_attestation,
    require_remote_environment_safety,
    safe_startup_enforcement_attestation,
)

ROOT = Path(__file__).resolve().parents[1]

HOSTED = {
    "RENDER": "true",
    "CBI_REMOTE_AUTH_MODE": "bearer",
    "CBI_REQUIRE_EPHEMERAL_DURABILITY": "1",
    "CBI_OBJECT_STORE_MODE": "r2",
    "CBI_REMOTE_PUBLIC_BASE_URL": "https://cbi-v61-preview.onrender.com",
    "CBI_OBJECT_STORE_ENDPOINT": "https://synthetic.invalid",
    "CBI_OBJECT_STORE_BUCKET": "secret-bucket-name",
    "CBI_OBJECT_STORE_ACCESS_KEY_ID": "secret-key-id",
    "CBI_OBJECT_STORE_SECRET_ACCESS_KEY": "secret-value",
}


class RemoteStartupAttestationTests(unittest.TestCase):
    def test_hosted_config_complete_reports_enforced_but_not_restore_proof(self):
        require_remote_environment_safety(HOSTED)
        result = safe_startup_enforcement_attestation(env=HOSTED, object_store_attached=True)
        self.assertTrue(result["render_hosted"])
        self.assertTrue(result["ephemeral_durability_gate_requested"])
        self.assertTrue(result["ephemeral_durability_gate_enforced"])
        self.assertFalse(result["latest_generation_self_restore_proven"])
        self.assertFalse(result["render_instance_plan_independently_verified"])
        self.assertFalse(result["secret_values_included"])
        raw = json.dumps(result)
        for prohibited in ("secret-bucket-name", "secret-key-id", "secret-value", "synthetic.invalid"):
            self.assertNotIn(prohibited, raw)

    def test_missing_ephemeral_flag_is_disclosed_not_silently_claimed(self):
        env = dict(HOSTED)
        env.pop("CBI_REQUIRE_EPHEMERAL_DURABILITY")
        result = safe_startup_enforcement_attestation(env=env, object_store_attached=True)
        self.assertFalse(result["ephemeral_durability_gate_requested"])
        self.assertFalse(result["ephemeral_durability_gate_enforced"])

    def test_unattached_manager_never_reports_ephemeral_enforcement(self):
        result = safe_startup_enforcement_attestation(env=HOSTED, object_store_attached=False)
        self.assertFalse(result["object_store_manager_attached"])
        self.assertFalse(result["ephemeral_durability_gate_enforced"])

    def test_local_offline_mode_never_asserts_render_enforcement(self):
        env = dict(HOSTED, RENDER="false", CBI_REMOTE_AUTH_MODE="none")
        result = safe_startup_enforcement_attestation(env=env, object_store_attached=True)
        self.assertFalse(result["render_hosted"])
        self.assertFalse(result["public_mcp_auth_mode_valid"])
        self.assertFalse(result["ephemeral_durability_gate_enforced"])

    def test_non_r2_mode_never_reports_enforced(self):
        result = safe_startup_enforcement_attestation(
            env=dict(HOSTED, CBI_OBJECT_STORE_MODE="none"),
            object_store_attached=True,
        )
        self.assertFalse(result["ephemeral_durability_gate_enforced"])

    def test_auth_disabled_never_reports_enforced(self):
        result = safe_startup_enforcement_attestation(
            env=dict(HOSTED, CBI_REMOTE_AUTH_MODE="none"),
            object_store_attached=True,
        )
        self.assertFalse(result["ephemeral_durability_gate_enforced"])

    def test_both_authenticated_read_handlers_receive_same_attestation(self):
        calls = []
        def contract(arguments):
            calls.append(("contract", arguments))
            return {"workflow_policy": {"default_mode": "FULL_AUDIT"}}
        def health(arguments):
            calls.append(("health", arguments))
            return {"status": "READY"}
        handles = {"get_runtime_contract": contract, "get_runtime_health": health}
        install_remote_startup_attestation(handles, env=HOSTED, object_store_attached=True)
        contract_result = handles["get_runtime_contract"]({})
        health_result = handles["get_runtime_health"]({})
        self.assertEqual(calls, [("contract", {}), ("health", {})])
        self.assertEqual(contract_result["workflow_policy"]["default_mode"], "FULL_AUDIT")
        self.assertEqual(health_result["status"], "READY")
        self.assertEqual(
            contract_result["remote_startup_safety"],
            health_result["remote_startup_safety"],
        )

    def test_existing_base_payload_is_not_mutated(self):
        original = {"status": "READY"}
        handles = {
            "get_runtime_contract": lambda _: original,
            "get_runtime_health": lambda _: {"status": "READY"},
        }
        install_remote_startup_attestation(handles, env=HOSTED, object_store_attached=True)
        value = handles["get_runtime_contract"]({})
        self.assertNotIn("remote_startup_safety", original)
        self.assertIn("remote_startup_safety", value)

    def test_missing_tool_handler_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "RUNTIME_SAFETY_ATTESTATION_TARGET_MISSING"):
            install_remote_startup_attestation({"get_runtime_contract": lambda _: {}}, env=HOSTED, object_store_attached=True)

    def test_invalid_tool_payload_fails_closed(self):
        handles = {
            "get_runtime_contract": lambda _: "not-a-structured-result",
            "get_runtime_health": lambda _: {},
        }
        install_remote_startup_attestation(handles, env=HOSTED, object_store_attached=True)
        with self.assertRaisesRegex(RuntimeError, "RUNTIME_SAFETY_ATTESTATION_TARGET_INVALID"):
            handles["get_runtime_contract"]({})

    def test_remote_adapter_installs_only_on_mcp_tool_handlers(self):
        s = (ROOT / "mcp/server_v61_remote.py").read_text(encoding="utf-8")
        self.assertIn("install_remote_startup_attestation(", s)
        self.assertIn("_production._v61._server.TOOL_HANDLERS", s)
        self.assertLess(s.index("install_remote_startup_attestation("), s.index("def _dispatch("))
        a = s.index("def _public_health(")
        b = s.index("def main(", a)
        self.assertNotIn("startup_attestation", s[a:b])
        self.assertNotIn("remote_startup_safety", s[a:b])


if __name__ == "__main__":
    unittest.main()
