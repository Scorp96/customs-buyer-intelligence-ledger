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
        self.assertEqual(canonical["alias_collision_policy"], "AMBIGUOUS_FAIL_CLOSED")
        self.assertEqual(
            canonical["alias_resolution_requirement"],
            "EXACT_CANONICAL_ACCOUNT_ID_AFTER_EVIDENCE_REVIEW",
        )

    def test_untyped_brand_alias_never_auto_merges_or_auto_creates(self) -> None:
        created = self.runtime.resolve_or_create_account({
            "candidate": {
                "name": "Western Woods LLC",
                "country": "Puerto Rico",
                "aliases": ["HOME iD"],
                "address": "100 Synthetic Industrial Rd",
            },
        })
        self.assertEqual(created["status"], "CREATED")
        account_id = created["match"]["account_id"]
        self.assertEqual(len(self.runtime.canonical_registry.entries()), 1)

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
        self.assertIsNone(unresolved["match"])
        self.assertEqual(unresolved["ambiguity_reason"], "ALIAS_RELATION_REQUIRES_CANONICAL_ID_PROOF")

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
                "value": {
                    "brand_name": "HOME iD Synthetic",
                    "relationship": "OPERATING_BRAND",
                },
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
