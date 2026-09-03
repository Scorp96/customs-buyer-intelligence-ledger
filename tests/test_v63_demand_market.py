import unittest

from unified_runtime.demand_market import (
    derive_demand_anchor,
    derive_market_cell,
    evaluate_market_acceptance,
)


class V63DemandMarketTests(unittest.TestCase):
    def make_anchor(self, account_id, date, evidence_id, geography="US-MA"):
        return derive_demand_anchor({
            "account_id": account_id,
            "opportunity_id": f"OPP-{account_id}-PVC-PRIMARY",
            "source_type": "CUSTOMS",
            "source_evidence_ids": [evidence_id],
            "shipment_date": date,
            "shipment_weight_kg": 26980,
            "product_profile_id": "PVC",
            "geography": geography,
        })

    def test_single_customs_shipment_creates_m1_only(self):
        anchor = self.make_anchor("C500", "2026-08-02", "E1")
        market = evaluate_market_acceptance([anchor])
        self.assertEqual(market["level"], "M1")

    def test_repeated_same_buyer_can_reach_m2(self):
        signals = [
            self.make_anchor("C500", "2026-08-02", "E1"),
            self.make_anchor("C500", "2026-08-29", "E2"),
        ]
        self.assertEqual(evaluate_market_acceptance(signals)["level"], "M2")

    def test_multiple_canonical_buyers_can_reach_m3(self):
        signals = [
            self.make_anchor("C500", "2026-08-02", "E1"),
            self.make_anchor("C501", "2026-08-15", "E2"),
        ]
        self.assertEqual(evaluate_market_acceptance(signals)["level"], "M3")

    def test_market_cell_key_is_order_independent_for_clusters(self):
        anchor = self.make_anchor("C500", "2026-08-02", "E1")
        a = derive_market_cell(anchor, ["SIGNAGE", "UV_PRINTING"], ["SIGN_MAKER", "DISTRIBUTOR"])
        b = derive_market_cell(anchor, ["UV_PRINTING", "SIGNAGE"], ["DISTRIBUTOR", "SIGN_MAKER"])
        self.assertEqual(a["market_cell_id"], b["market_cell_id"])

    def test_one_shipment_cannot_reach_m2_even_with_duplicate_signal_copy(self):
        anchor = self.make_anchor("C500", "2026-08-02", "E1")
        self.assertEqual(evaluate_market_acceptance([anchor, dict(anchor)])["level"], "M1")

    def test_non_procurement_signal_does_not_create_m1(self):
        signal = {
            "demand_anchor_id": "DA-X",
            "account_id": "C500",
            "source_type": "APPLICATION_PROOF",
            "source_evidence_ids": ["E1"],
            "product_profile_id": "PVC",
            "geography": "US-MA",
            "procurement_proven": False,
        }
        self.assertEqual(evaluate_market_acceptance([signal])["level"], "M0")


if __name__ == "__main__":
    unittest.main()
