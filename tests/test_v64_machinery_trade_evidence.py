"""Machine-buyer HS / shipment / party separation with synthetic fixtures only."""
from __future__ import annotations

import copy
import unittest

from unified_runtime.machinery_trade_evidence_v64 import assess_machinery_trade_buyer


HS = {"hs6_candidate": "842230", "destination_country": "USA"}
SHIPMENT = {
    "source_type": "CUSTOMS",
    "source_locator": "https://example.test/trade/fixture-001",
    "bill_of_lading": "TEST-BOL-001",
    "shipment_date": "2026-08-18",
    "goods_kind": "COMPLETE_MACHINE",
    "goods_description": "industrial liquid perfume filling and sealing machine",
    "machine_identity_status": "EXACT_MATCH",
    "machine_identity_locator": "https://example.test/trade/fixture-001#goods",
    "buyer_account_id": "TEST-BUYER-001",
}
BUYER = {
    "canonical_account_id": "TEST-BUYER-001",
    "legal_entity_name": "Example Synthetic Buyer",
    "trade_role": "IMPORTER_OF_RECORD",
    "identity_evidence_locator": "https://example.test/register/fixture-001",
}


class MachineryTradeEvidenceTests(unittest.TestCase):
    def _check(self, **overrides):
        return assess_machinery_trade_buyer(
            hs=overrides.get("hs", HS),
            shipment=overrides.get("shipment", SHIPMENT),
            buyer=overrides.get("buyer", BUYER),
            seller_capability=overrides.get("seller_capability", {}),
        )

    def test_hs_six_digit_only_is_discovery_not_import(self):
        r = assess_machinery_trade_buyer(hs=HS)
        self.assertEqual(r["stage"], "DISCOVERY_CANDIDATE")
        self.assertEqual(r["classification_status"], "HS6_CANDIDATE_ONLY")
        self.assertFalse(r["shipment_supported"])
        self.assertFalse(r["hs_only_proves_machine_purchase"])

    def test_importer_of_record_does_not_become_ultimate_buyer(self):
        r = self._check()
        self.assertEqual(r["stage"], "VERIFIED_MACHINE_IMPORTER_OF_RECORD")
        self.assertTrue(r["shipment_supported"])
        self.assertFalse(r["ultimate_buyer_supported"])
        self.assertIsNone(r["commercial_value_grade"])

    def test_unverified_consignee_is_not_ultimate_buyer(self):
        buyer = {**BUYER, "trade_role": "CONSIGNEE"}
        r = self._check(buyer=buyer)
        self.assertEqual(r["stage"], "VERIFIED_MACHINE_CONSIGNEE_NOT_NECESSARILY_BUYER")
        self.assertFalse(r["ultimate_buyer_supported"])

    def test_ultimate_buyer_requires_separate_evidence(self):
        buyer = {**BUYER, "trade_role": "ULTIMATE_BUYER",
                 "ultimate_buyer_evidence_locator": "https://example.test/contracts/synthetic"}
        r = self._check(buyer=buyer)
        self.assertEqual(r["stage"], "VERIFIED_ACTUAL_MACHINE_BUYER")
        self.assertTrue(r["ultimate_buyer_supported"])

    def test_machine_parts_do_not_upgrade_to_complete_machine(self):
        shipment = {**SHIPMENT, "goods_kind": "SPARE_PARTS"}
        r = self._check(shipment=shipment)
        self.assertFalse(r["shipment_supported"])
        self.assertIn("SHIPMENT_IS_NOT_COMPLETE_MACHINE", r["blockers"])

    def test_freight_forwarder_not_a_buyer(self):
        buyer = {**BUYER, "trade_role": "FORWARDER"}
        r = self._check(buyer=buyer)
        self.assertFalse(r["shipment_supported"])
        self.assertIn("PARTY_IS_NOT_BUYER", r["blockers"])

    def test_purchase_order_is_not_import_record(self):
        shipment = {**SHIPMENT, "source_type": "PURCHASE_ORDER"}
        r = self._check(shipment=shipment)
        self.assertFalse(r["shipment_supported"])
        self.assertIn("DIRECT_PROCUREMENT_SOURCE_MISSING", r["blockers"])

    def test_invoice_is_not_customs_import_proof(self):
        shipment = {**SHIPMENT, "source_type": "INVOICE"}
        r = self._check(shipment=shipment)
        self.assertFalse(r["shipment_supported"])

    def test_no_id_or_date_fails_closed(self):
        shipment = {**SHIPMENT, "bill_of_lading": "", "shipment_date": "2026-02-30"}
        r = self._check(shipment=shipment)
        self.assertFalse(r["shipment_supported"])
        self.assertIn("SHIPMENT_DATE_INVALID_OR_MISSING", r["blockers"])
        self.assertIn("SHIPMENT_UNIQUE_IDENTIFIER_MISSING", r["blockers"])

    def test_name_only_without_legal_evidence_not_verified(self):
        buyer = {**BUYER, "identity_evidence_locator": ""}
        r = self._check(buyer=buyer)
        self.assertFalse(r["shipment_supported"])

    def test_wrong_account_identity_must_not_inherit_import(self):
        shipment = {**SHIPMENT, "buyer_account_id": "OTHER-ACCOUNT"}
        r = self._check(shipment=shipment)
        self.assertFalse(r["shipment_supported"])

    def test_industry_prospect_without_import_kept_for_research(self):
        buyer = {**BUYER, "industry_product_evidence_locator": "https://example.test/product"}
        r = self._check(shipment={}, buyer=buyer)
        self.assertEqual(r["stage"], "PROSPECT_UNVERIFIED_MACHINE_IMPORT")
        self.assertFalse(r["missing_contact_rejects_research_candidate"])

    def test_national_code_without_official_locator_not_verified(self):
        hs = {**HS, "national_tariff_code": "8422309000"}
        r = self._check(hs=hs)
        self.assertEqual(r["classification_status"], "HS6_CANDIDATE_ONLY")
        self.assertIn("NATIONAL_TARIFF_NOT_OFFICIALLY_BOUND", r["blockers"])

    def test_national_code_bound_only_as_source_claim_not_customs_ruling(self):
        hs = {**HS, "national_tariff_code": "8422309000",
              "national_official_locator": "https://example.test/tariff/fixture"}
        r = self._check(hs=hs)
        self.assertEqual(r["classification_status"], "NATIONAL_TARIFF_SOURCE_BOUND")
        self.assertTrue(r["national_tariff_verified_as_source_claim"])

    def test_model_capability_must_have_model_specific_evidence(self):
        partial = {"validation_status": "VERIFIED", "seller_identity": "Synthetic Factory"}
        r = self._check(seller_capability=partial)
        self.assertFalse(r["seller_capability_supported_for_model"])
        complete = {**partial, "model_id": "TEST-2026",
                    "model_evidence_locator": "https://example.test/model/TEST-2026"}
        r = self._check(seller_capability=complete)
        self.assertTrue(r["seller_capability_supported_for_model"])

    def test_input_not_mutated(self):
        hs, shipment, buyer = copy.deepcopy(HS), copy.deepcopy(SHIPMENT), copy.deepcopy(BUYER)
        self._check(hs=hs, shipment=shipment, buyer=buyer)
        self.assertEqual((hs, shipment, buyer), (HS, SHIPMENT, BUYER))


if __name__ == "__main__":
    unittest.main()
