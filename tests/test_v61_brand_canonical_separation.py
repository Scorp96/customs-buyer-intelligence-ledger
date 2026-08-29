from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime import (
    EvidenceBoundCanonicalRegistry,
    UnifiedRuntime,
    V61BrandHardeningMixin,
    V61CanonicalIdentityHardeningMixin,
    ValidationError,
)


class V61BrandCanonicalSeparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-brand-canonical-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = UnifiedRuntime(self.root / "sessions")

    def test_production_runtime_wires_brand_and_canonical_hardening(self) -> None:
        self.assertIsInstance(self.runtime, V61BrandHardeningMixin)
        self.assertIsInstance(self.runtime, V61CanonicalIdentityHardeningMixin)
        self.assertIsInstance(self.runtime.canonical_registry, EvidenceBoundCanonicalRegistry)
        contract = self.runtime.get_runtime_contract({})
        self.assertTrue(contract["brand_legal_entity_separation_v6_1"]["brand_name_never_auto_merges_legal_entity"])
        canonical = contract["canonical_identity_resolution_v6_1"]
        self.assertFalse(canonical["raw_aliases_are_legal_identity_keys"])
        self.assertFalse(canonical["typed_aliases_are_automatic_match_keys"])
        self.assertFalse(canonical["address_only_match_allowed"])
        self.assertTrue(canonical["primary_name_match_requires_explicit_country_overlap"])
        self.assertEqual(canonical["same_name_missing_country_policy"], "AMBIGUOUS_FAIL_CLOSED")
        self.assertTrue(canonical["requested_account_id_is_exact_constraint"])
        self.assertFalse(canonical["requested_id_fuzzy_substitution_allowed"])
        self.assertTrue(canonical["explicit_new_id_without_fuzzy_identity_can_be_allocated"])
        self.assertTrue(canonical["contradictory_tax_ids_fail_closed"])
        self.assertTrue(canonical["tax_conflict_applies_to_external_id_candidates"])
        self.assertEqual(canonical["strong_id_country_conflict_policy"], "AMBIGUOUS_FAIL_CLOSED")
        self.assertEqual(
            canonical["country_conflict_applies_to"],
            ["EXACT_ACCOUNT_ID", "TAX_ID", "EXTERNAL_ID"],
        )

    def test_explicit_new_account_id_allows_low_information_allocation_without_fuzzy_substitution(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {"country": "Canada"},
            "requested_account_id": "MCP-PROVIDER-SYNTH",
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(created["match"]["account_id"], "MCP-PROVIDER-SYNTH")
        replay = self.runtime.resolve_or_create_account({
            "candidate": {"country": "Canada"},
            "requested_account_id": "MCP-PROVIDER-SYNTH",
            "create_if_missing": False,
        })
        self.assertEqual(replay["status"], "MATCHED")
        self.assertIn("EXACT_ACCOUNT_ID", replay["match"]["reasons"])

    def test_untyped_brand_alias_never_auto_merges_or_auto_creates(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Western Woods LLC",
                "country": "Puerto Rico",
                "aliases": ["HOME iD"],
                "address": "100 Synthetic Industrial Rd",
            },
        })
        account_id = created["match"]["account_id"]
        collision = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "HOME iD",
                "country": "Puerto Rico",
                "address": "100 Synthetic Industrial Rd",
            },
        })
        self.assertEqual(collision["status"], "AMBIGUOUS_MATCH")
        self.assertIsNone(collision["match"])
        self.assertFalse(collision["automatic_merge_allowed"])
        self.assertFalse(collision["automatic_create_allowed"])
        self.assertEqual(collision["ambiguity_reason"], "ALIAS_RELATION_REQUIRES_CANONICAL_ID_PROOF")
        self.assertEqual(collision["candidates"][0]["account_id"], account_id)
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 1)
        with self.assertRaises(ValidationError):
            self.runtime.start_investigation({
                "account": {
                    "name": "HOME iD",
                    "country": "Puerto Rico",
                    "address": "100 Synthetic Industrial Rd",
                },
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
            })

    def test_typed_legal_alias_is_review_signal_not_merge_authority(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Western Woods LLC",
                "country": "Puerto Rico",
                "legal_aliases": ["Western Woods Incorporated"],
            },
        })
        account_id = created["match"]["account_id"]
        unresolved = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Western Woods Incorporated",
                "country": "Puerto Rico",
            },
            "create_if_missing": False,
        })
        self.assertEqual(unresolved["status"], "AMBIGUOUS_MATCH")
        reviewed = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Western Woods Incorporated",
                "country": "Puerto Rico",
            },
            "requested_account_id": account_id,
            "create_if_missing": False,
        })
        self.assertEqual(reviewed["status"], "MATCHED")
        self.assertEqual(reviewed["match"]["account_id"], account_id)
        self.assertIn("EXACT_ACCOUNT_ID", reviewed["match"]["reasons"])

    def test_candidate_alias_collision_blocks_silent_duplicate_creation(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Arecibo Synthetic Center LLC",
                "country": "Puerto Rico",
            },
        })
        account_id = created["match"]["account_id"]
        collision = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Arecibo Synthetic Design LLC",
                "country": "Puerto Rico",
                "aliases": ["Arecibo Synthetic Center LLC"],
            },
        })
        self.assertEqual(collision["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(collision["candidates"][0]["account_id"], account_id)
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 1)

    def test_address_alone_has_no_canonical_merge_authority(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Synthetic Tenant One LLC",
                "country": "United States",
                "address": "200 Shared Commerce Plaza",
            },
        })
        unrelated = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Synthetic Tenant Two LLC",
                "country": "United States",
                "address": "200 Shared Commerce Plaza",
            },
            "create_if_missing": False,
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(unrelated["status"], "NOT_FOUND")

    def test_same_name_legacy_missing_country_fails_closed_instead_of_merging_or_creating_duplicate(self) -> None:
        self.runtime.canonical_registry.log.append("CANONICAL_ACCOUNT_CREATED", {
            "account_id": "C-LEGACY-NO-COUNTRY",
            "account": {
                "account_id": "C-LEGACY-NO-COUNTRY",
                "name": "Global Name Synthetic LLC",
            },
            "identity_keys_sha256": "0" * 64,
            "created_at": "2026-08-28T00:00:00Z",
        })
        unresolved = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Global Name Synthetic LLC",
                "country": "United States",
            },
        })
        self.assertEqual(unresolved["status"], "AMBIGUOUS_MATCH")
        self.assertIsNone(unresolved["match"])
        self.assertEqual(
            unresolved["ambiguity_reason"],
            "PRIMARY_LEGAL_NAME_REQUIRES_COUNTRY_OR_STRONG_ID",
        )
        self.assertEqual(unresolved["candidates"][0]["account_id"], "C-LEGACY-NO-COUNTRY")
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 1)

    def test_same_name_explicit_different_country_can_remain_separate(self) -> None:
        first = self.runtime.resolve_or_create_account({
            "candidate": {"name": "Cross Border Synthetic Ltd", "country": "Canada"},
        })
        second = self.runtime.resolve_or_create_account({
            "candidate": {"name": "Cross Border Synthetic Ltd", "country": "Australia"},
        })
        self.assertEqual(first["status"], "CREATED")
        self.assertEqual(second["status"], "CREATED")
        self.assertNotEqual(first["match"]["account_id"], second["match"]["account_id"])
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 2)

    def test_requested_account_id_is_never_fuzzily_substituted(self) -> None:
        existing = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Exact Identity Synthetic LLC",
                "country": "United States",
            },
            "requested_account_id": "C-EXACT-001",
        })
        self.assertEqual(existing["status"], "CREATED")
        collision = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Exact Identity Synthetic LLC",
                "country": "United States",
            },
            "requested_account_id": "C-DIFFERENT-999",
        })
        self.assertEqual(collision["status"], "AMBIGUOUS_MATCH")
        self.assertIsNone(collision["match"])
        self.assertEqual(collision["ambiguity_reason"], "REQUESTED_ACCOUNT_ID_NOT_FOUND_IDENTITY_COLLISION")
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 1)

    def test_exact_account_id_cannot_override_explicit_country_conflict(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Exact Country Synthetic LLC",
                "country": "United States",
            },
            "requested_account_id": "C-COUNTRY-EXACT",
        })
        self.assertEqual(created["status"], "CREATED")
        conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Exact Country Synthetic LLC",
                "country": "Canada",
            },
            "requested_account_id": "C-COUNTRY-EXACT",
            "create_if_missing": False,
        })
        self.assertEqual(conflict["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(conflict["ambiguity_reason"], "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW")
        self.assertIn("COUNTRY_CONFLICT", conflict["candidates"][0]["reasons"])

    def test_tax_id_conflict_blocks_name_match_and_exact_id_override(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Tax Conflict Synthetic LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-A"],
            },
            "requested_account_id": "C-TAX-001",
        })
        self.assertEqual(created["status"], "CREATED")
        same_name_conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Tax Conflict Synthetic LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-B"],
            },
        })
        self.assertEqual(same_name_conflict["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(same_name_conflict["ambiguity_reason"], "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW")
        exact_id_conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Tax Conflict Synthetic LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-B"],
            },
            "requested_account_id": "C-TAX-001",
            "create_if_missing": False,
        })
        self.assertEqual(exact_id_conflict["status"], "AMBIGUOUS_MATCH")
        self.assertIsNone(exact_id_conflict["match"])
        self.assertIn("TAX_ID_CONFLICT", exact_id_conflict["candidates"][0]["reasons"])

    def test_tax_id_match_cannot_override_explicit_country_conflict(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Tax Country One LLC",
                "country": "United States",
                "tax_ids": ["SHARED-TAX-SYNTH-001"],
            },
        })
        conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Tax Country Two LLC",
                "country": "Canada",
                "tax_ids": ["SHARED-TAX-SYNTH-001"],
            },
            "create_if_missing": False,
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(conflict["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(conflict["ambiguity_reason"], "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW")
        self.assertIn("COUNTRY_CONFLICT", conflict["candidates"][0]["reasons"])

    def test_external_id_match_cannot_override_tax_id_conflict(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "External Identity One LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-EXT-A"],
                "external_ids": ["EXT-SYNTH-001"],
            },
        })
        conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "External Identity Renamed LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-EXT-B"],
                "external_ids": ["EXT-SYNTH-001"],
            },
            "create_if_missing": False,
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(conflict["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(conflict["ambiguity_reason"], "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW")
        self.assertIn("TAX_ID_CONFLICT", conflict["candidates"][0]["reasons"])

    def test_external_id_match_cannot_override_explicit_country_conflict(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "External Country One LLC",
                "country": "United States",
                "external_ids": ["EXT-COUNTRY-SYNTH-001"],
            },
        })
        conflict = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "External Country Two LLC",
                "country": "Canada",
                "external_ids": ["EXT-COUNTRY-SYNTH-001"],
            },
            "create_if_missing": False,
        })
        self.assertEqual(created["status"], "CREATED")
        self.assertEqual(conflict["status"], "AMBIGUOUS_MATCH")
        self.assertEqual(conflict["ambiguity_reason"], "STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW")
        self.assertIn("COUNTRY_CONFLICT", conflict["candidates"][0]["reasons"])

    def test_matching_tax_id_remains_strong_identity_authority(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Tax Match Synthetic LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-SAME"],
            },
        })
        matched = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Renamed Tax Match Synthetic LLC",
                "country": "United States",
                "tax_ids": ["US-TAX-SAME"],
            },
            "create_if_missing": False,
        })
        self.assertEqual(matched["status"], "MATCHED")
        self.assertEqual(matched["match"]["account_id"], created["match"]["account_id"])
        self.assertIn("TAX_ID", matched["match"]["reasons"])

    def test_brand_graph_classifies_alias_without_legal_merge_permission(self) -> None:
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-BRAND-SYNTH",
                "name": "Western Woods Synthetic LLC",
                "country": "Puerto Rico",
                "aliases": ["HOME iD Synthetic"],
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        investigation_id = started["investigation_id"]
        material = "synthetic HOME iD operating brand evidence"
        self.runtime.append_information_record({
            "investigation_id": investigation_id,
            "record": {
                "information_id": "INFO-BRAND-SYNTH-001",
                "investigation_id": investigation_id,
                "related_account_id": "C-BRAND-SYNTH",
                "subject_type": "BRAND",
                "subject_owner_id": "BRAND-HOME-ID-SYNTH",
                "relationship_to_account": "OPERATING_BRAND",
                "information_type": "FACT",
                "claim_key": "identity.brand_relationship",
                "value": {"brand_name": "HOME iD Synthetic", "relationship": "OPERATING_BRAND"},
                "source_type": "USER_INPUT",
                "source_reference_type": "USER_INPUT",
                "source_url": "",
                "source_locator": "user-input://synthetic/brand-separation",
                "observed_at": "2026-08-29T00:00:00Z",
                "content_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
                "confidence": "HIGH",
                "temporal_status": "CURRENT",
                "route_scope": "NOT_A_ROUTE",
                "outreach_eligible_claimed": False,
                "supersedes_information_ids": [],
                "conflicts_with_information_ids": [],
                "evidence_ids": [],
                "notes": "Synthetic regression fixture only.",
            },
        })
        state = self.runtime.get_account_state({"investigation_id": investigation_id})
        self.assertTrue(state["identity"]["legal_entity_separate_from_brand_graph"])
        self.assertEqual(state["identity"]["alias_classification"]["brand_tokens"], ["HOME iD Synthetic"])
        self.assertEqual(len(state["brands"]), 1)
        brand = state["brands"][0]
        self.assertEqual(brand["brand_name"], "HOME iD Synthetic")
        self.assertEqual(brand["relationship_to_legal_account"], "OPERATING_BRAND")
        self.assertFalse(brand["legal_entity_merge_allowed"])
        self.assertTrue(brand["legal_identity_inference_from_brand_prohibited"])


if __name__ == "__main__":
    unittest.main()
