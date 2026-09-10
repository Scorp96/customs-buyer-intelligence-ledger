import unittest

from unified_runtime.product_profiles import (
    classify_product_alias,
    get_product_profile,
    list_product_profiles,
    portfolio_priority,
    product_profile_sha256,
)


class V63ProductProfileTests(unittest.TestCase):
    def test_pvc_is_primary_and_has_rich_applications(self):
        pvc = get_product_profile("PVC")
        self.assertEqual(pvc["portfolio_priority"], "PRIMARY")
        self.assertIn("PVC_FOAM_BOARD", pvc["subfamilies"])
        self.assertIn("SIGNAGE", pvc["applications"])
        self.assertIn("CABINETRY", pvc["applications"])
        self.assertIn("PARTITION_WET_AREA", pvc["applications"])

    def test_secondary_profiles_exist(self):
        ids = {p["profile_id"] for p in list_product_profiles()}
        self.assertTrue({"PVC", "WPC", "SPC", "ACRYLIC_PMMA"} <= ids)

    def test_profile_hash_is_deterministic(self):
        pvc = get_product_profile("PVC")
        self.assertEqual(
            product_profile_sha256(pvc),
            product_profile_sha256(get_product_profile("PVC")),
        )

    def test_marketing_alias_is_not_technical_identity(self):
        result = classify_product_alias("太空板")
        self.assertEqual(result["classification"], "MARKETING_ALIAS")
        self.assertFalse(result["technical_identity_verified"])

    def test_portfolio_priority_is_scheduler_only_weight(self):
        self.assertEqual(portfolio_priority("PVC"), 1.0)
        self.assertEqual(portfolio_priority("WPC"), 0.75)
        self.assertEqual(portfolio_priority("SPC"), 0.65)
        self.assertEqual(portfolio_priority("ACRYLIC_PMMA"), 0.65)

    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(KeyError):
            get_product_profile("UNKNOWN")


if __name__ == "__main__":
    unittest.main()

class V63ProductApplicationMappingTests(unittest.TestCase):
    def test_celuka_maps_to_cabinet_and_furniture_archetypes(self):
        pvc = get_product_profile("PVC")
        mapping = pvc["variant_application_map"]["CELUKA"]
        self.assertIn("CABINETRY", mapping["applications"])
        self.assertIn("CABINET_MANUFACTURER", mapping["buyer_archetypes"])
        self.assertIn("BATHROOM_VANITY_MANUFACTURER", mapping["buyer_archetypes"])

    def test_free_foam_maps_to_signage_display_archetypes(self):
        pvc = get_product_profile("PVC")
        mapping = pvc["variant_application_map"]["FREE_FOAM"]
        self.assertIn("SIGNAGE", mapping["applications"])
        self.assertIn("SIGN_MAKER", mapping["buyer_archetypes"])
        self.assertIn("DISPLAY_MANUFACTURER", mapping["buyer_archetypes"])

    def test_partition_board_maps_to_wet_area_buyers(self):
        pvc = get_product_profile("PVC")
        mapping = pvc["variant_application_map"]["PARTITION_BOARD"]
        self.assertIn("PARTITION_WET_AREA", mapping["applications"])
        self.assertIn("PARTITION_MANUFACTURER", mapping["buyer_archetypes"])

class V63SecondaryVariantMappingTests(unittest.TestCase):
    def test_wpc_decking_maps_to_real_buyer_archetypes(self):
        wpc = get_product_profile("WPC")
        mapping = wpc["variant_application_map"]["DECKING"]
        self.assertIn("OUTDOOR_DECKING", mapping["applications"])
        self.assertIn("DECKING_DISTRIBUTOR", mapping["buyer_archetypes"])

    def test_spc_flooring_maps_to_flooring_buyers(self):
        spc = get_product_profile("SPC")
        mapping = spc["variant_application_map"]["SPC_FLOORING"]
        self.assertIn("FLOORING", mapping["applications"])
        self.assertIn("FLOORING_IMPORTER", mapping["buyer_archetypes"])

    def test_acrylic_signage_grade_maps_to_signage_buyers(self):
        acrylic = get_product_profile("ACRYLIC_PMMA")
        mapping = acrylic["variant_application_map"]["SIGNAGE_GRADE"]
        self.assertIn("SIGNAGE", mapping["applications"])
        self.assertIn("SIGN_MATERIAL_DISTRIBUTOR", mapping["buyer_archetypes"])

    def test_pvc_finished_systems_have_application_mappings(self):
        pvc = get_product_profile("PVC")
        wall = pvc["variant_application_map"]["PVC_WALL_PANEL"]
        floor = pvc["variant_application_map"]["PVC_FLOORING"]
        self.assertIn("WALL_DECORATION", wall["applications"])
        self.assertIn("FLOORING_DISTRIBUTOR", floor["buyer_archetypes"])

    def test_all_mapping_values_are_declared_on_profile(self):
        for profile in list_product_profiles():
            declared_apps = set(profile.get("applications", []))
            declared_buyers = set(profile.get("buyer_archetypes", []))
            for variant, mapping in (profile.get("variant_application_map") or {}).items():
                with self.subTest(profile=profile["profile_id"], variant=variant):
                    self.assertTrue(set(mapping.get("applications", [])) <= declared_apps)
                    self.assertTrue(set(mapping.get("buyer_archetypes", [])) <= declared_buyers)
