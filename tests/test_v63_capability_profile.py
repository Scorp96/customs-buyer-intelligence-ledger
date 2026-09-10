import unittest

from unified_runtime.capability_profile import (
    build_capability_profile,
    evaluate_capability_fit,
)


class V63CapabilityProfileTests(unittest.TestCase):
    def test_capability_profile_separates_supported_from_unverified_claims(self):
        profile = build_capability_profile({
            "capability_profile_id": "XH-PVC-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["FREE_FOAM", "CELUKA", "CO_EXTRUDED"],
            "supported_thickness_mm": [1, 30],
            "supported_sizes_mm": [[1220, 2440]],
            "verified_claims": ["WATER_RESISTANT"],
            "unverified_claims": ["FIRE_RATING"],
        })
        self.assertIn("CELUKA", profile["supported_variants"])
        self.assertNotIn("FIRE_RATING", profile["verified_claims"])

    def test_matching_variant_and_range_produces_supported_fit(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["CELUKA"],
            "supported_thickness_mm": [3, 30],
            "supported_sizes_mm": [[1220, 2440]],
            "verified_claims": [],
            "unverified_claims": [],
        })
        result = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "thickness_mm": 18,
            "size_mm": [1220, 2440],
        })
        self.assertEqual(result["capability_fit"], "SUPPORTED")

    def test_unsupported_variant_fails_closed(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["CELUKA"],
            "supported_thickness_mm": [3, 30],
            "supported_sizes_mm": [[1220, 2440]],
            "verified_claims": [],
            "unverified_claims": [],
        })
        result = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "HONEYCOMB_BOARD",
        })
        self.assertEqual(result["capability_fit"], "UNSUPPORTED")

    def test_unverified_certification_never_counts_as_supported_claim(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["CELUKA"],
            "supported_thickness_mm": [3, 30],
            "supported_sizes_mm": [[1220, 2440]],
            "verified_claims": [],
            "unverified_claims": ["UL94_V0"],
        })
        result = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "required_claims": ["UL94_V0"],
        })
        self.assertEqual(result["capability_fit"], "NEEDS_VERIFICATION")
        self.assertEqual(result["missing_verified_claims"], ["UL94_V0"])


if __name__ == "__main__":
    unittest.main()

class V63VariantCapabilityTests(unittest.TestCase):
    def test_variant_overrides_do_not_cross_contaminate_density_ranges(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["FREE_FOAM", "CELUKA", "CO_EXTRUDED"],
            "variant_capabilities": {
                "FREE_FOAM": {"density_g_cm3": [0.35, 0.45]},
                "CELUKA": {"density_g_cm3": [0.40, 0.65]},
                "CO_EXTRUDED": {"density_g_cm3": [0.45, 0.60]},
            },
        })
        free = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "FREE_FOAM",
            "density_g_cm3": 0.60,
        })
        celuka = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "CELUKA",
            "density_g_cm3": 0.60,
        })
        self.assertEqual(free["capability_fit"], "UNSUPPORTED")
        self.assertIn("DENSITY_OUT_OF_RANGE", free["reasons"])
        self.assertEqual(celuka["capability_fit"], "SUPPORTED")

    def test_variant_capability_can_bind_surface_lamination_color_and_machining(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["CO_EXTRUDED"],
            "variant_capabilities": {
                "CO_EXTRUDED": {
                    "surface_options": ["HIGH_GLOSS", "MATTE"],
                    "lamination_options": ["PVC_FILM", "PET_FILM"],
                    "color_options": ["WHITE", "BLACK", "CUSTOM_BY_CONFIRMATION"],
                    "machining_options": ["CUT", "CNC", "WELD", "BEND"],
                }
            },
        })
        result = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "CO_EXTRUDED",
            "surface": "HIGH_GLOSS",
            "lamination": "PET_FILM",
            "color": "BLACK",
            "machining": ["CNC", "WELD"],
        })
        self.assertEqual(result["capability_fit"], "SUPPORTED")

    def test_demanded_parameter_without_verified_capability_is_needs_verification(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-WPC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "WPC",
            "supported_variants": ["DECKING"],
            "variant_capabilities": {"DECKING": {"capability_status": "USER_CONFIRMED_SPECS_PENDING"}},
        })
        result = evaluate_capability_fit(capability, {
            "product_profile_id": "WPC",
            "product_variant": "DECKING",
            "thickness_mm": 25,
        })
        self.assertEqual(result["capability_fit"], "NEEDS_VERIFICATION")
        self.assertIn("THICKNESS_NOT_VERIFIED", result["reasons"])

    def test_profile_preserves_private_source_provenance_without_promoting_certification(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["CELUKA"],
            "evidence_sources": [{
                "source_ref": "library:file-example",
                "source_type": "CONTROLLED_INTERNAL_PRODUCT_MATERIAL",
                "scope": "CELUKA_DENSITY_AND_APPLICATION",
            }],
            "verified_claims": [],
            "unverified_claims": ["ISO_9001", "CE", "SGS", "ROHS", "REACH"],
            "variant_capabilities": {"CELUKA": {"density_g_cm3": [0.40, 0.65]}},
        })
        self.assertEqual(len(capability["evidence_sources"]), 1)
        self.assertEqual(capability["verified_claims"], [])
        self.assertIn("CE", capability["unverified_claims"])



class V63DiscreteCapabilityTests(unittest.TestCase):
    def test_discrete_thickness_values_do_not_imply_unlisted_intermediate_values(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-ACRYLIC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "ACRYLIC_PMMA",
            "supported_variants": ["GENERAL_SHEET"],
            "variant_capabilities": {
                "GENERAL_SHEET": {"supported_thickness_values_mm": [2.8, 4.7]}
            },
        })
        listed = evaluate_capability_fit(capability, {
            "product_profile_id": "ACRYLIC_PMMA",
            "product_variant": "GENERAL_SHEET",
            "thickness_mm": 2.8,
        })
        intermediate = evaluate_capability_fit(capability, {
            "product_profile_id": "ACRYLIC_PMMA",
            "product_variant": "GENERAL_SHEET",
            "thickness_mm": 3.5,
        })
        self.assertEqual(listed["capability_fit"], "SUPPORTED")
        self.assertEqual(intermediate["capability_fit"], "NEEDS_VERIFICATION")
        self.assertIn("THICKNESS_NOT_LISTED", intermediate["reasons"])

class V63SpecCombinationTests(unittest.TestCase):
    def test_verified_spec_matrix_blocks_unproven_color_thickness_combinations(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-ACRYLIC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "ACRYLIC_PMMA",
            "supported_variants": ["GENERAL_SHEET"],
            "variant_capabilities": {
                "GENERAL_SHEET": {
                    "supported_thickness_values_mm": [2.8, 2.9, 4.6, 4.7],
                    "supported_sizes_mm": [[2050, 3050]],
                    "color_options": ["TRANSPARENT", "MILKY_WHITE", "COLORED"],
                    "verified_spec_combinations": [
                        {"thickness_mm": 2.8, "size_mm": [2050, 3050], "color": "TRANSPARENT"},
                        {"thickness_mm": 4.7, "size_mm": [2050, 3050], "color": "TRANSPARENT"},
                        {"thickness_mm": 2.9, "size_mm": [2050, 3050], "color": "MILKY_WHITE"},
                        {"thickness_mm": 4.6, "size_mm": [2050, 3050], "color": "MILKY_WHITE"},
                        {"thickness_mm": 2.9, "size_mm": [2050, 3050], "color": "COLORED"},
                        {"thickness_mm": 4.6, "size_mm": [2050, 3050], "color": "COLORED"},
                    ],
                }
            },
        })
        verified = evaluate_capability_fit(capability, {
            "product_profile_id": "ACRYLIC_PMMA",
            "product_variant": "GENERAL_SHEET",
            "thickness_mm": 2.8,
            "size_mm": [2050, 3050],
            "color": "TRANSPARENT",
        })
        unproven = evaluate_capability_fit(capability, {
            "product_profile_id": "ACRYLIC_PMMA",
            "product_variant": "GENERAL_SHEET",
            "thickness_mm": 2.9,
            "size_mm": [2050, 3050],
            "color": "TRANSPARENT",
        })
        self.assertEqual(verified["capability_fit"], "SUPPORTED")
        self.assertEqual(unproven["capability_fit"], "NEEDS_VERIFICATION")
        self.assertIn("SPEC_COMBINATION_NOT_VERIFIED", unproven["reasons"])

class V63ProductionLineAuditTests(unittest.TestCase):
    def test_variant_capability_preserves_production_line_and_structure_without_inventing_specs(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["HONEYCOMB_BOARD"],
            "variant_capabilities": {
                "HONEYCOMB_BOARD": {
                    "production_line": "USER_CONFIRMED_AVAILABLE",
                    "supported_structure": "PVC_HONEYCOMB_BOARD_SPECS_PENDING",
                    "capability_status": "USER_CONFIRMED_SPECS_PENDING",
                }
            },
        })
        item = capability["variant_capabilities"]["HONEYCOMB_BOARD"]
        self.assertEqual(item["production_line"], "USER_CONFIRMED_AVAILABLE")
        self.assertEqual(item["supported_structure"], "PVC_HONEYCOMB_BOARD_SPECS_PENDING")
        self.assertIsNone(item["supported_thickness_mm"])

class V63VariantInheritanceSafetyTests(unittest.TestCase):
    def test_specs_pending_variant_can_disable_family_spec_inheritance(self):
        capability = build_capability_profile({
            "capability_profile_id": "XH-PVC-PRIVATE-1",
            "version": "1",
            "product_profile_id": "PVC",
            "supported_variants": ["HONEYCOMB_BOARD"],
            "supported_thickness_mm": [1, 30],
            "supported_sizes_mm": [[1220, 2440]],
            "variant_capabilities": {
                "HONEYCOMB_BOARD": {
                    "inherit_family_specs": False,
                    "production_line": "USER_CONFIRMED_AVAILABLE",
                    "supported_structure": "PVC_HONEYCOMB_BOARD_SPECS_PENDING",
                    "capability_status": "USER_CONFIRMED_SPECS_PENDING",
                }
            },
        })
        result = evaluate_capability_fit(capability, {
            "product_profile_id": "PVC",
            "product_variant": "HONEYCOMB_BOARD",
            "thickness_mm": 18,
            "size_mm": [1220, 2440],
        })
        self.assertEqual(result["capability_fit"], "NEEDS_VERIFICATION")
        self.assertIn("THICKNESS_NOT_VERIFIED", result["reasons"])
        self.assertIn("SIZE_NOT_VERIFIED", result["reasons"])
