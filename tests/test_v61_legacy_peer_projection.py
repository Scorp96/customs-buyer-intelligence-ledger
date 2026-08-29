from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unified_runtime import UnifiedRuntime


class V61LegacyPeerProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-legacy-peer-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-LEGACY-PEER-ROOT",
                "country": "United States",
                "name": "Legacy Peer Root Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "input": {"synthetic": True},
        })
        self.investigation_id = started["investigation_id"]
        self.account_id = started["canonical_account_id"]

    def append_attempt(
        self,
        attempt_id: str,
        owner_id: str,
        evidence_id: str,
        *,
        module: str,
        discovered_peer_id: str = "",
        relationship_evidence_id: str = "",
    ) -> None:
        attempt = {
            "attempt_id": attempt_id,
            "execution_id": f"EXEC-{attempt_id}",
            "owner_id": owner_id,
            "owner_type": "ACCOUNT" if owner_id == self.account_id else "PEER",
            "module_or_branch": module,
            "source_family": "synthetic_registry",
            "result": "POSITIVE",
            "discovered_peer_ids": [discovered_peer_id] if discovered_peer_id else [],
            "relationship_evidence_ids": (
                {discovered_peer_id: [relationship_evidence_id]}
                if discovered_peer_id and relationship_evidence_id
                else {}
            ),
        }
        evidence = [{
            "evidence_id": evidence_id,
            "owner_id": owner_id,
            "owner_type": attempt["owner_type"],
            "claim_key": f"synthetic.{attempt_id.casefold()}",
        }]
        self.runtime.store.append(self.investigation_id, "EXECUTION_RECEIPT_APPENDED", {
            "attempt": attempt,
            "evidence": evidence,
            "pivots_generated": [],
            "pivots_consumed": [],
            "manual_visual_items_resolved": [],
        })

    def append_validated_legacy_peer(self, *, promote: bool = True) -> str:
        peer_id = "PEER-LEGACY-VALIDATED-001"
        self.append_attempt(
            "DISC-001",
            self.account_id,
            "E-REL-001",
            module="regional_peer",
            discovered_peer_id=peer_id,
            relationship_evidence_id="E-REL-001",
        )
        sections = {}
        for label, suffix, module in (
            ("entity", "ENTITY", "buyer_entity_resolution"),
            ("product", "PRODUCT", "product_identity_boundary"),
            ("trade_business", "TRADE", "trade_supplier_continuity"),
            ("company_profile", "PROFILE", "company_profile"),
        ):
            attempt_id = f"ATT-{suffix}-001"
            evidence_id = f"E-{suffix}-001"
            self.append_attempt(attempt_id, peer_id, evidence_id, module=module)
            sections[label] = {
                "passed": True,
                "attempt_ids": [attempt_id],
                "evidence_ids": [evidence_id],
            }
        self.append_attempt(
            "ATT-CONTACT-001",
            peer_id,
            "E-CONTACT-001",
            module="contact_coverage",
        )
        receipt = {
            "peer_id": peer_id,
            "canonical_key": "Legacy Validated Peer LLC",
            "discovered_by_attempt_id": "DISC-001",
            "branch": "regional_peer",
            "inherited_anchor_facts": False,
            "canonical_dedup_checked": True,
            **sections,
            "relationship": {"passed": True, "evidence_ids": ["E-REL-001"]},
            "contact_coverage": {
                "passed": True,
                "attempt_ids": ["ATT-CONTACT-001"],
                "evidence_ids": [],
            },
            "promotion_decision": "PROMOTE" if promote else "DO_NOT_PROMOTE",
            "promotion_reason": "Synthetic historical validation receipt",
            "promotion_gate": "PASSED" if promote else "NOT_REQUIRED",
        }
        self.runtime.store.append(
            self.investigation_id,
            "PEER_RECEIPT_APPENDED",
            {"receipt": receipt},
        )
        return peer_id

    def test_validated_legacy_promote_receipt_projects_anchor_eligible_read_only(self) -> None:
        peer_id = self.append_validated_legacy_peer(promote=True)
        self.assertNotIn(peer_id, self.runtime._v6_state(self.investigation_id)["peers"])

        state = self.runtime.get_account_state({"investigation_id": self.investigation_id})
        peers = {row["peer_id"]: row for row in state["network"]["peers"]}
        self.assertIn(peer_id, peers)
        projected = peers[peer_id]
        self.assertEqual(projected["stage"], "ANCHOR_ELIGIBLE")
        self.assertEqual(projected["projection_source"], "LEGACY_VALIDATED_PEER_RECEIPT")
        self.assertTrue(projected["projection_read_only"])
        self.assertTrue(projected["requires_v6_reconciliation"])
        self.assertFalse(projected["v6_anchor_promoted"])
        self.assertEqual(state["network"]["legacy_validated_peer_projection_count"], 1)

        saturation = self.runtime.evaluate_decision_saturation({
            "investigation_id": self.investigation_id,
        })
        self.assertFalse(saturation["decision_saturated"])
        self.assertIn(peer_id, saturation["anchor_eligible_peers_pending_promotion"])
        self.assertIn(
            f"LEGACY_VALIDATED_PEER_REQUIRES_V6_RECONCILIATION:{peer_id}",
            saturation["blockers"],
        )

    def test_legacy_receipt_without_validation_gates_is_not_projected(self) -> None:
        peer_id = "PEER-LEGACY-UNSAFE-001"
        self.runtime.store.append(self.investigation_id, "PEER_RECEIPT_APPENDED", {
            "receipt": {
                "peer_id": peer_id,
                "canonical_key": "Unsafe Legacy Candidate",
                "discovered_by_attempt_id": "MISSING",
                "branch": "regional_peer",
                "inherited_anchor_facts": True,
                "canonical_dedup_checked": False,
                "entity": {},
                "product": {},
                "trade_business": {},
                "relationship": {},
                "company_profile": {},
                "contact_coverage": {},
                "promotion_decision": "PROMOTE",
                "promotion_gate": "PASSED",
            }
        })
        state = self.runtime.get_account_state({"investigation_id": self.investigation_id})
        self.assertNotIn(peer_id, {row.get("peer_id") for row in state["network"]["peers"]})
        self.assertEqual(state["network"]["legacy_validated_peer_projection_count"], 0)

    def test_native_v6_peer_wins_over_same_legacy_peer_id(self) -> None:
        peer_id = self.append_validated_legacy_peer(promote=False)
        self.runtime.store.append(self.investigation_id, "V6_PEER_DISCOVERED", {
            "peer_id": peer_id,
            "name": "Native V6 Peer",
            "country": "United States",
            "branch": "REGIONAL_PEERS",
            "stage": "DISCOVERED",
            "relationship_evidence_ids": [],
        })
        state = self.runtime.get_account_state({"investigation_id": self.investigation_id})
        rows = [row for row in state["network"]["peers"] if row.get("peer_id") == peer_id]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Native V6 Peer")
        self.assertNotIn("projection_source", rows[0])
        self.assertEqual(state["network"]["legacy_validated_peer_projection_count"], 0)

    def test_projection_reuses_legacy_event_stream_without_v6_replay(self) -> None:
        peer_id = self.append_validated_legacy_peer(promote=False)
        with mock.patch.object(
            self.runtime,
            "_v6_state",
            side_effect=AssertionError("projection must not replay v6 state"),
        ):
            rows = self.runtime._legacy_peer_projections(self.investigation_id)
        self.assertEqual([row["peer_id"] for row in rows], [peer_id])
        self.assertEqual(rows[0]["stage"], "QUALIFIED")


if __name__ == "__main__":
    unittest.main()
