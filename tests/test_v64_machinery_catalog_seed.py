"""99-row machinery HS candidate intake tests, entirely synthetic."""
from __future__ import annotations

import copy
import unittest

from unified_runtime.machinery_catalog_seed_v64 import (
    validate_machinery_catalog_candidates,
    plan_catalog_customs_queries,
)

SOURCE = "b" * 64
GROUPS = ("A MIXING", "B FILLING", "C PRINT", "D LAB", "E WATER")


def fixtures(count=99, coded=85):
    return [{
        "catalog_row_id": f"SMARTORS-20261012-{i+1:04d}",
        "catalog_group": GROUPS[i % len(GROUPS)],
        "catalog_page": str(12 + i),
        "product_name_chinese": "模拟设备" + str(i),
        "product_name_english": "synthetic equipment " + str(i),
        "hs6_candidate": "847982" if i < coded else None,
        "candidate_confidence": "HIGH" if i < coded else "UNDETERMINED",
        "engineering_classification_conditions": "Main function needs verification",
        "search_aliases_english": ["machine term " + str(i), "generic " + str(i)],
        "source_document_sha256": SOURCE,
    } for i in range(count)]


class MachineryCatalogueCandidateTests(unittest.TestCase):
    def test_count_matches_user_source_99_85_14(self):
        src = fixtures()
        copy_before = copy.deepcopy(src)
        result = validate_machinery_catalog_candidates(
            src, expected_row_count=99, expected_hs6_candidate_count=85,
        )
        self.assertEqual(src, copy_before)
        self.assertEqual(result["row_count"], 99)
        self.assertEqual(result["hs6_candidate_count"], 85)
        self.assertEqual(result["pending_classification_count"], 14)
        self.assertEqual(result["national_tariff_codes_confirmed"], 0)
        self.assertEqual(result["actual_import_records_verified"], 0)
        self.assertEqual(result["seller_capability"], "UNCONFIGURED")
        self.assertFalse(result["persistent_mutation_performed"])

    def test_candidate_code_never_proves_national_ruling(self):
        result = validate_machinery_catalog_candidates(fixtures(1, 1))
        row = result["rows"][0]
        self.assertEqual(row["hs6_candidate"], "847982")
        self.assertEqual(row["classification_status"], "HS6_CANDIDATE_NOT_RULING")
        self.assertIsNone(row["national_hs_code"])
        self.assertFalse(row["verified_buyer"])

    def test_uncoded_product_kept_for_future_classification(self):
        result = validate_machinery_catalog_candidates(fixtures(2, 0))
        self.assertEqual(result["pending_classification_count"], 2)
        self.assertTrue(all(row["hs6_candidate"] is None for row in result["rows"]))
        self.assertTrue(all(row["classification_status"] == "PENDING_TECHNICAL_CLASSIFICATION"
                            for row in result["rows"]))

    def test_invalid_hs6_not_promoted(self):
        rows = fixtures(1, 1)
        rows[0]["hs6_candidate"] = "8422309900"
        with self.assertRaisesRegex(ValueError, "HS6_FORMAT_INVALID"):
            validate_machinery_catalog_candidates(rows)

    def test_claimed_verification_from_upload_fails_closed(self):
        rows = fixtures(1, 1)
        rows[0]["binding_customs_classification"] = True
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_VERIFICATION_CLAIM"):
            validate_machinery_catalog_candidates(rows)

    def test_duplicate_catalog_row_is_not_accepted(self):
        rows = fixtures(2, 2)
        rows[1]["catalog_row_id"] = rows[0]["catalog_row_id"]
        with self.assertRaisesRegex(ValueError, "DUPLICATE_ROW_ID"):
            validate_machinery_catalog_candidates(rows)

    def test_unclassified_requires_engineering_reason(self):
        rows = fixtures(1, 0)
        rows[0]["engineering_classification_conditions"] = ""
        with self.assertRaisesRegex(ValueError, "UNCLASSIFIED_REQUIRES_REASON"):
            validate_machinery_catalog_candidates(rows)

    def test_source_provenance_is_mandatory(self):
        rows = fixtures(1, 1)
        rows[0]["source_document_sha256"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_INVALID"):
            validate_machinery_catalog_candidates(rows)

    def test_count_mismatch_cannot_silently_ignore_missing_rows(self):
        rows = fixtures(99, 85)[:-1]
        with self.assertRaisesRegex(ValueError, "ROW_COUNT_MISMATCH"):
            validate_machinery_catalog_candidates(rows, expected_row_count=99)

    def test_contiguous_row_lineage_required_for_strict_99_item_import(self):
        rows = fixtures(99, 85)
        rows[20]["catalog_row_id"] = "SMARTORS-20261012-0100"
        with self.assertRaisesRegex(ValueError, "ROW_LINEAGE_NOT_CONTIGUOUS"):
            validate_machinery_catalog_candidates(
                rows, expected_row_count=99,
                expected_hs6_candidate_count=85,
            )

    def test_order_swap_is_not_silently_accepted_as_same_catalogue(self):
        rows = fixtures(99, 85)
        rows[0], rows[1] = rows[1], rows[0]
        with self.assertRaisesRegex(ValueError, "ROW_LINEAGE_NOT_CONTIGUOUS"):
            validate_machinery_catalog_candidates(rows, expected_row_count=99)

    def test_strict_catalogue_mixed_workbook_sources_fail_closed(self):
        rows = fixtures(99, 85)
        rows[5]["source_document_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "MIXED_SOURCE_FINGERPRINT"):
            validate_machinery_catalog_candidates(rows, expected_row_count=99)

    def test_budget_spans_groups_and_is_not_search_execution(self):
        source = validate_machinery_catalog_candidates(fixtures())
        plan = plan_catalog_customs_queries(source, target_country="Indonesia", limit=5)
        self.assertEqual(plan["returned_count"], 5)
        self.assertEqual(len({x["catalog_group"] for x in plan["queries"]}), 5)
        self.assertTrue(plan["truncated"])
        self.assertFalse(plan["source_coverage_complete"])
        self.assertTrue(all(not r["search_execution_performed"] for r in plan["queries"]))

    def test_query_without_candidate_hs_is_still_plannable(self):
        source = validate_machinery_catalog_candidates(fixtures(2, 0))
        plan = plan_catalog_customs_queries(source, target_country="Vietnam")
        self.assertTrue(plan["queries"])
        self.assertTrue(all(q["hs6_candidate"] is None for q in plan["queries"]))
        self.assertTrue(all(not q["query_uses_unverified_hs6_candidate"] for q in plan["queries"]))

    def test_repeat_plan_is_deterministic(self):
        source = validate_machinery_catalog_candidates(fixtures(15, 10))
        a = plan_catalog_customs_queries(source, target_country="Brazil")
        b = plan_catalog_customs_queries(source, target_country="Brazil")
        self.assertEqual(a, b)

    def test_bad_query_limit_fails_closed(self):
        source = validate_machinery_catalog_candidates(fixtures(1, 1))
        with self.assertRaisesRegex(ValueError, "LIMIT_INVALID"):
            plan_catalog_customs_queries(source, target_country="Brazil", limit=0)

    def test_query_names_do_not_equal_actual_buyers(self):
        source = validate_machinery_catalog_candidates(fixtures(5, 5))
        result = plan_catalog_customs_queries(source, target_country="Mexico")
        self.assertFalse(result["planning_is_execution_proof"])
        self.assertTrue(result["host_execution_required"])
        self.assertTrue(all(r["buyer_identity_verified"] is False for r in result["queries"]))


if __name__ == "__main__":
    unittest.main()
