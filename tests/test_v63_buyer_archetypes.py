import unittest


class V63BuyerArchetypeEngineTests(unittest.TestCase):
    def test_sign_material_distributor_ranks_above_sign_maker_for_channel_scale(self):
        from unified_runtime.buyer_archetypes import rank_buyer_archetypes
        ranked = rank_buyer_archetypes("PVC", ["SIGN_MAKER", "SIGN_MATERIAL_DISTRIBUTOR"])
        self.assertEqual(ranked[0]["archetype_id"], "SIGN_MATERIAL_DISTRIBUTOR")
        self.assertFalse(ranked[0]["archetype_match_proves_procurement"])

    def test_cabinet_manufacturer_ranks_above_interior_fitout_for_repeat_material_consumption(self):
        from unified_runtime.buyer_archetypes import rank_buyer_archetypes
        ranked = rank_buyer_archetypes("PVC", ["INTERIOR_FITOUT_COMPANY", "CABINET_MANUFACTURER"])
        self.assertEqual(ranked[0]["archetype_id"], "CABINET_MANUFACTURER")
        self.assertEqual(ranked[0]["demand_mode"], "PRODUCTION_CONSUMPTION")

    def test_profile_archetype_coverage_has_no_unclassified_ids(self):
        from unified_runtime.buyer_archetypes import get_buyer_archetype
        from unified_runtime.product_profiles import list_product_profiles
        for profile in list_product_profiles():
            for archetype_id in profile.get("buyer_archetypes", []):
                result = get_buyer_archetype(archetype_id)
                self.assertEqual(result["archetype_id"], archetype_id)
                self.assertNotEqual(result["business_role"], "UNCLASSIFIED")

    def test_unknown_archetype_fails_closed(self):
        from unified_runtime.buyer_archetypes import get_buyer_archetype
        with self.assertRaises(ValueError):
            get_buyer_archetype("MAGIC_CUSTOMER")

    def test_archetype_priority_is_discovery_only_not_commercial_grade(self):
        from unified_runtime.buyer_archetypes import get_buyer_archetype
        result = get_buyer_archetype("BUILDING_MATERIAL_DISTRIBUTOR")
        self.assertTrue(result["priority_is_discovery_only"])
        self.assertFalse(result["archetype_match_proves_product_fit"])
        self.assertFalse(result["archetype_match_proves_procurement"])
        self.assertNotIn("commercial_value_grade", result)
