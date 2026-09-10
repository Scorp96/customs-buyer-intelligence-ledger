import tempfile
import unittest
from pathlib import Path


class V63ProductionCheckoutProbeTests(unittest.TestCase):
    def _root(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "unified_runtime").mkdir()
        (root / "mcp").mkdir()
        return td, root

    def test_old_v61_checkout_is_blocked_before_mro_patch(self):
        from unified_runtime.production_checkout_probe import probe_production_checkout
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "__init__.py").write_text("class UnifiedRuntime:\n    pass\n")
        (root / "mcp" / "server_v61.py").write_text("def _invoke_mutation():\n    pass\n")
        result = probe_production_checkout(root)
        self.assertFalse(result["safe_for_v63_mro_patch"])
        self.assertIn("V62_ORCHESTRATION_NOT_PRESENT", result["blockers"])

    def test_v62_like_checkout_allows_read_only_overlay_review(self):
        from unified_runtime.production_checkout_probe import probe_production_checkout
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text("class V61ResearchOrchestrationHardeningMixin: pass\n")
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n"
        )
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS = {'start_investigation'}\n"
            "def _invoke_mutation():\n    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n    pass\n"
        )
        result = probe_production_checkout(root)
        self.assertTrue(result["safe_for_v63_mro_patch"])
        self.assertTrue(result["production_wal_pattern_detected"])
        self.assertFalse(result["v63_mutation_inventory_complete"])
        self.assertFalse(result["safe_to_apply_v63_adapter_patch"])
        self.assertFalse(result["post_patch_binding_complete"])


    def test_v62_checkout_with_recovery_precedents_is_safe_to_apply_adapter_patch_before_v63_names_exist(self):
        from unified_runtime.production_checkout_probe import probe_production_checkout
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text("class V61ResearchOrchestrationHardeningMixin: pass\n")
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n"
        )
        precedents = ["append_peer_discovery", "promote_anchor", "resolve_or_create_account", "append_information_record"]
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS = " + repr(set(precedents)) + "\n"
            "def _invoke_mutation():\n    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n    pass\n"
        )
        result = probe_production_checkout(root)
        self.assertTrue(result["safe_for_v63_mro_patch"])
        self.assertTrue(result["production_wal_pattern_detected"])
        self.assertTrue(result["recovery_precedents_present"])
        self.assertFalse(result["v63_mutation_inventory_complete"])
        self.assertTrue(result["safe_to_apply_v63_adapter_patch"])
        self.assertFalse(result["post_patch_binding_complete"])
        self.assertFalse(result["ready_for_exact_adapter_integration_tests"])

    def test_v63_mutation_inventory_requires_all_three_names_and_recovery_precedents(self):
        from unified_runtime.production_checkout_probe import probe_production_checkout
        from unified_runtime.wal_contract_v63 import V63_WAL_BINDINGS
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text("class V61ResearchOrchestrationHardeningMixin: pass\n")
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n"
        )
        names = sorted(V63_WAL_BINDINGS)
        precedents = ["append_peer_discovery", "promote_anchor", "resolve_or_create_account", "append_information_record"]
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS = " + repr(set(names + precedents)) + "\n"
            "def _invoke_mutation():\n    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n    pass\n"
        )
        result = probe_production_checkout(root)
        self.assertTrue(result["v63_mutation_inventory_complete"])
        self.assertEqual(result["missing_v63_mutation_names"], [])
        self.assertTrue(result["recovery_precedents_present"])
        self.assertEqual(result["missing_recovery_precedent_tools"], [])
        self.assertTrue(result["safe_to_apply_v63_adapter_patch"])
        self.assertTrue(result["post_patch_binding_complete"])
        self.assertTrue(result["ready_for_exact_adapter_integration_tests"])


    def test_new_mutation_names_without_existing_recovery_precedents_are_not_adapter_ready(self):
        from unified_runtime.production_checkout_probe import probe_production_checkout
        from unified_runtime.wal_contract_v63 import V63_WAL_BINDINGS
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text("class V61ResearchOrchestrationHardeningMixin: pass\n")
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n"
        )
        names = sorted(V63_WAL_BINDINGS)
        (root / "mcp" / "server_v61.py").write_text(
            "_MUTATING_TOOLS = " + repr(set(names)) + "\n"
            "def _invoke_mutation():\n    # PREPARED COMMITTED MUTCORR MUTATION_RECONCILIATION_REQUIRED\n    pass\n"
        )
        result = probe_production_checkout(root)
        self.assertTrue(result["v63_mutation_inventory_complete"])
        self.assertFalse(result["recovery_precedents_present"])
        self.assertIn("V63_RECOVERY_PRECEDENTS_NOT_PROVEN", result["blockers"])
        self.assertFalse(result["ready_for_exact_adapter_integration_tests"])

    def test_presence_of_names_without_wal_pattern_is_not_enough(self):
        from unified_runtime.production_checkout_probe import probe_production_checkout
        from unified_runtime.wal_contract_v63 import V63_WAL_BINDINGS
        td, root = self._root()
        self.addCleanup(td.cleanup)
        (root / "unified_runtime" / "research_orchestration_hardening.py").write_text("class V61ResearchOrchestrationHardeningMixin: pass\n")
        (root / "unified_runtime" / "__init__.py").write_text(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n"
            "class UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n):\n    pass\n"
        )
        names = " ".join(V63_WAL_BINDINGS)
        (root / "mcp" / "server_v61.py").write_text(names)
        result = probe_production_checkout(root)
        self.assertTrue(result["v63_mutation_inventory_complete"])
        self.assertFalse(result["production_wal_pattern_detected"])
        self.assertFalse(result["ready_for_exact_adapter_integration_tests"])
