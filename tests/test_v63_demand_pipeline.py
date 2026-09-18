import unittest

from unified_runtime.demand_pipeline import (
    plan_customs_seed_expansion,
    qualify_candidate_opportunity,
)


class V63DemandPipelineTests(unittest.TestCase):
    def test_pvc_celuka_customs_seed_becomes_m1_market_plan(self):
        result = plan_customs_seed_expansion({
            "account_id": "C100",
            "opportunity_id": "OPP-C100-PVC-PRIMARY",
            "source_evidence_ids": ["E-CUSTOMS-1"],
            "shipment_date": "2026-08-02",
            "shipment_weight_kg": 20000,
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "geography": "Vietnam-HCMC",
            "supplier_ids": ["SUP-1"],
            "anchor_grade": "B+",
            "anchor_score": 84.0,
            "local_language_terms": ["tấm nhựa PVC", "tủ bếp"],
        })
        self.assertEqual(result["demand_anchor"]["source_type"], "CUSTOMS")
        self.assertEqual(result["market_acceptance"]["level"], "M1")
        self.assertEqual(result["market_scope"]["scope"], "CITY_AND_NEARBY")
        self.assertFalse(result["market_scope"]["country_wide_demand_proven"])
        self.assertIn("CABINETRY", result["market_cell"]["application_ids"])
        self.assertIn("CABINET_MANUFACTURER", result["market_cell"]["buyer_archetype_ids"])
        self.assertEqual(len(result["expansion_plan"]["branch_groups"]), 6)
        self.assertGreater(result["discovery_plan"]["returned_count"], 0)
        self.assertFalse(result["discovery_plan"]["planning_is_execution_proof"])
        self.assertFalse(result["discovery_plan"]["source_coverage_complete"])

    def test_unknown_variant_does_not_invent_application_mapping(self):
        result = plan_customs_seed_expansion({
            "account_id": "C100",
            "opportunity_id": "OPP-C100-PVC-PRIMARY",
            "source_evidence_ids": ["E-CUSTOMS-1"],
            "shipment_date": "2026-08-02",
            "product_profile_id": "PVC",
            "product_variant": "UNVERIFIED_MARKETING_BOARD",
            "geography": "US-MA",
            "anchor_grade": "B+",
            "anchor_score": 84.0,
        })
        self.assertEqual(result["market_cell"]["application_ids"], [])
        self.assertEqual(result["market_cell"]["buyer_archetype_ids"], [])
        self.assertTrue(result["product_mapping_requires_research"])

    def test_candidate_qualification_keeps_anchor_procurement_evidence_separate(self):
        result = qualify_candidate_opportunity({
            "candidate": {
                "candidate_id": "CAN-1",
                "discovered_from_anchor_id": "DA-1",
                "branch_group": "APPLICATION_GRAPH",
                "branch": "downstream_manufacturer",
                "company_name": "Example Cabinet Co",
                "product_profile_id": "PVC",
            },
            "canonical_resolution": {
                "canonical_status": "CONFIRMED",
                "canonical_account_id": "C501",
                "resolver_authority": "PRIMARY_LEGAL_NAME_COUNTRY",
                "resolver_is_existing_production_authority": True,
                "ambiguous": False,
                "address_only_match": False,
                "alias_only_match": False,
                "tax_conflict": False,
                "country_conflict": False,
            },
            "candidate_account_id": "C501",
            "product_variant": "CELUKA",
            "commercial_value_grade": "A",
            "commercial_score": 92.0,
            "commercial_evidence_bound": True,
            "canonical_status": "CONFIRMED",
            "novelty_signals": ["NEW_MARKET_CELL"],
            "anchor_grade": "B+",
            "anchor_score": 84.0,
            "outreach_readiness": "IDENTITY_ONLY",
        })
        self.assertEqual(result["candidate"]["procurement_evidence_ids"], [])
        self.assertEqual(result["opportunity"]["product_evidence_ids"], [])
        self.assertEqual(result["relative"]["relative_class"], "UPGRADE_TARGET")
        self.assertTrue(result["contact_plan"]["company_route_required"])
        self.assertGreater(result["contact_source_plan"]["returned_count"], 0)
        self.assertFalse(result["contact_source_plan"]["planning_is_execution_proof"])
        self.assertTrue(result["anchor_eligibility"]["anchor_eligible"])
        self.assertFalse(result["anchor_eligibility"]["contact_readiness_is_gate"])

    def test_bplus_candidate_without_novelty_stays_non_anchor(self):
        result = qualify_candidate_opportunity({
            "candidate": {
                "candidate_id": "CAN-2",
                "discovered_from_anchor_id": "DA-1",
                "branch_group": "MARKET_GRAPH",
                "branch": "regional_peer",
                "company_name": "Example Regional Co",
                "product_profile_id": "PVC",
            },
            "canonical_resolution": {
                "canonical_status": "CONFIRMED",
                "canonical_account_id": "C502",
                "resolver_authority": "PRIMARY_LEGAL_NAME_COUNTRY",
                "resolver_is_existing_production_authority": True,
                "ambiguous": False,
                "address_only_match": False,
                "alias_only_match": False,
                "tax_conflict": False,
                "country_conflict": False,
            },
            "candidate_account_id": "C502",
            "commercial_value_grade": "B+",
            "commercial_score": 85.0,
            "commercial_evidence_bound": True,
            "canonical_status": "CONFIRMED",
            "novelty_signals": [],
            "anchor_grade": "B+",
            "anchor_score": 84.0,
            "outreach_readiness": "COMPANY_ROUTE_READY",
        })
        self.assertEqual(result["relative"]["relative_class"], "SAME_TIER")
        self.assertFalse(result["anchor_eligibility"]["anchor_eligible"])
        self.assertIn("BPLUS_REQUIRES_MATERIAL_NOVELTY", result["anchor_eligibility"]["blockers"])


if __name__ == "__main__":
    unittest.main()

class V63LocalizedDemandPipelineTests(unittest.TestCase):
    def test_customs_seed_locale_automatically_uses_curated_local_terms(self):
        result = plan_customs_seed_expansion({
            "account_id": "C100",
            "opportunity_id": "OPP-C100-PVC-PRIMARY",
            "source_evidence_ids": ["E-CUSTOMS-LOCAL-1"],
            "shipment_date": "2026-08-02",
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "geography": "Vietnam-HCMC",
            "locale": "vi-VN",
            "anchor_grade": "B+",
            "anchor_score": 84.0,
        })
        joined = "\n".join(row["query"] for row in result["discovery_plan"]["queries"]).casefold()
        self.assertIn("tấm pvc foam", joined)
        self.assertIn("tủ bếp", joined)
        self.assertEqual(result["discovery_plan"]["locale_pack_status"], "CURATED")
        self.assertFalse(result["discovery_plan"]["planning_is_execution_proof"])

class V63CanonicalQualificationBoundaryTests(unittest.TestCase):
    def test_candidate_qualification_rejects_missing_production_canonical_proof(self):
        with self.assertRaises(ValueError):
            qualify_candidate_opportunity({
                "candidate": {
                    "candidate_id": "CAN-NO-CANON",
                    "discovered_from_anchor_id": "DA-1",
                    "branch_group": "APPLICATION_GRAPH",
                    "branch": "downstream_manufacturer",
                    "company_name": "Example Co",
                    "product_profile_id": "PVC",
                },
                "candidate_account_id": "C999",
                "commercial_value_grade": "A",
                "commercial_score": 91,
                "commercial_evidence_bound": True,
                "canonical_status": "CONFIRMED",
                "novelty_signals": ["NEW_MARKET_CELL"],
                "anchor_grade": "B+",
                "anchor_score": 84,
            })

class V63WideDiscoveryStrictQualificationRegressionTests(unittest.TestCase):
    def test_research_active_d4_candidate_still_cannot_create_opportunity_without_canonical_proof(self):
        from unified_runtime.candidate_research_gate import assess_candidate_researchability
        research = assess_candidate_researchability({
            "candidate_id": "CAN-WIDE-STRICT",
            "company_name": "Wide Discovery Co",
            "product_profile_id": "PVC",
            "signal_tier": "D4",
            "eiv": 0.88,
            "canonical_status": "UNRESOLVED",
            "product_or_application_signal": True,
        })
        self.assertEqual(research["research_state"], "RESEARCH_ACTIVE")
        with self.assertRaises(ValueError):
            qualify_candidate_opportunity({
                "candidate": {
                    "candidate_id": "CAN-WIDE-STRICT",
                    "discovered_from_anchor_id": "DA-1",
                    "branch_group": "APPLICATION_GRAPH",
                    "branch": "downstream_manufacturer",
                    "company_name": "Wide Discovery Co",
                    "product_profile_id": "PVC",
                },
                "commercial_value_grade": "A",
                "commercial_score": 92,
                "commercial_evidence_bound": True,
                "novelty_signals": ["NEW_MARKET_CELL"],
                "anchor_grade": "B+",
                "anchor_score": 84,
            })
