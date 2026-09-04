import importlib.util
import unittest
from pathlib import Path


def _load_detector():
    root = Path(__file__).resolve().parents[1]
    path = root / "unified_runtime" / "canonical_identity_reconciliation_v64.py"
    spec = importlib.util.spec_from_file_location("canonical_identity_reconciliation_v64", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.detect_identity_reconciliation


detect_identity_reconciliation = _load_detector()


def account(account_id, name, country="Vietnam", **kwargs):
    return {
        "account_id": account_id,
        "name": name,
        "country": country,
        "aliases": kwargs.pop("aliases", []),
        "tax_id": kwargs.pop("tax_id", ""),
        "tax_ids": kwargs.pop("tax_ids", []),
        "address": kwargs.pop("address", ""),
        "addresses": kwargs.pop("addresses", []),
        "external_ids": kwargs.pop("external_ids", []),
        **kwargs,
    }


class CanonicalIdentityReconciliationDetectorTests(unittest.TestCase):
    def test_same_country_shared_tax_id_is_deterministic_duplicate_candidate(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading Co Ltd", tax_id="SYNTH-TAX-ALPHA"),
            account("A-2", "ACME TRADING COMPANY LIMITED", tax_ids=["SYNTH-TAX-ALPHA"]),
        ])
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["status"], "DETERMINISTIC_DUPLICATE_CANDIDATE")
        self.assertEqual(item["account_ids"], ["A-1", "A-2"])
        self.assertIn("SHARED_TAX_ID", item["evidence_basis"])
        self.assertFalse(item["auto_merge_allowed"])

    def test_same_name_same_country_conflicting_tax_ids_is_identity_conflict(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading Co Ltd", tax_id="TAX-111"),
            account("A-2", "Acme Trading Co., Ltd.", tax_id="TAX-222"),
        ])
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["status"], "IDENTITY_CONFLICT")
        self.assertIn("LEGAL_NAME_MATCH_TAX_ID_CONFLICT", item["evidence_basis"])
        self.assertFalse(item["auto_merge_allowed"])

    def test_same_name_same_country_without_strong_id_requires_review(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading and Production Company Limited"),
            account("A-2", "Acme Trading & Production Co., Ltd."),
        ])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["status"], "REVIEW_REQUIRED")
        self.assertFalse(result["items"][0]["auto_merge_allowed"])

    def test_same_exact_external_id_same_country_requires_review_not_auto_merge(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme One", external_ids=["https://acme.example/"]),
            account("A-2", "Acme Two", external_ids=["https://acme.example"]),
        ])
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["status"], "REVIEW_REQUIRED")
        self.assertIn("SHARED_EXTERNAL_ID", item["evidence_basis"])

    def test_alias_only_overlap_does_not_create_candidate(self):
        result = detect_identity_reconciliation([
            account("A-1", "Legal One Ltd", aliases=["Acme"]),
            account("A-2", "Legal Two Ltd", aliases=["Acme"]),
        ])
        self.assertEqual(result["items"], [])

    def test_same_name_different_country_does_not_create_candidate(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading Ltd", country="Vietnam"),
            account("A-2", "Acme Trading Ltd", country="Thailand"),
        ])
        self.assertEqual(result["items"], [])

    def test_exact_address_plus_name_is_review_required_not_deterministic(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading Ltd", address="Lot 1, Hanoi"),
            account("A-2", "ACME TRADING LIMITED", addresses=["Lot 1 Hanoi"]),
        ])
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["status"], "REVIEW_REQUIRED")
        self.assertIn("LEGAL_NAME_MATCH", item["evidence_basis"])
        self.assertIn("SHARED_ADDRESS", item["evidence_basis"])

    def test_many_same_name_accounts_collapse_to_one_review_cluster(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading Company Limited"),
            account("A-2", "ACME TRADING CO LTD"),
            account("A-3", "Acme Trading Co., Ltd."),
            account("A-4", "Acme Trading Company Limited"),
        ])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["account_ids"], ["A-1", "A-2", "A-3", "A-4"])
        self.assertEqual(result["items"][0]["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["cluster_count"], 1)

    def test_cluster_is_deterministic_only_when_all_members_share_tax_id(self):
        result = detect_identity_reconciliation([
            account("A-1", "Acme Trading Company Limited", tax_id="TAX-1"),
            account("A-2", "ACME TRADING CO LTD", tax_id="TAX-1"),
            account("A-3", "Acme Trading Co., Ltd."),
        ])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["status"], "REVIEW_REQUIRED")
        self.assertIn("PARTIAL_SHARED_TAX_ID", result["items"][0]["evidence_basis"])

    def test_detector_never_mutates_input_records(self):
        rows = [account("A-1", "Acme Ltd"), account("A-2", "Acme Ltd")]
        before = [dict(row) for row in rows]
        detect_identity_reconciliation(rows)
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
