import unittest

from unified_runtime.demand_evidence import classify_demand_evidence


class V63DemandEvidenceTests(unittest.TestCase):
    def test_customs_is_d1_direct_procurement(self):
        result = classify_demand_evidence({
            "source_type": "CUSTOMS",
            "evidence_ids": ["E1"],
            "verified": True,
        })
        self.assertEqual(result["tier"], "D1")
        self.assertTrue(result["supports_procurement"])
        self.assertTrue(result["supports_product_involvement"])

    def test_official_stocking_page_is_d2_not_procurement(self):
        result = classify_demand_evidence({
            "source_type": "OFFICIAL_STOCKING_PAGE",
            "evidence_ids": ["E2"],
            "verified": True,
        })
        self.assertEqual(result["tier"], "D2")
        self.assertFalse(result["supports_procurement"])
        self.assertTrue(result["supports_current_commerce"])

    def test_verified_application_page_is_d3_not_buyer_fact(self):
        result = classify_demand_evidence({
            "source_type": "OFFICIAL_APPLICATION_PAGE",
            "evidence_ids": ["E3"],
            "verified": True,
        })
        self.assertEqual(result["tier"], "D3")
        self.assertTrue(result["supports_application_fit"])
        self.assertFalse(result["supports_procurement"])

    def test_similarity_search_is_d4_hypothesis_only(self):
        result = classify_demand_evidence({
            "source_type": "SEARCH_SIMILARITY",
            "evidence_ids": ["E4"],
            "verified": True,
        })
        self.assertEqual(result["tier"], "D4")
        self.assertTrue(result["discovery_only"])
        self.assertFalse(result["supports_procurement"])

    def test_unverified_source_never_becomes_d1_d2_or_d3(self):
        result = classify_demand_evidence({
            "source_type": "CUSTOMS",
            "evidence_ids": ["E1"],
            "verified": False,
        })
        self.assertEqual(result["tier"], "D4")
        self.assertFalse(result["supports_procurement"])
        self.assertEqual(result["boundary"], "UNVERIFIED_DISCOVERY_SIGNAL")

    def test_missing_evidence_ids_cannot_support_positive_commercial_fact(self):
        result = classify_demand_evidence({
            "source_type": "OFFICIAL_STOCKING_PAGE",
            "evidence_ids": [],
            "verified": True,
        })
        self.assertEqual(result["tier"], "D4")
        self.assertFalse(result["supports_current_commerce"])

    def test_unknown_source_fails_closed_to_d4(self):
        result = classify_demand_evidence({
            "source_type": "SOME_UNKNOWN_SOURCE",
            "evidence_ids": ["E5"],
            "verified": True,
        })
        self.assertEqual(result["tier"], "D4")
        self.assertTrue(result["requires_further_verification"])


if __name__ == "__main__":
    unittest.main()
