import unittest


class V63PortfolioMetricsTests(unittest.TestCase):
    def test_metrics_separate_unique_accounts_from_product_opportunities(self):
        from unified_runtime.portfolio_metrics import compute_portfolio_metrics
        result = compute_portfolio_metrics([
            {"account_id": "C1", "opportunity_id": "O1", "commercial_value_grade": "A", "outreach_readiness": "COMPANY_ROUTE_READY", "stage": "QUALIFIED_TARGET"},
            {"account_id": "C1", "opportunity_id": "O2", "commercial_value_grade": "B+", "outreach_readiness": "IDENTITY_ONLY", "stage": "QUALIFIED_TARGET", "state": "CROSS_SELL_HYPOTHESIS"},
            {"account_id": "C2", "opportunity_id": "O3", "commercial_value_grade": "A+", "outreach_readiness": "NAMED_ROUTE_READY", "stage": "PROMOTED_ANCHOR"},
        ])
        self.assertEqual(result["unique_account_count"], 2)
        self.assertEqual(result["product_opportunity_count"], 3)
        self.assertEqual(result["bplus_or_above_opportunity_count"], 3)
        self.assertEqual(result["company_route_ready_opportunity_count"], 2)
        self.assertEqual(result["named_route_ready_opportunity_count"], 1)
        self.assertEqual(result["promoted_anchor_opportunity_count"], 1)
        self.assertEqual(result["cross_sell_hypothesis_count"], 1)

    def test_metrics_do_not_treat_unknown_grade_as_qualified(self):
        from unified_runtime.portfolio_metrics import compute_portfolio_metrics
        result = compute_portfolio_metrics([
            {"account_id": "C1", "opportunity_id": "O1", "commercial_value_grade": "NQ", "outreach_readiness": "IDENTITY_ONLY"},
        ])
        self.assertEqual(result["bplus_or_above_opportunity_count"], 0)
        self.assertEqual(result["sales_ready_qualified_opportunity_count"], 0)
