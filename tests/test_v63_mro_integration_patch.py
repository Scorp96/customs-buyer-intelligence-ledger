import unittest

from unified_runtime.mro_integration_patch import adapt_runtime_init_text


V62_BASE = '''from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\nfrom .acceptance_hardening import V61AcceptanceHardeningMixin\n\nRUNTIME_VERSION = V6_RUNTIME_VERSION\nBUILD_ID = V6_BUILD_ID\n\nclass UnifiedRuntime(\n    V61ResearchOrchestrationHardeningMixin,\n    V61AcceptanceHardeningMixin,\n    V6RuntimeMixin,\n):\n    pass\n'''


class V63MROIntegrationPatchTests(unittest.TestCase):
    def test_inserts_v63_import_and_makes_it_first_mro_base(self):
        result = adapt_runtime_init_text(V62_BASE)
        self.assertEqual(result.count("from .demand_expansion import V63DemandExpansionMixin"), 1)
        class_tail = result[result.index("class UnifiedRuntime") :]
        self.assertLess(
            class_tail.index("V63DemandExpansionMixin,"),
            class_tail.index("V61ResearchOrchestrationHardeningMixin,"),
        )

    def test_edit_is_idempotent(self):
        once = adapt_runtime_init_text(V62_BASE)
        twice = adapt_runtime_init_text(once)
        self.assertEqual(once, twice)

    def test_preserves_other_existing_mixins(self):
        drifted = V62_BASE.replace(
            "class UnifiedRuntime(\n",
            "from .cloud_hardening import CloudMixin\n\nclass UnifiedRuntime(\n    CloudMixin,\n",
        )
        result = adapt_runtime_init_text(drifted)
        self.assertIn("CloudMixin,", result)
        class_tail = result[result.index("class UnifiedRuntime") :]
        self.assertLess(class_tail.index("V63DemandExpansionMixin,"), class_tail.index("CloudMixin,"))

    def test_refuses_pre_v62_runtime_without_orchestration_mixin(self):
        pre_v62 = V62_BASE.replace(
            "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin\n",
            "",
        ).replace("    V61ResearchOrchestrationHardeningMixin,\n", "")
        with self.assertRaisesRegex(RuntimeError, "V6.2 orchestration baseline"):
            adapt_runtime_init_text(pre_v62)

    def test_refuses_ambiguous_unified_runtime_declaration(self):
        ambiguous = V62_BASE + "\nclass UnifiedRuntime(OtherMixin):\n    pass\n"
        with self.assertRaises(RuntimeError):
            adapt_runtime_init_text(ambiguous)


if __name__ == "__main__":
    unittest.main()
