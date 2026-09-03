import unittest

from unified_runtime.capability_profile import build_capability_profile
from unified_runtime.sales_readiness import evaluate_sales_readiness


def pvc_capability(*, density=(0.40, 0.65)):
    return build_capability_profile({
        "capability_profile_id": "TEST-PVC-CAP",
        "version": "1",
        "product_profile_id": "PVC",
        "supported_variants": ["CELUKA"],
        "variant_capabilities": {
            "CELUKA": {
                "inherit_family_specs": False,
                "capability_status": "VERIFIED_FOR_TEST",
                "production_line": "PVC_CELUKA_LINE",
                "supported_structure": "PVC_CELUKA",
                "supported_thickness_values_mm": [18],
                "supported_sizes_mm": [[1220, 2440]],
                "density_g_cm3": list(density),
                "machining_options": ["CNC", "CUT", "DRILL"],
            }
        },
    })


def base_payload():
    return {
        "opportunity": {
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "commercial_value_grade": "A",
            "commercial_score": 92,
            "lifecycle_stage": "QUALIFIED_TARGET",
        },
        "selected_route": {
            "route_id": "R-C500-EMAIL",
            "channel": "EMAIL",
            "verified": True,
            "route_eligible": True,
            "guessed": False,
            "freshness": "CURRENT",
            "owner_scope": "COMPANY",
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
            "machining": ["CNC"],
        },
    }


class V63SalesReadinessTests(unittest.TestCase):
    def test_supported_capability_current_route_and_local_window_are_outreach_ready(self):
        result = evaluate_sales_readiness(base_payload(), pvc_capability())
        self.assertEqual(result["sales_readiness_state"], "OUTREACH_EXECUTION_READY")
        self.assertTrue(result["commercial_outreach_ready"])
        self.assertTrue(result["technical_offer_ready"])
        self.assertEqual(result["outreach_language"], "vi")
        self.assertEqual(result["channel"], "EMAIL")
        self.assertFalse(result["sends_message"])
        self.assertFalse(result["server_side_draft_created"])

    def test_unverified_exact_spec_allows_discovery_outreach_but_blocks_technical_offer(self):
        payload = base_payload()
        payload["product_demand"]["density_g_cm3"] = 0.70
        capability = pvc_capability(density=(0.40, 0.65))
        result = evaluate_sales_readiness(payload, capability)
        self.assertEqual(result["sales_readiness_state"], "CAPABILITY_MISMATCH")
        self.assertFalse(result["commercial_outreach_ready"])
        self.assertFalse(result["technical_offer_ready"])

        payload = base_payload()
        payload["product_demand"]["surface"] = "HIGH_GLOSS"
        result = evaluate_sales_readiness(payload, pvc_capability())
        self.assertEqual(result["sales_readiness_state"], "OUTREACH_READY_TECH_CONFIRMATION_REQUIRED")
        self.assertTrue(result["commercial_outreach_ready"])
        self.assertFalse(result["technical_offer_ready"])
        self.assertTrue(result["technical_promises_blocked"])

    def test_missing_or_stale_route_requires_contact_research(self):
        payload = base_payload()
        payload["selected_route"]["freshness"] = "STALE"
        result = evaluate_sales_readiness(payload, pvc_capability())
        self.assertEqual(result["sales_readiness_state"], "CONTACT_RESEARCH_REQUIRED")
        self.assertFalse(result["commercial_outreach_ready"])
        self.assertIn("ROUTE_NOT_CURRENT", result["route_reuse"]["blockers"])

    def test_outside_local_window_waits_instead_of_sending(self):
        payload = base_payload()
        payload["local_context"]["now_utc"] = "2026-09-03T20:00:00+00:00"
        result = evaluate_sales_readiness(payload, pvc_capability())
        self.assertEqual(result["sales_readiness_state"], "WAIT_FOR_LOCAL_WINDOW")
        self.assertFalse(result["commercial_outreach_ready"])
        self.assertIsNotNone(result["next_window_local"])

    def test_unresolved_holiday_or_timezone_context_blocks_execution(self):
        payload = base_payload()
        payload["local_context"]["holiday_calendar_status"] = "UNKNOWN"
        result = evaluate_sales_readiness(payload, pvc_capability())
        self.assertEqual(result["sales_readiness_state"], "LOCAL_CONTEXT_RESOLUTION_REQUIRED")
        task_types = {task["task_type"] for task in result["local_context_resolution"]["tasks"]}
        self.assertIn("VERIFY_LOCAL_BUSINESS_HOLIDAY", task_types)
        self.assertFalse(result["commercial_outreach_ready"])

    def test_low_value_opportunity_is_not_prioritized_for_outreach_by_default(self):
        payload = base_payload()
        payload["opportunity"]["commercial_value_grade"] = "C"
        result = evaluate_sales_readiness(payload, pvc_capability())
        self.assertEqual(result["sales_readiness_state"], "LOW_PRIORITY_RESEARCH_ONLY")
        self.assertFalse(result["commercial_outreach_ready"])

    def test_sales_readiness_never_mutates_commercial_grade(self):
        payload = base_payload()
        result = evaluate_sales_readiness(payload, pvc_capability())
        self.assertEqual(result["commercial_value_grade"], "A")
        self.assertFalse(result["commercial_grade_mutated"])


if __name__ == "__main__":
    unittest.main()
