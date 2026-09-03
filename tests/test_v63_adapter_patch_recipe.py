import json
import tempfile
import unittest
from pathlib import Path

from unified_runtime.mcp_schema_v63 import V63_MUTATION_TOOL_NAMES, V63_READ_ONLY_TOOL_NAMES


class V63AdapterPatchRecipeTests(unittest.TestCase):
    def _repo(self, root: Path, *, postpatch=False, omit_tool_registry=False):
        (root / "unified_runtime").mkdir(parents=True)
        (root / "mcp").mkdir(parents=True)
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text(
            "class V61ResearchOrchestrationHardeningMixin: pass\n", encoding="utf-8"
        )
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n",
            encoding="utf-8",
        )
        precedents = [
            "append_peer_discovery",
            "promote_anchor",
            "resolve_or_create_account",
            "append_information_record",
        ]
        mutations = list(V63_MUTATION_TOOL_NAMES) if postpatch else []
        tool_names = precedents + (list(V63_READ_ONLY_TOOL_NAMES) + mutations if postpatch else [])
        descriptors = "" if omit_tool_registry else (
            "TOOL_DEFINITIONS = [\n"
            + "".join(f"    {{'name': {name!r}, 'inputSchema': {{'type':'object'}}}},\n" for name in tool_names)
            + "]\n"
        )
        handlers = (
            "def _invoke_mutation(tool_name, handler, arguments):\n"
            "    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n"
            "    return handler(arguments)\n"
            "def _peer_handler(arguments):\n"
            "    return _invoke_mutation('append_peer_discovery', runtime.append_peer_discovery, arguments)\n"
            "def _promote_handler(arguments):\n"
            "    return _invoke_mutation('promote_anchor', runtime.promote_anchor, arguments)\n"
            "def _canonical_handler(arguments):\n"
            "    return _invoke_mutation('resolve_or_create_account', runtime.resolve_or_create_account, arguments)\n"
            "def _information_handler(arguments):\n"
            "    return _invoke_mutation('append_information_record', runtime.append_information_record, arguments)\n"
        )
        dispatch = {
            "append_peer_discovery": "_peer_handler",
            "promote_anchor": "_promote_handler",
            "resolve_or_create_account": "_canonical_handler",
            "append_information_record": "_information_handler",
        }
        if postpatch:
            handlers += (
                "def _candidate_handler(arguments):\n"
                "    return _invoke_mutation('append_candidate_discovery', runtime.append_candidate_discovery, arguments)\n"
                "def _opportunity_handler(arguments):\n"
                "    return _invoke_mutation('create_product_opportunity', runtime.create_product_opportunity, arguments)\n"
                "def _anchor_handler(arguments):\n"
                "    return _invoke_mutation('promote_opportunity_anchor', runtime.promote_opportunity_anchor, arguments)\n"
            )
            dispatch.update({
                "append_candidate_discovery": "_candidate_handler",
                "create_product_opportunity": "_opportunity_handler",
                "promote_opportunity_anchor": "_anchor_handler",
            })
            for tool in V63_READ_ONLY_TOOL_NAMES:
                handler = f"_v63_ro_{tool}"
                handlers += f"def {handler}(arguments):\n    return runtime.{tool}(arguments)\n"
                dispatch[tool] = handler
        dispatch_text = "HANDLERS = {\n" + "".join(
            f"    {tool!r}: {handler},\n" for tool, handler in dispatch.items()
        ) + "}\n"
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS = " + repr(set(precedents + mutations)) + "\n"
            + descriptors + handlers + dispatch_text,
            encoding="utf-8",
        )
        (root / "mcp" / "server_v61_backup_recovery.py").write_text(
            "from .server_v61 import *\n", encoding="utf-8"
        )
        (root / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"cbi": {"args": ["mcp/server_v61_backup_recovery.py", "--stdio"]}}}),
            encoding="utf-8",
        )
        return root

    def test_prepatch_checkout_produces_non_mutating_codegen_recipe(self):
        from unified_runtime.adapter_patch_recipe_v63 import build_v63_adapter_patch_recipe
        with tempfile.TemporaryDirectory() as td:
            result = build_v63_adapter_patch_recipe(self._repo(Path(td)))
        self.assertEqual(result["status"], "READY_FOR_ADAPTER_CODEGEN")
        self.assertFalse(result["modifies_checkout"])
        self.assertFalse(result["switches_production_entrypoint"])
        self.assertEqual(len(result["source_pins"]["mcp/server_v61.py"]), 64)
        self.assertTrue(result["source_pins_must_match_before_codegen"])
        self.assertEqual(set(result["mutation_registry_additions"]), set(V63_MUTATION_TOOL_NAMES))
        self.assertEqual(set(result["tool_descriptors_to_add"]), set(V63_MUTATION_TOOL_NAMES) | set(V63_READ_ONLY_TOOL_NAMES))
        for tool in V63_MUTATION_TOOL_NAMES:
            self.assertEqual(result["handler_plan"][tool]["invocation"], "EXISTING_PRODUCTION_INVOKE_MUTATION")
            self.assertEqual(result["handler_plan"][tool]["runtime_target"], tool)
        for tool in V63_READ_ONLY_TOOL_NAMES:
            self.assertEqual(result["handler_plan"][tool]["invocation"], "READ_ONLY_RUNTIME_DIRECT")
        self.assertEqual(result["next_gate"], "GENERATE_PATCH_ONLY_AFTER_EXACT_CHECKOUT_RECHECK")

    def test_unproven_tool_registry_blocks_recipe(self):
        from unified_runtime.adapter_patch_recipe_v63 import build_v63_adapter_patch_recipe
        with tempfile.TemporaryDirectory() as td:
            result = build_v63_adapter_patch_recipe(self._repo(Path(td), omit_tool_registry=True))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("MCP_TOOL_REGISTRY_NOT_PROVEN", result["blockers"])
        self.assertFalse(result["codegen_allowed"])

    def test_existing_adapter_surface_waits_for_runtime_durable_backend_not_codegen(self):
        from unified_runtime.adapter_patch_recipe_v63 import build_v63_adapter_patch_recipe
        with tempfile.TemporaryDirectory() as td:
            result = build_v63_adapter_patch_recipe(self._repo(Path(td), postpatch=True))
        self.assertEqual(result["status"], "ADAPTER_SURFACE_PRESENT_BACKEND_PENDING")
        self.assertFalse(result["codegen_allowed"])
        self.assertTrue(result["binding_plan"]["adapter_surface_complete"])
        self.assertFalse(result["binding_plan"]["runtime_durable_backend_binding_proven"])
        self.assertEqual(result["next_gate"], "BIND_RUNTIME_DURABLE_BACKEND_ON_EXACT_CHECKOUT")


if __name__ == "__main__":
    unittest.main()
