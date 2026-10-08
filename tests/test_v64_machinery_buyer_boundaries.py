"""Safety regression for machinery discovery vs verified seller capability.

No production credentials, external crawling, or network calls in these tests.
"""
from __future__ import annotations

import unittest
import json
from pathlib import Path

from unified_runtime.capability_profile import (
    build_capability_profile,
    evaluate_capability_fit,
)
from unified_runtime.demand_expansion import V63DemandExpansionMixin
from unified_runtime.product_profiles import (
    get_product_profile,
    list_product_profiles,
    classify_product_alias,
)


class _ReadModel(V63DemandExpansionMixin):
    pass


class MachineryProductBoundaryTests(unittest.TestCase):
    def test_machinery_is_a_distinct_buyer_discovery_taxonomy(self):
        profile = get_product_profile("SOAP_MACHINERY")
        self.assertEqual(profile["product_scope"], "BUYER_DISCOVERY_TAXONOMY_ONLY")
        self.assertEqual(profile["seller_capability_default"], "UNCONFIGURED")
        self.assertIn("LIQUID_WASHING_MIXER", profile["variants"])
        self.assertNotIn("SOLID_SOAP_PLODDER", profile["variants"])
        self.assertEqual(profile["cross_sell_profiles"], [])
        self.assertIn("SOAP_MACHINERY", {p["profile_id"] for p in list_product_profiles()})
        self.assertNotIn("PVC", " ".join(profile["positive_search_vocabulary"]).upper())

    def test_machine_alias_is_discovery_not_seller_spec(self):
        result = classify_product_alias("liquid detergent manufacturing equipment")
        self.assertEqual(result["profile_id"], "SOAP_MACHINERY")
        self.assertEqual(result["classification"], "COMMERCIAL_ALIAS")
        self.assertFalse(result["technical_identity_verified"])

    def test_six_branch_plan_works_without_implying_execution(self):
        plan = _ReadModel().plan_candidate_expansion({
            "product_profile_id": "SOAP_MACHINERY",
            "product_variant": "LIQUID_WASHING_MIXER",
            "geography": "Ghana",
            "limit": 30,
        })
        self.assertEqual(plan["status"], "PLANNED")
        self.assertFalse(plan["planning_is_execution_proof"])
        self.assertTrue(plan["host_execution_required"])
        self.assertEqual(plan["expansion_plan"]["product_profile_id"], "SOAP_MACHINERY")
        self.assertTrue(plan["source_plan"])
        discovery = plan["discovery_plan"]
        self.assertFalse(discovery["source_coverage_complete"])
        self.assertTrue(discovery["queries"])
        self.assertTrue(all(not row["search_execution_performed"] for row in discovery["queries"]))
        self.assertTrue(any("liquid washing" in row["query"].lower() for row in discovery["queries"]))
        self.assertFalse(any("foam board" in row["query"].lower() for row in discovery["queries"]))

    def test_unknown_machine_variant_does_not_become_qualified(self):
        machine = get_product_profile("SOAP_MACHINERY")
        self.assertNotIn("SOAP_PLODDER", machine["variants"])

    def test_unbound_machine_seller_remains_unconfigured(self):
        model = _ReadModel()
        result = model.get_capability_profile({"product_profile_id": "SOAP_MACHINERY"})
        self.assertEqual(result["status"], "UNCONFIGURED")
        self.assertEqual(result["reason"], "CAPABILITY_PROFILE_NOT_BOUND")
        fit = model.evaluate_capability_fit({
            "product_profile_id": "SOAP_MACHINERY",
            "demand": {"product_profile_id": "SOAP_MACHINERY", "product_variant": "LIQUID_WASHING_MIXER"},
        })
        self.assertEqual(fit["status"], "UNCONFIGURED")
        self.assertIsNone(fit["capability_fit"])

    def test_legacy_sheet_matcher_cannot_certify_machine_even_with_claims(self):
        # The legacy matcher's sheet-specific attributes have no throughput or
        # installation safety fields, so even a sourced seller claim cannot
        # imply a full machine-to-buyer technical fit.
        capability = build_capability_profile({
            "capability_profile_id": "TEST-MACHINERY-EXPLICIT",
            "version": "1",
            "product_profile_id": "SOAP_MACHINERY",
            "supported_variants": ["LIQUID_WASHING_MIXER"],
            "verified_claims": ["LIQUID_WASHING_MIXER"],
            "validation_status": "VERIFIED",
            "evidence_sources": [{"url": "https://www.gzsmartors.com/nd.jsp?fromMid=780&id=8"}],
        })
        fit = evaluate_capability_fit(capability, {
            "product_profile_id": "SOAP_MACHINERY",
            "product_variant": "LIQUID_WASHING_MIXER",
            "required_claims": ["LIQUID_WASHING_MIXER"],
        })
        self.assertEqual(fit["capability_fit"], "NEEDS_VERIFICATION")
        self.assertIn("MACHINERY_TECHNICAL_SPEC_MATCHER_UNCONFIGURED", fit["reasons"])
        self.assertEqual(fit["missing_verified_claims"], [])

    def test_legacy_portfolio_priority_is_not_current_seller_identity(self):
        from unified_runtime.contract_v63 import build_v63_contract
        contract = build_v63_contract()
        self.assertEqual(contract["primary_product_profile"], "PVC")  # compatibility only
        self.assertEqual(contract["primary_product_profile_scope"], "LEGACY_PORTFOLIO_COMPATIBILITY_ONLY")
        self.assertIsNone(contract["active_seller_product_profile_id"])
        self.assertTrue(contract["seller_profile_requires_explicit_binding"])
        self.assertIn("SOAP_MACHINERY", contract["product_profiles"])

    def test_plugin_publisher_identity_is_seller_neutral(self):
        root = Path(__file__).resolve().parents[1]
        for path in ("plugin.json", ".codex-plugin/plugin.json"):
            manifest = json.loads((root / path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["author"]["name"], "CBI Research Platform")

    def test_legacy_pvc_remains_separate(self):
        self.assertIn("PVC_FOAM_BOARD", get_product_profile("PVC")["subfamilies"])
        model = _ReadModel()
        self.assertEqual(model.get_capability_profile({})["reason"],
                         "EXPLICIT_SELLER_PRODUCT_PROFILE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
