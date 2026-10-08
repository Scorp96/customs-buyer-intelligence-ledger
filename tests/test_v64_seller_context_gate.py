from __future__ import annotations

import unittest

from unified_runtime.demand_expansion import V63DemandExpansionMixin


class _CapabilityHarness(V63DemandExpansionMixin):
    pass


class SellerContextFailClosedTests(unittest.TestCase):
    def test_omitted_capability_profile_never_defaults_to_legacy_pvc(self):
        runtime = _CapabilityHarness()
        result = runtime.get_capability_profile({})
        self.assertEqual(result["status"], "UNCONFIGURED")
        self.assertIsNone(result["product_profile_id"])
        self.assertEqual(result["reason"], "EXPLICIT_SELLER_PRODUCT_PROFILE_REQUIRED")

    def test_omitted_fit_profile_never_defaults_to_legacy_pvc(self):
        runtime = _CapabilityHarness()
        result = runtime.evaluate_capability_fit({"demand": {"product_variant": "CELUKA"}})
        self.assertEqual(result["status"], "UNCONFIGURED")
        self.assertIsNone(result["capability_fit"])
        self.assertEqual(result["reason"], "EXPLICIT_SELLER_PRODUCT_PROFILE_REQUIRED")

    def test_unconfigured_machine_profile_does_not_become_supported(self):
        runtime = _CapabilityHarness()
        result = runtime.evaluate_capability_fit({
            "product_profile_id": "SOAP_MACHINERY",
            "demand": {"machine_type": "SOAP_PLODDER"}
        })
        self.assertEqual(result["status"], "UNCONFIGURED")
        self.assertIsNone(result["capability_fit"])
        self.assertEqual(result["reason"], "CAPABILITY_PROFILE_NOT_BOUND")

    def test_historical_pvc_capability_remains_accessible_if_explicitly_selected(self):
        runtime = _CapabilityHarness()
        runtime._v63_capability_profiles = {"PVC": {"capability_profile_id": "XH-LEGACY-PVC", "product_profile_id": "PVC"}}
        result = runtime.get_capability_profile({"product_profile_id": "PVC"})
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["capability_profile"]["capability_profile_id"], "XH-LEGACY-PVC")


if __name__ == "__main__":
    unittest.main()
