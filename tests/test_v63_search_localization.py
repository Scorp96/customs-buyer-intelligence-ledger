import unittest


class V63SearchLocalizationTests(unittest.TestCase):
    def test_vietnam_pvc_terms_include_local_product_and_interior_vocabulary(self):
        from unified_runtime.search_localization import get_localized_search_terms
        result = get_localized_search_terms(
            locale="vi-VN",
            product_profile_id="PVC",
            applications=["CABINETRY"],
            buyer_archetypes=["CABINET_MANUFACTURER"],
        )
        joined = "\n".join(result["terms"]).casefold()
        self.assertIn("tấm pvc foam", joined)
        self.assertIn("tủ bếp", joined)
        self.assertTrue(result["planning_only"])
        self.assertIsNone(result["evidence_strength"])

    def test_mexico_pvc_terms_include_local_signage_vocabulary(self):
        from unified_runtime.search_localization import get_localized_search_terms
        result = get_localized_search_terms(
            locale="es-MX",
            product_profile_id="PVC",
            applications=["SIGNAGE"],
            buyer_archetypes=["SIGN_MAKER"],
        )
        joined = "\n".join(result["terms"]).casefold()
        self.assertIn("pvc espumado", joined)
        self.assertTrue("señalización" in joined or "letreros" in joined)

    def test_brazil_pvc_terms_include_visual_communication_vocabulary(self):
        from unified_runtime.search_localization import get_localized_search_terms
        result = get_localized_search_terms(
            locale="pt-BR",
            product_profile_id="PVC",
            applications=["SIGNAGE"],
            buyer_archetypes=["SIGN_MATERIAL_DISTRIBUTOR"],
        )
        joined = "\n".join(result["terms"]).casefold()
        self.assertIn("pvc expandido", joined)
        self.assertIn("comunicação visual", joined)

    def test_unknown_locale_falls_back_without_fabricating_local_terms(self):
        from unified_runtime.search_localization import get_localized_search_terms
        result = get_localized_search_terms(
            locale="zz-ZZ",
            product_profile_id="PVC",
            applications=["SIGNAGE"],
            buyer_archetypes=["SIGN_MAKER"],
        )
        self.assertEqual(result["status"], "NO_CURATED_LOCALE_PACK")
        self.assertEqual(result["terms"], [])
        self.assertFalse(result["source_coverage_complete"])

    def test_query_generator_can_inject_curated_locale_terms_automatically(self):
        from unified_runtime.expansion_planner import generate_discovery_queries
        result = generate_discovery_queries({
            "product_profile_id": "PVC",
            "product_variant": "FREE_FOAM",
            "geography": "Mexico",
            "locale": "es-MX",
            "limit": 100,
        })
        joined = "\n".join(row["query"] for row in result["queries"]).casefold()
        self.assertIn("pvc espumado", joined)
        self.assertEqual(result["locale_pack_status"], "CURATED")
        self.assertFalse(result["planning_is_execution_proof"])

class V63VariantBeforeLocaleExpansionTests(unittest.TestCase):
    def test_variant_mapping_precedes_locale_term_expansion(self):
        from unified_runtime.expansion_planner import generate_discovery_queries
        result = generate_discovery_queries({
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "geography": "Vietnam-HCMC",
            "locale": "vi-VN",
            "limit": 200,
        })
        joined = "\n".join(row["query"] for row in result["queries"]).casefold()
        self.assertIn("tủ bếp", joined)
        self.assertIn("cabinet manufacturer", joined)
