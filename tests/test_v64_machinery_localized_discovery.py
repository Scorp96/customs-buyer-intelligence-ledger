"""Source-observed multilingual machinery discovery (no network or buyer promotion)."""
from __future__ import annotations

import unittest

from unified_runtime.search_localization import get_localized_search_terms
from unified_runtime.expansion_planner import generate_discovery_queries
from unified_runtime.demand_expansion import V63DemandExpansionMixin


_MARKETS = {
    "Indonesia": ("id-ID", "mesin pengisi cairan"),
    "Vietnam": ("vi-VN", "máy nhũ hóa chân không"),
    "Mexico": ("es-MX", "emulsionador al vacío"),
    "Brazil": ("pt-BR", "misturador emulsificador a vácuo"),
}


class MachineryLocalizationTests(unittest.TestCase):
    def test_machine_packs_cover_four_different_local_languages(self):
        for market, (locale, term) in _MARKETS.items():
            with self.subTest(market=market):
                row = get_localized_search_terms(
                    locale=locale,
                    product_profile_id="SOAP_MACHINERY",
                    applications=["COSMETICS_EMULSION"],
                    buyer_archetypes=["COSMETICS_MANUFACTURER"],
                )
                self.assertEqual(row["status"], "CURATED")
                self.assertEqual(row["locale"], locale)
                self.assertIn(term, row["terms"])
                self.assertGreater(len(row["source_hint_urls"]), 0)
                self.assertFalse(row["source_coverage_complete"])
                self.assertTrue(row["planning_only"])
                self.assertIsNone(row["evidence_strength"])

    def test_auto_selection_uses_country_only_for_machinery(self):
        for geography, (locale, _) in _MARKETS.items():
            with self.subTest(geography=geography):
                result = generate_discovery_queries({
                    "product_profile_id": "SOAP_MACHINERY",
                    "product_variant": "VACUUM_EMULSIFIER",
                    "geography": geography,
                    "limit": 8,
                })
                self.assertEqual(result["locale"], locale)
                self.assertTrue(result["locale_auto_selected"])
                self.assertEqual(result["locale_pack_status"], "CURATED")
                self.assertTrue(result["local_and_global_query_budget_balanced"])
                self.assertEqual(result["returned_count"], 8)
                queries = result["queries"]
                self.assertTrue(any(q["basis"] == "LOCAL_TERM_X_GEOGRAPHY" for q in queries))
                self.assertTrue(any(q["basis"] not in {
                    "LOCAL_TERM_X_GEOGRAPHY", "PRODUCT_X_LOCAL_TERM_X_GEOGRAPHY"
                } for q in queries))
                self.assertTrue(all(q["search_execution_performed"] is False for q in queries))

    def test_narrow_budget_keeps_native_and_global_seeds(self):
        r = generate_discovery_queries({
            "product_profile_id": "SOAP_MACHINERY",
            "geography": "Indonesia",
            "limit": 2,
        })
        self.assertEqual(len(r["queries"]), 2)
        self.assertEqual(r["queries"][0]["basis"], "PRODUCT_X_LOCAL_TERM_X_GEOGRAPHY")
        self.assertNotIn(r["queries"][1]["basis"], {
            "LOCAL_TERM_X_GEOGRAPHY", "PRODUCT_X_LOCAL_TERM_X_GEOGRAPHY"
        })
        self.assertTrue(r["truncated"])

    def test_explicit_locale_overrides_geography(self):
        r = generate_discovery_queries({
            "product_profile_id": "SOAP_MACHINERY",
            "geography": "Brazil",
            "locale": "vi-VN",
            "limit": 10,
        })
        self.assertEqual(r["locale"], "vi-VN")
        self.assertFalse(r["locale_auto_selected"])

    def test_unknown_market_remains_unknown_language(self):
        r = generate_discovery_queries({
            "product_profile_id": "SOAP_MACHINERY",
            "geography": "Morocco",
            "limit": 10,
        })
        self.assertIsNone(r["locale"])
        self.assertFalse(r["locale_auto_selected"])
        self.assertEqual(r["locale_pack_status"], "NOT_REQUESTED")

    def test_auto_locale_opt_out_for_specialized_customer_queries(self):
        r = generate_discovery_queries({
            "product_profile_id": "SOAP_MACHINERY",
            "geography": "Indonesia",
            "auto_market_locale": False,
            "limit": 10,
        })
        self.assertIsNone(r["locale"])
        self.assertFalse(r["locale_auto_selected"])

    def test_pvc_wpc_do_not_inherit_machinery_locale_auto_selection(self):
        for profile in ("PVC", "WPC"):
            r = generate_discovery_queries({
                "product_profile_id": profile,
                "geography": "Indonesia",
                "limit": 10,
            })
            self.assertIsNone(r["locale"])
            self.assertFalse(r["locale_auto_selected"])

    def test_invalid_unlisted_profile_fails_closed(self):
        with self.assertRaises(KeyError):
            get_localized_search_terms(
                locale="id-ID", product_profile_id="NOT_A_REAL_PROFILE"
            )

    def test_runtime_plan_propagates_localization_without_execution(self):
        result = V63DemandExpansionMixin().plan_candidate_expansion({
            "product_profile_id": "SOAP_MACHINERY",
            "product_variant": "LIQUID_FILLING_LINE",
            "geography": "Indonesia",
            "query_limit": 24,
            "source_task_limit": 24,
        })
        d = result["discovery_plan"]
        self.assertEqual(d["locale"], "id-ID")
        self.assertTrue(d["locale_auto_selected"])
        self.assertTrue(result["host_execution_required"])
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertTrue(all(
            not x["search_execution_performed"]
            for x in result["source_plan"]["tasks"]
        ))


if __name__ == "__main__":
    unittest.main()
