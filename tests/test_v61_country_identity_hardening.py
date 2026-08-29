from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_runtime import (
    COUNTRY_RELATION_CONFLICT,
    COUNTRY_RELATION_MISSING,
    COUNTRY_RELATION_SAME,
    COUNTRY_RELATION_UNRESOLVED,
    CountryAwareCanonicalRegistry,
    UnifiedRuntime,
)


class V61CountryIdentityHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-country-identity-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = UnifiedRuntime(self.root / "sessions")

    def test_production_runtime_uses_country_aware_registry_and_contract(self) -> None:
        self.assertIsInstance(self.runtime.canonical_registry, CountryAwareCanonicalRegistry)
        contract = self.runtime.get_runtime_contract({})["canonical_identity_resolution_v6_1"]
        self.assertEqual(contract["country_input_contract"], "FREE_FORM_NONEMPTY_STRING")
        self.assertEqual(
            contract["country_relation_states"],
            [
                COUNTRY_RELATION_SAME,
                COUNTRY_RELATION_CONFLICT,
                COUNTRY_RELATION_MISSING,
                COUNTRY_RELATION_UNRESOLVED,
            ],
        )
        self.assertEqual(contract["unknown_country_representation_policy"], "AMBIGUOUS_FAIL_CLOSED")
        self.assertFalse(contract["country_string_inequality_alone_is_conflict_proof"])
        self.assertFalse(contract["same_name_unknown_country_representation_can_create_duplicate"])

    def test_common_country_aliases_are_same_for_primary_legal_name(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Country Alias Synthetic LLC",
                "country": "US",
            },
        })
        matched = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Country Alias Synthetic LLC",
                "country": "United States of America",
            },
            "create_if_missing": False,
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(matched["status"], "MATCHED")
        self.assertEqual(matched["match"]["account_id"], created["match"]["account_id"])
        self.assertIn("PRIMARY_LEGAL_NAME_COUNTRY", matched["match"]["reasons"])

    def test_common_country_aliases_do_not_create_false_strong_id_conflict(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Country Strong ID Synthetic LLC",
                "country": "USA",
                "tax_ids": ["COUNTRY-TAX-SYNTH-001"],
            },
            "requested_account_id": "C-COUNTRY-ALIAS-001",
        })
        matched = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Renamed Country Strong ID Synthetic LLC",
                "country": "United States",
                "tax_ids": ["COUNTRY-TAX-SYNTH-001"],
            },
            "requested_account_id": "C-COUNTRY-ALIAS-001",
            "create_if_missing": False,
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(matched["status"], "MATCHED")
        self.assertIn("EXACT_ACCOUNT_ID", matched["match"]["reasons"])
        self.assertIn("TAX_ID", matched["match"]["reasons"])

    def test_recognized_different_countries_remain_strong_identity_conflict(self) -> None:
        self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Known Country Conflict One LLC",
                "country": "United States",
                "external_ids": ["COUNTRY-EXT-SYNTH-001"],
            },
        })
        conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Known Country Conflict Two LLC",
                "country": "Canada",
                "external_ids": ["COUNTRY-EXT-SYNTH-001"],
            },
            "create_if_missing": False,
        })
        self.assertEqual(conflict["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(conflict["ambiguity_reason"], "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW")
        self.assertIn("COUNTRY_CONFLICT", conflict["candidates"][0]["reasons"])
        self.assertEqual(conflict["candidates"][0]["country_relation"], COUNTRY_RELATION_CONFLICT)

    def test_unknown_country_representation_cannot_silently_bind_strong_id(self) -> None:
        self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Unknown Country One LLC",
                "country": "Synthetic Republic Long Form",
                "external_ids": ["UNKNOWN-COUNTRY-EXT-001"],
            },
        })
        conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Unknown Country Two LLC",
                "country": "SRLF",
                "external_ids": ["UNKNOWN-COUNTRY-EXT-001"],
            },
            "create_if_missing": False,
        })
        self.assertEqual(conflict["status"], "AMBIGUOUS_MATCH")
        self.assertIn("COUNTRY_REPRESENTATION_UNRESOLVED", conflict["candidates"][0]["reasons"])
        self.assertEqual(conflict["candidates"][0]["country_relation"], COUNTRY_RELATION_UNRESOLVED)

    def test_unknown_country_representation_blocks_same_name_duplicate_creation(self) -> None:
        first = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Unknown Country Name Collision LLC",
                "country": "Synthetic Republic Long Form",
            },
        })
        second = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Unknown Country Name Collision LLC",
                "country": "SRLF",
            },
        })
        self.assertEqual(first["status"], "CREATED")
        self.assertEqual(second["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 1)
        self.assertIn("COUNTRY_REPRESENTATION_UNRESOLVED", second["candidates"][0]["reasons"])

    def test_missing_legacy_country_does_not_become_affirmative_country_conflict_for_exact_id(self) -> None:
        self.runtime.canonical_registry.log.append("CANONICAL_ACCOUNT_CREATED", {
            "account_id": "C-LEGACY-COUNTRY-MISSING",
            "account": {
                "account_id": "C-LEGACY-COUNTRY-MISSING",
                "name": "Legacy Missing Country Synthetic LLC",
            },
            "identity_keys_sha256": "0" * 64,
            "created_at": "2026-08-29T00:00:00Z",
        })
        matched = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Legacy Missing Country Synthetic LLC",
                "country": "United States",
            },
            "requested_account_id": "C-LEGACY-COUNTRY-MISSING",
            "create_if_missing": False,
        })
        self.assertEqual(matched["status"], "MATCHED")
        self.assertEqual(matched["match"]["account_id"], "C-LEGACY-COUNTRY-MISSING")


if __name__ == "__main__":
    unittest.main()
