import unittest

from unified_runtime.crm_projection import project_account_opportunities


class V63CrmProjectionTests(unittest.TestCase):
    def test_multi_product_account_remains_one_crm_account(self):
        result = project_account_opportunities(
            {
                "account_id": "C500",
                "legal_name": "Example Materials LLC",
                "country": "US",
            },
            [
                {
                    "opportunity_id": "OPP-C500-PVC-PRIMARY",
                    "product_profile_id": "PVC",
                    "product_variant": "CELUKA",
                    "applications": ["CABINETRY"],
                    "commercial_value_grade": "A",
                    "relative_class": "SAME_TIER_HIGH",
                    "market_cell_ids": ["MC-1"],
                    "company_route_status": "COMPANY_ROUTE_READY",
                    "named_route_status": "IDENTITY_ONLY",
                    "anchor_status": "ANCHOR_ELIGIBLE",
                },
                {
                    "opportunity_id": "OPP-C500-ACRYLIC_PMMA-PRIMARY",
                    "product_profile_id": "ACRYLIC_PMMA",
                    "applications": ["SIGNAGE"],
                    "commercial_value_grade": "B+",
                    "relative_class": "STRATEGIC_LOWER",
                    "market_cell_ids": ["MC-2"],
                    "company_route_status": "COMPANY_ROUTE_READY",
                    "named_route_status": "IDENTITY_ONLY",
                    "anchor_status": "NOT_ELIGIBLE",
                },
            ],
        )
        self.assertEqual(result["account_row_count"], 1)
        self.assertEqual(result["account"]["account_id"], "C500")
        self.assertEqual(len(result["product_opportunities"]), 2)

    def test_projection_keeps_only_opportunity_summary_fields(self):
        result = project_account_opportunities(
            {"account_id": "C500", "legal_name": "Example Materials LLC"},
            [{
                "opportunity_id": "OPP-C500-PVC-PRIMARY",
                "product_profile_id": "PVC",
                "product_variant": "FREE_FOAM",
                "applications": ["SIGNAGE"],
                "commercial_value_grade": "A+",
                "relative_class": "UPGRADE_TARGET",
                "market_cell_ids": ["MC-1"],
                "company_route_status": "COMPANY_ROUTE_READY",
                "named_route_status": "NAMED_ROUTE_READY",
                "anchor_status": "PROMOTED_ANCHOR",
                "private_raw_evidence": "must-not-leak",
            }],
        )
        projected = result["product_opportunities"][0]
        self.assertNotIn("private_raw_evidence", projected)
        self.assertEqual(projected["product_family"], "PVC")
        self.assertEqual(projected["grade"], "A+")

    def test_opportunity_for_different_account_is_rejected(self):
        with self.assertRaises(ValueError):
            project_account_opportunities(
                {"account_id": "C500", "legal_name": "Example Materials LLC"},
                [{
                    "opportunity_id": "OPP-C999-PVC-PRIMARY",
                    "account_id": "C999",
                    "product_profile_id": "PVC",
                }],
            )

    def test_duplicate_opportunity_ids_are_deduplicated_without_duplicate_customer_rows(self):
        opp = {
            "opportunity_id": "OPP-C500-PVC-PRIMARY",
            "account_id": "C500",
            "product_profile_id": "PVC",
            "commercial_value_grade": "A",
        }
        result = project_account_opportunities(
            {"account_id": "C500", "legal_name": "Example Materials LLC"},
            [opp, dict(opp)],
        )
        self.assertEqual(result["account_row_count"], 1)
        self.assertEqual(len(result["product_opportunities"]), 1)


if __name__ == "__main__":
    unittest.main()
