"""Regression: machinery expansion must not consume signage/PVC channel budget.

Synthetic no-network tests; no production persistence or buyer promotion.
"""
from __future__ import annotations

import unittest

from unified_runtime.expansion_planner import BRANCH_GROUPS, plan_expansion
from unified_runtime.demand_expansion import V63DemandExpansionMixin
from unified_runtime.source_execution import SOURCE_FAMILIES_BY_BRANCH_GROUP


class _ReadModel(V63DemandExpansionMixin):
    pass


class MachineryChannelExpansionTests(unittest.TestCase):
    def test_machinery_channel_excludes_plastic_sheet_supply_chain(self):
        out = plan_expansion({
            "product_profile_id": "SOAP_MACHINERY",
            "geography": "Indonesia",
        })
        channels = out["branches"]["CHANNEL_GRAPH"]
        self.assertIn("machinery_importer", channels)
        self.assertIn("machinery_distributor", channels)
        self.assertIn("equipment_integrator", channels)
        self.assertIn("turnkey_production_line_integrator", channels)
        for forbidden in ("building_material_supplier", "sign_material_supplier", "specialty_sheet_distributor"):
            self.assertNotIn(forbidden, channels)
        self.assertEqual(set(out["branch_groups"]), set(BRANCH_GROUPS))
        self.assertFalse(out["policy"]["planning_is_execution_proof"])

    def test_pvc_legacy_channel_unchanged(self):
        out = plan_expansion({"product_profile_id": "PVC", "geography": "Brazil"})
        self.assertEqual(out["branches"]["CHANNEL_GRAPH"], list(BRANCH_GROUPS["CHANNEL_GRAPH"]))
        self.assertIn("sign_material_supplier", out["branches"]["CHANNEL_GRAPH"])

    def test_wpc_remains_unchanged(self):
        out = plan_expansion({"product_profile_id": "WPC", "geography": "Mexico"})
        self.assertEqual(out["branches"]["CHANNEL_GRAPH"], list(BRANCH_GROUPS["CHANNEL_GRAPH"]))

    def test_readonly_machinery_plan_uses_existing_source_families(self):
        result = _ReadModel().plan_candidate_expansion({
            "product_profile_id": "SOAP_MACHINERY",
            "product_variant": "VACUUM_EMULSIFIER",
            "geography": "Indonesia",
            "limit": 12,
            "source_task_limit": 18,
        })
        channels = result["expansion_plan"]["branches"]["CHANNEL_GRAPH"]
        self.assertIn("machinery_distributor", channels)
        self.assertNotIn("sign_material_supplier", channels)
        self.assertIn("CHANNEL_GRAPH", SOURCE_FAMILIES_BY_BRANCH_GROUP)
        self.assertTrue(result["host_execution_required"])
        self.assertFalse(result["planning_is_execution_proof"])
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertTrue(all(not x["search_execution_performed"] for x in result["source_plan"]["tasks"]))

    def test_invalid_profile_is_not_silently_machinery(self):
        with self.assertRaises(KeyError):
            plan_expansion({"product_profile_id": "NOT_AN_ACTUAL_PROFILE", "geography": "Indonesia"})


if __name__ == "__main__":
    unittest.main()
