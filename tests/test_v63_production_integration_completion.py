import copy
import unittest

from unified_runtime.demand_expansion import V63DemandExpansionMixin
from unified_runtime.recovery_semantics_v63 import snapshot_sha256


PVC_SHA = "17b7c762e04966088f700da8ce75670d519f1d2930d3d8f2e0b72d048b012eeb"


def create_event(opportunity_id="OPP-C1-PVC-PRIMARY", account_id="C1", investigation_id="INV-1"):
    snapshot = {
        "status": "CREATED",
        "opportunity_id": opportunity_id,
        "account_id": account_id,
        "product_profile_id": "PVC",
        "product_profile_version": "1",
        "product_profile_sha256": PVC_SHA,
        "stage": "OPPORTUNITY_CREATED",
    }
    return {
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "investigation_id": investigation_id,
        "correlation_id": "MUTCORR-CREATE-1",
        "request_sha256": "a" * 64,
        "result_snapshot": snapshot,
        "result_snapshot_sha256": snapshot_sha256(snapshot),
        "raw_idempotency_key_persisted": False,
    }


def promotion_event(opportunity_id="OPP-C1-PVC-PRIMARY", investigation_id="INV-1"):
    return {
        "event_type": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
        "investigation_id": investigation_id,
        "correlation_id": "MUTCORR-PROMOTE-1",
        "request_sha256": "b" * 64,
        "opportunity_id": opportunity_id,
        "anchor_id": "ANCHOR-" + opportunity_id,
        "promotion_reason": "UPGRADE_TARGET",
        "stage": "PROMOTED_ANCHOR",
        "anchor_eligibility_snapshot": {"anchor_eligible": True},
        "cycle_dedup_snapshot": {"cycle_dedup_complete": True},
        "raw_idempotency_key_persisted": False,
    }


class FakeBase:
    def __init__(self):
        self.events = {
            "INV-1": [create_event()],
            "INV-2": [create_event("OPP-C2-PVC-PRIMARY", "C2", "INV-2")],
        }
        self.derived_views = {}
        self.evidence = {
            "E-CUSTOMS-1": {"investigation_id": "INV-1", "account_id": "C1", "source_type": "CUSTOMS", "product_profile_id": "PVC"},
            "E-WEB-1": {"investigation_id": "INV-1", "account_id": "C1", "source_type": "PUBLIC_WEB", "product_profile_id": "PVC"},
            "E-WPC-1": {"investigation_id": "INV-1", "account_id": "C1", "source_type": "CUSTOMS", "product_profile_id": "WPC"},
            "E-OTHER-1": {"investigation_id": "INV-2", "account_id": "C2", "source_type": "CUSTOMS", "product_profile_id": "PVC"},
        }

    def get_runtime_contract(self, arguments=None):
        return {"runtime_version": "6.2-test", "research_orchestration_v6_2": {"status": "READY"}}

    def _read_v63_durable_events(self, investigation_id):
        return copy.deepcopy(self.events.get(investigation_id, []))

    def _query_v63_opportunity_events(self, filters):
        rows = []
        for events in self.events.values():
            rows.extend(copy.deepcopy(events))
        return rows

    def _validate_v63_evidence_ownership(self, investigation_id, account_id, evidence_ids):
        mismatches = []
        for evidence_id in evidence_ids:
            row = self.evidence.get(evidence_id)
            if not row or row["investigation_id"] != investigation_id or row["account_id"] != account_id:
                mismatches.append(evidence_id)
        return {"valid": not mismatches, "mismatches": mismatches}

    def _validate_v63_evidence_provenance(self, investigation_id, evidence_ids, required_source_type):
        mismatches = []
        for evidence_id in evidence_ids:
            row = self.evidence.get(evidence_id)
            if not row or row["investigation_id"] != investigation_id or row["source_type"] != required_source_type:
                mismatches.append(evidence_id)
        return {"valid": not mismatches, "mismatches": mismatches}

    def _validate_v63_opportunity_evidence_binding(self, investigation_id, opportunity, evidence_ids):
        expected = str(opportunity.get("product_profile_id") or "").upper()
        mismatches = []
        for evidence_id in evidence_ids:
            row = self.evidence.get(evidence_id)
            if not row or row["investigation_id"] != investigation_id or str(row.get("product_profile_id") or "").upper() != expected:
                mismatches.append(evidence_id)
        return {"valid": not mismatches, "mismatches": mismatches}

    def _derive_v63_opportunity_runtime_view(self, investigation_id, opportunity):
        return copy.deepcopy(self.derived_views.get(opportunity.get("opportunity_id"), {}))

    def _load_v63_capability_bundle(self):
        return {
            "schema": "cbi.private-seller-capability.v1",
            "public_git_allowed": False,
            "profiles": {
                "PVC": {
                    "capability_profile_id": "CAP-PVC-TEST",
                    "version": "1",
                    "product_profile_id": "PVC",
                    "supported_variants": ["CELUKA"],
                    "variant_capabilities": {
                        "CELUKA": {
                            "inherit_family_specs": False,
                            "supported_thickness_values_mm": [18],
                            "supported_sizes_mm": [[1220, 2440]],
                            "density_g_cm3": [0.40, 0.65],
                        }
                    },
                }
            },
        }


class Runtime(V63DemandExpansionMixin, FakeBase):
    pass


class V63ProductionIntegrationCompletionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_created_opportunity_reconstructs_from_durable_event(self):
        result = self.runtime.get_product_opportunities({"investigation_id": "INV-1"})
        self.assertEqual(result["projected_opportunity_count"], 1)
        row = result["opportunities"][0]
        self.assertEqual(row["opportunity_id"], "OPP-C1-PVC-PRIMARY")
        self.assertEqual(row["product_profile_id"], "PVC")
        self.assertEqual(row["lifecycle_stage"], "OPPORTUNITY_CREATED")

    def test_anchor_promotion_updates_projected_stage(self):
        self.runtime.events["INV-1"].append(promotion_event())
        row = self.runtime.get_product_opportunities({"investigation_id": "INV-1"})["opportunities"][0]
        self.assertEqual(row["lifecycle_stage"], "PROMOTED_ANCHOR")
        self.assertEqual(row["anchor_id"], "ANCHOR-OPP-C1-PVC-PRIMARY")

    def test_portfolio_metrics_loads_durable_opportunity_by_investigation(self):
        result = self.runtime.get_portfolio_metrics({"investigation_id": "INV-1"})
        self.assertEqual(result["unique_account_count"], 1)
        self.assertEqual(result["product_opportunity_count"], 1)

    def test_global_portfolio_metrics_queries_across_investigations(self):
        result = self.runtime.get_portfolio_metrics({"product_profile_id": "PVC"})
        self.assertEqual(result["unique_account_count"], 2)
        self.assertEqual(result["product_opportunity_count"], 2)

    def test_global_opportunity_query_requires_investigation_provenance(self):
        broken = create_event("OPP-C3-PVC-PRIMARY", "C3", "INV-3")
        broken.pop("investigation_id")
        self.runtime.events["INV-3"] = [broken]
        with self.assertRaisesRegex(RuntimeError, "V63_GLOBAL_OPPORTUNITY_EVENT_MISSING_INVESTIGATION_ID"):
            self.runtime.get_product_opportunities({"product_profile_id": "PVC"})

    def test_global_product_opportunity_query_can_filter_account(self):
        result = self.runtime.get_product_opportunities({"account_id": "C2"})
        self.assertEqual(result["projected_opportunity_count"], 1)
        self.assertEqual(result["opportunities"][0]["opportunity_id"], "OPP-C2-PVC-PRIMARY")
        self.assertEqual(result["projection_scope"], "VISIBLE_PORTFOLIO_QUERY")

    def test_contact_plan_loads_persisted_opportunity_by_id(self):
        result = self.runtime.plan_contact_exhaustion({
            "investigation_id": "INV-1",
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "current_routes": {},
        })
        self.assertEqual(result["product_profile_id"], "PVC")

    def test_top_level_account_context_must_match_durable_opportunity(self):
        with self.assertRaisesRegex(ValueError, "OPPORTUNITY_CONTEXT_IDENTITY_CONFLICT:account_id"):
            self.runtime.plan_contact_exhaustion({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
                "account_id": "C2",
                "current_routes": {},
            })

    def test_top_level_product_profile_context_must_match_durable_opportunity(self):
        with self.assertRaisesRegex(ValueError, "OPPORTUNITY_CONTEXT_IDENTITY_CONFLICT:product_profile_id"):
            self.runtime.plan_contact_exhaustion({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
                "product_profile_id": "WPC",
                "current_routes": {},
            })

    def test_nonexistent_opportunity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "OPPORTUNITY_NOT_FOUND"):
            self.runtime.evaluate_product_opportunity({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-NOT-REAL",
                "assessment": {
                    "commercial_value_grade": "A",
                    "commercial_value_score": 90,
                    "commercial_evidence_ids": ["E-CUSTOMS-1"],
                },
            })

    def test_same_account_wrong_product_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "EVIDENCE_OPPORTUNITY_BINDING_MISMATCH"):
            self.runtime.evaluate_product_opportunity({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
                "assessment": {
                    "commercial_value_grade": "A",
                    "commercial_value_score": 90,
                    "commercial_evidence_ids": ["E-WPC-1"],
                },
            })

    def test_cross_owner_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "EVIDENCE_OWNER_MISMATCH"):
            self.runtime.evaluate_product_opportunity({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
                "assessment": {
                    "commercial_value_grade": "A",
                    "commercial_value_score": 90,
                    "commercial_evidence_ids": ["E-OTHER-1"],
                },
            })

    def test_customs_preview_rejects_non_customs_evidence(self):
        with self.assertRaisesRegex(ValueError, "CUSTOMS_EVIDENCE_PROVENANCE_MISMATCH"):
            self.runtime.preview_customs_seed_expansion({
                "investigation_id": "INV-1",
                "account_id": "C1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
                "source_evidence_ids": ["E-WEB-1"],
                "product_profile_id": "PVC",
                "product_variant": "CELUKA",
                "geography": "Vietnam-HCMC",
            })

    def test_customs_preview_proves_customs_before_procurement_true(self):
        result = self.runtime.preview_customs_seed_expansion({
            "investigation_id": "INV-1",
            "account_id": "C1",
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "source_evidence_ids": ["E-CUSTOMS-1"],
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "geography": "Vietnam-HCMC",
        })
        self.assertTrue(result["demand_anchor"]["procurement_proven"])
        self.assertTrue(result["demand_anchor"]["direct_procurement_provenance_verified"])

    def test_direct_demand_anchor_rejects_cross_owner_evidence(self):
        with self.assertRaisesRegex(ValueError, "EVIDENCE_OWNER_MISMATCH"):
            self.runtime.derive_demand_anchor({
                "investigation_id": "INV-1",
                "account_id": "C1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
                "source_type": "CUSTOMS",
                "source_evidence_ids": ["E-OTHER-1"],
                "product_profile_id": "PVC",
                "geography": "Vietnam-HCMC",
            })

    def test_derived_commercial_state_requires_product_bound_evidence(self):
        self.runtime.derived_views["OPP-C1-PVC-PRIMARY"] = {
            "commercial_value_grade": "A",
            "commercial_value_score": 90,
            "lifecycle_target": "QUALIFIED_TARGET",
        }
        with self.assertRaisesRegex(ValueError, "V63_DERIVED_VIEW_COMMERCIAL_EVIDENCE_REQUIRED"):
            self.runtime.get_product_opportunities({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
            })

    def test_derived_commercial_state_rejects_same_account_wrong_product_evidence(self):
        self.runtime.derived_views["OPP-C1-PVC-PRIMARY"] = {
            "commercial_value_grade": "A",
            "commercial_value_score": 90,
            "commercial_evidence_ids": ["E-WPC-1"],
            "lifecycle_target": "QUALIFIED_TARGET",
        }
        with self.assertRaisesRegex(ValueError, "EVIDENCE_OPPORTUNITY_BINDING_MISMATCH"):
            self.runtime.get_product_opportunities({
                "investigation_id": "INV-1",
                "opportunity_id": "OPP-C1-PVC-PRIMARY",
            })

    def test_persisted_opportunity_can_flow_to_sales_readiness_through_derived_state_and_capability(self):
        self.runtime.derived_views["OPP-C1-PVC-PRIMARY"] = {
            "commercial_value_grade": "A",
            "commercial_value_score": 90,
            "commercial_evidence_ids": ["E-CUSTOMS-1"],
            "research_confidence": 80,
            "lifecycle_target": "QUALIFIED_TARGET",
            "outreach_readiness": "COMPANY_ROUTE_READY",
        }
        result = self.runtime.evaluate_sales_readiness({
            "investigation_id": "INV-1",
            "opportunity_id": "OPP-C1-PVC-PRIMARY",
            "selected_route": {
                "route_id": "R1",
                "channel": "EMAIL",
                "owner_scope": "COMPANY",
                "verified": True,
                "route_eligible": True,
                "freshness": "CURRENT",
            },
            "local_context": {
                "now_utc": "2026-09-03T03:00:00+00:00",
                "timezone_name": "Asia/Ho_Chi_Minh",
                "timezone_confidence": "VERIFIED",
                "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
                "holiday_calendar_status": "VERIFIED",
                "holiday_dates_local": [],
                "market_locale": "vi-VN",
                "official_site_languages": ["vi"],
            },
            "product_demand": {
                "product_profile_id": "PVC",
                "product_variant": "CELUKA",
                "thickness_mm": 18,
                "size_mm": [1220, 2440],
                "density_g_cm3": 0.55,
            },
        })
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["sales_readiness"]["sales_readiness_state"], "OUTREACH_EXECUTION_READY")
        self.assertEqual(result["sales_readiness"]["commercial_value_grade"], "A")

    def test_private_capability_loader_survives_fresh_runtime(self):
        first = Runtime().get_capability_profile({"product_profile_id": "PVC"})
        second = Runtime().get_capability_profile({"product_profile_id": "PVC"})
        self.assertEqual(first["status"], "READY")
        self.assertEqual(second["status"], "READY")
        self.assertEqual(first["capability_profile"]["capability_profile_id"], "CAP-PVC-TEST")

    def test_runtime_contract_reports_read_model_binding_state(self):
        result = self.runtime.get_runtime_contract({})["demand_expansion_v6_3"]
        self.assertEqual(result["runtime_read_model_binding_status"], "BOUND")
        self.assertTrue(result["runtime_read_model_bindings_complete"])


if __name__ == "__main__":
    unittest.main()
