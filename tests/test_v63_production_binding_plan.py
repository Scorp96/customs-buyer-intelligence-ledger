import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.mcp_schema_v63 import V63_READ_ONLY_TOOL_NAMES


class V63ProductionBindingPlanTests(unittest.TestCase):
    def _root(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "unified_runtime").mkdir()
        (root / "mcp").mkdir()
        return td, root

    def _write_v62_runtime(self, root: Path):
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text(
            "class V61ResearchOrchestrationHardeningMixin: pass\n",
            encoding="utf-8",
        )
        (root / "unified_runtime" / "v6.py").write_text(
            "class V6RuntimeMixin:\n"
            "    def append_peer_discovery(self, arguments):\n"
            "        return self.store.append(arguments['investigation_id'], 'V6_PEER_DISCOVERED', arguments)\n"
            "    def promote_anchor(self, arguments):\n"
            "        return self.store.append(arguments['investigation_id'], 'V6_ANCHOR_PROMOTED', arguments)\n"
            "    def append_information_record(self, arguments):\n"
            "        return self.store.append(arguments['investigation_id'], 'INFORMATION_RECORD_APPENDED', arguments)\n",
            encoding="utf-8",
        )
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n",
            encoding="utf-8",
        )

    def _write_prepatch_adapter(self, root: Path, include_v63=False, include_v63_tool_surface=True):
        precedents = [
            "append_peer_discovery",
            "promote_anchor",
            "resolve_or_create_account",
            "append_information_record",
        ]
        v63 = [
            "append_candidate_discovery",
            "create_product_opportunity",
            "promote_opportunity_anchor",
        ]
        names = list(precedents) + (v63 if include_v63 else [])
        descriptor_names = list(precedents) + ((list(V63_READ_ONLY_TOOL_NAMES) + v63) if include_v63 and include_v63_tool_surface else [])
        descriptors = "TOOL_DEFINITIONS = [\n" + "".join(
            f"    {{'name': {name!r}, 'inputSchema': {{'type':'object'}}}},\n" for name in descriptor_names
        ) + "]\n"
        base_handlers = (
            "def _peer_handler(arguments):\n"
            "    return _invoke_mutation('append_peer_discovery', runtime.append_peer_discovery, arguments)\n"
            "def _promote_handler(arguments):\n"
            "    return _invoke_mutation('promote_anchor', runtime.promote_anchor, arguments)\n"
            "def _canonical_handler(arguments):\n"
            "    return _invoke_mutation('resolve_or_create_account', runtime.resolve_or_create_account, arguments)\n"
            "def _information_handler(arguments):\n"
            "    return _invoke_mutation('append_information_record', runtime.append_information_record, arguments)\n"
        )
        v63_handlers = ""
        if include_v63:
            v63_handlers = (
                "def _candidate_handler(arguments):\n"
                "    return _invoke_mutation('append_candidate_discovery', runtime.append_candidate_discovery, arguments)\n"
                "def _opportunity_handler(arguments):\n"
                "    return _invoke_mutation('create_product_opportunity', runtime.create_product_opportunity, arguments)\n"
                "def _anchor_handler(arguments):\n"
                "    return _invoke_mutation('promote_opportunity_anchor', runtime.promote_opportunity_anchor, arguments)\n"
            )
        read_only_handlers = ""
        if include_v63 and include_v63_tool_surface:
            for tool in V63_READ_ONLY_TOOL_NAMES:
                handler = f"_v63_ro_{tool}"
                read_only_handlers += (
                    f"def {handler}(arguments):\n"
                    f"    return runtime.{tool}(arguments)\n"
                )
        dispatch = {
            "append_peer_discovery": "_peer_handler",
            "promote_anchor": "_promote_handler",
            "resolve_or_create_account": "_canonical_handler",
            "append_information_record": "_information_handler",
        }
        if include_v63 and include_v63_tool_surface:
            dispatch.update({tool: f"_v63_ro_{tool}" for tool in V63_READ_ONLY_TOOL_NAMES})
            dispatch.update({
                "append_candidate_discovery": "_candidate_handler",
                "create_product_opportunity": "_opportunity_handler",
                "promote_opportunity_anchor": "_anchor_handler",
            })
        dispatch_text = "HANDLERS = {\n" + "".join(
            f"    {tool!r}: {handler},\n" for tool, handler in dispatch.items()
        ) + "}\n"
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS = " + repr(set(names)) + "\n"
            + descriptors
            + "def _invoke_mutation(tool_name, handler, arguments):\n"
            + "    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n"
            + "    return handler(arguments)\n"
            + base_handlers + v63_handlers + read_only_handlers + dispatch_text,
            encoding="utf-8",
        )
        (root / "mcp" / "server_v61_peer_pivot_recovery.py").write_text(
            "from . import server_v61 as _base\n"
            "def _recover_peer(intent, durable_events):\n"
            "    arguments = intent['arguments']\n"
            "    correlation_id = intent['correlation_id']\n"
            "    return {'status':'RECOVERED','arguments':arguments,'correlation_id':correlation_id} if durable_events else {'status':'MUTATION_RECONCILIATION_REQUIRED'}\n"
            "def _recover_anchor(intent, durable_events):\n"
            "    arguments = intent['arguments']\n"
            "    correlation_id = intent['correlation_id']\n"
            "    return {'status':'RECOVERED','arguments':arguments,'correlation_id':correlation_id} if durable_events else {'status':'MUTATION_RECONCILIATION_REQUIRED'}\n"
            "RECOVERY_HANDLERS={'append_peer_discovery':_recover_peer,'promote_anchor':_recover_anchor}\n",
            encoding="utf-8",
        )
        (root / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from . import server_v61_peer_pivot_recovery as _v61\n",
            encoding="utf-8",
        )
        (root / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"cbi": {"command": "python", "args": ["mcp/server_v61_backup_recovery.py", "--stdio"]}}}),
            encoding="utf-8",
        )

    def test_old_v61_checkout_is_blocked(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "__init__.py").write_text("class UnifiedRuntime: pass\n", encoding="utf-8")
        (root / "mcp" / "server_v61.py").write_text("def _invoke_mutation(): pass\n", encoding="utf-8")
        result = build_v63_production_binding_plan(root)
        self.assertEqual(result["status"], "BLOCKED_PREPATCH")
        self.assertFalse(result["can_apply_patch"])
        self.assertIn("V62_ORCHESTRATION_NOT_PRESENT", result["blockers"])

    def test_v62_prepatch_checkout_builds_runtime_and_adapter_plan(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        self._write_v62_runtime(root)
        self._write_prepatch_adapter(root, include_v63=False)
        result = build_v63_production_binding_plan(root)
        self.assertEqual(result["status"], "READY_FOR_PATCH_APPLICATION")
        self.assertTrue(result["can_apply_patch"])
        self.assertEqual(result["active_mcp_entrypoint"], "mcp/server_v61_backup_recovery.py")
        self.assertTrue(result["active_mcp_entrypoint_exists"])
        self.assertIn("unified_runtime/demand_expansion.py", result["runtime_payload_files"])
        self.assertNotIn("unified_runtime/__init__.py", result["runtime_payload_files"])
        self.assertEqual(
            set(result["durable_mutations"]),
            {"append_candidate_discovery", "create_product_opportunity", "promote_opportunity_anchor"},
        )
        self.assertTrue(result["runtime_mro_patch_required"])
        self.assertTrue(result["adapter_patch_required"])
        self.assertFalse(result["post_patch_binding_complete"])
        self.assertTrue(result["adapter_codegen_ready"])
        self.assertEqual(result["adapter_structure"]["mutation_registry_candidates"], ["_MUTATING_TOOLS"])

    def test_missing_active_mcp_entrypoint_blocks_patch_application(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        self._write_v62_runtime(root)
        self._write_prepatch_adapter(root, include_v63=False)
        (root / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"cbi": {"args": ["mcp/server_v61_missing.py", "--stdio"]}}}),
            encoding="utf-8",
        )
        result = build_v63_production_binding_plan(root)
        self.assertFalse(result["can_apply_patch"])
        self.assertIn("ACTIVE_MCP_ENTRYPOINT_MISSING", result["blockers"])


    def _passing_backend_acceptance(self, snapshot_sha="a" * 64):
        from unified_runtime.backend_correlation_acceptance_v63 import REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
        return {
            "schema": "cbi.v63-backend-correlation-acceptance.v1",
            "adapter_path_exercised": "EXISTING_PRODUCTION_INVOKE_MUTATION",
            "runtime_store_exercised": "EXISTING_PRODUCTION_APPEND_ONLY_STORE",
            "production_source_snapshot_sha256": snapshot_sha,
            "scenarios": [
                {
                    "scenario": name,
                    "status": "PASS",
                    "reexecute_side_effect": False,
                    "exact_correlation_proven": True,
                    "exact_request_hash_proven": True,
                    "cross_key_result_claimed": False,
                } for name in REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS
            ],
        }

    def _passing_recovery_acceptance(self, snapshot_sha="a" * 64):
        from unified_runtime.recovery_overlay_acceptance_v63 import REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS
        return {
            "schema": "cbi.v63-recovery-overlay-acceptance.v1",
            "active_overlay_path_exercised": "ACTIVE_PRODUCTION_SERVER_V61_OVERLAY_CHAIN",
            "production_source_snapshot_sha256": snapshot_sha,
            "recovery_registry_file": "mcp/server_v61_peer_pivot_recovery.py",
            "recovery_registry_name": "RECOVERY_HANDLERS",
            "reference_runner_only": False,
            "scenarios": [
                {
                    "scenario": name,
                    "status": "PASS",
                    "active_overlay_handler_exercised": True,
                    "reexecute_side_effect": False,
                    "exact_correlation_proven": True,
                    "exact_request_hash_proven": True,
                    "exact_result_snapshot_proven": True if name == "OPPORTUNITY_EXACT_SNAPSHOT_RECOVERS" else None,
                } for name in REQUIRED_V63_RECOVERY_OVERLAY_SCENARIOS
            ],
        }

    def test_postpatch_surface_plus_source_bound_backend_acceptance_reaches_exact_adapter_tests(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        self._write_v62_runtime(root)
        self._write_prepatch_adapter(root, include_v63=True)
        result = build_v63_production_binding_plan(
            root,
            backend_correlation_acceptance_report=self._passing_backend_acceptance(),
            recovery_overlay_acceptance_report=self._passing_recovery_acceptance(),
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertEqual(result["status"], "READY_FOR_EXACT_ADAPTER_TESTS")
        self.assertTrue(result["runtime_durable_backend_binding_proven"])
        self.assertTrue(result["recovery_overlay_binding_proven"])
        self.assertTrue(result["post_patch_binding_complete"])
        self.assertTrue(result["exact_adapter_tests_required"])
        self.assertEqual(result["runtime_backend_binding_plan"]["status"], "BACKEND_BINDING_PROVEN")

    def test_backend_acceptance_without_live_recovery_overlay_stays_pending(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        self._write_v62_runtime(root)
        self._write_prepatch_adapter(root, include_v63=True)
        result = build_v63_production_binding_plan(
            root,
            backend_correlation_acceptance_report=self._passing_backend_acceptance(),
            expected_production_source_snapshot_sha256="a" * 64,
        )
        self.assertEqual(result["status"], "BACKEND_READY_RECOVERY_OVERLAY_PENDING")
        self.assertTrue(result["runtime_durable_backend_binding_proven"])
        self.assertFalse(result["recovery_overlay_binding_proven"])
        self.assertFalse(result["post_patch_binding_complete"])
        self.assertIn("V63_RECOVERY_OVERLAY_NOT_BOUND", result["postpatch_gaps"])

    def test_postpatch_adapter_surface_still_waits_for_runtime_durable_backend(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        self._write_v62_runtime(root)
        self._write_prepatch_adapter(root, include_v63=True)
        result = build_v63_production_binding_plan(root)
        self.assertEqual(result["status"], "ADAPTER_SURFACE_READY_BACKEND_PENDING")
        self.assertFalse(result["post_patch_binding_complete"])
        self.assertFalse(result["adapter_patch_required"])
        self.assertFalse(result["exact_adapter_tests_required"])
        self.assertTrue(result["adapter_surface_complete"])
        self.assertTrue(result["runtime_durable_backend_binding_required"])
        self.assertFalse(result["runtime_durable_backend_binding_proven"])
        self.assertEqual(result["runtime_backend_binding_plan"]["status"], "BACKEND_BINDING_BLOCKED")
        self.assertIn("V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND", result["postpatch_gaps"])
        self.assertTrue(result["adapter_structure"]["v63_handler_binding_complete"])
        self.assertTrue(result["adapter_structure"]["v63_tool_descriptor_complete"])
        self.assertTrue(result["adapter_structure"]["v63_dispatch_binding_complete"])


    def test_postpatch_handler_without_tool_surface_stays_in_patch_application(self):
        from unified_runtime.production_binding_plan import build_v63_production_binding_plan
        td, root = self._root()
        self.addCleanup(td.cleanup)
        self._write_v62_runtime(root)
        self._write_prepatch_adapter(root, include_v63=True, include_v63_tool_surface=False)
        result = build_v63_production_binding_plan(root)
        self.assertEqual(result["status"], "READY_FOR_PATCH_APPLICATION")
        self.assertFalse(result["post_patch_binding_complete"])
        self.assertIn("V63_TOOL_DESCRIPTORS_INCOMPLETE", result["postpatch_gaps"])
        self.assertIn("V63_DISPATCH_BINDING_INCOMPLETE", result["postpatch_gaps"])



if __name__ == "__main__":
    unittest.main()
