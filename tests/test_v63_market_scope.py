import unittest

from unified_runtime.market_scope import derive_market_expansion_scope


class V63MarketScopeTests(unittest.TestCase):
    def test_m1_stays_local_and_nearby(self):
        scope = derive_market_expansion_scope("M1", geography="Vietnam-HCMC")
        self.assertEqual(scope["scope"], "CITY_AND_NEARBY")
        self.assertFalse(scope["country_wide_demand_proven"])
        self.assertTrue(scope["cross_country_requires_separate_market_cell"])

    def test_m2_expands_to_region_not_whole_country_by_fact(self):
        scope = derive_market_expansion_scope("M2", geography="US-MA")
        self.assertEqual(scope["scope"], "METRO_AND_REGION")
        self.assertFalse(scope["country_wide_demand_proven"])

    def test_m3_can_search_country_wide_without_upgrading_evidence_scope(self):
        scope = derive_market_expansion_scope("M3", geography="Vietnam-HCMC")
        self.assertEqual(scope["scope"], "REGION_AND_COUNTRY_DISCOVERY")
        self.assertTrue(scope["country_discovery_allowed"])
        self.assertFalse(scope["country_wide_demand_proven"])
        self.assertEqual(scope["evidence_scope"], "MARKET_CELL_ONLY")

    def test_m4_and_m5_prioritize_country_clusters_and_competitor_networks(self):
        m4 = derive_market_expansion_scope("M4", geography="Mexico-MX")
        m5 = derive_market_expansion_scope("M5", geography="Mexico-MX")
        self.assertEqual(m4["scope"], "COUNTRY_WIDE_PRIORITY_CLUSTERS")
        self.assertEqual(m5["scope"], "COUNTRY_WIDE_DENSE_COMPETITIVE_NETWORK")
        self.assertTrue(m5["competitor_network_priority"])

    def test_cross_country_never_inherits_market_acceptance(self):
        scope = derive_market_expansion_scope("M5", geography="US-MA")
        self.assertFalse(scope["adjacent_country_acceptance_inherited"])
        self.assertTrue(scope["cross_country_requires_separate_market_cell"])

    def test_invalid_market_level_fails_closed(self):
        with self.assertRaises(ValueError):
            derive_market_expansion_scope("M9", geography="US-MA")


if __name__ == "__main__":
    unittest.main()
