from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_runtime import UnifiedRuntime


BODY = (
    "Hello, I am reaching out to introduce our PVC board production capabilities and learn whether this product category "
    "is relevant to your current sourcing plans. We can support stable specifications, practical order planning, and clear "
    "production communication for regular commercial requirements. If you are reviewing alternative suppliers or preparing "
    "future purchasing, I can send a concise product overview and discuss the sizes, thicknesses, densities, and applications "
    "that matter to your team. Please let me know whether a short comparison would be useful, and I will keep the information "
    "focused on your actual requirements."
)


class V61OutreachHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-outreach-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        self.start = self.runtime.start_investigation({
            "account": {
                "account_id": "C-OUTREACH-SYNTH",
                "country": "United States",
                "name": "Outreach Synthetic Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = self.start["investigation_id"]

    def _append_information_route(
        self,
        *,
        information_id: str,
        owner_id: str = "C-OUTREACH-SYNTH",
        guessed: bool = False,
        current: str = "CURRENT_CONFIRMED",
    ) -> None:
        self.runtime.store.append(
            self.investigation_id,
            "INFORMATION_RECORD_APPENDED",
            {
                "record": {
                    "information_id": information_id,
                    "information_type": "ROUTE",
                    "subject_type": "ACCOUNT",
                    "subject_owner_id": owner_id,
                    "route_scope": "BUYER_DIRECT",
                    "temporal_status": current,
                    "outreach_eligible_effective": True,
                    "value": {
                        "channel": "EMAIL",
                        "value": "buyer@example.invalid",
                        "verified": True,
                        "masked": False,
                        "guessed": guessed,
                    },
                    "evidence_ids": ["EVD-OUTREACH-INFO-001"],
                    "source_url": "https://example.invalid/outreach/contact",
                    "source_locator": "https://example.invalid/outreach/contact#email",
                    "conflicts_with_information_ids": [],
                }
            },
        )

    def _append_positive_closure(self) -> str:
        state = self.runtime._v6_state(self.investigation_id)
        closure_id = "CLOS-22222222222222222222222222222222"
        self.runtime.store.append(
            self.investigation_id,
            "CLOSURE_ISSUED",
            {
                "schema": "cbi.closure.v6.1",
                "closure_id": closure_id,
                "investigation_id": self.investigation_id,
                "account_id": "C-OUTREACH-SYNTH",
                "status": "COMPLETE_POSITIVE",
                "issued_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                "basis_hash": state["events"][-1]["event_hash"],
                "state_dimensions": {"outreach_prerequisites_complete": True},
                "decision_saturation_sha256": "0" * 64,
                "used": False,
            },
        )
        return closure_id

    def _prepare(self, closure_id: str) -> dict:
        state = self.runtime._v6_state(self.investigation_id)
        return self.runtime.prepare_outreach({
            "investigation_id": self.investigation_id,
            "closure_id": closure_id,
            "route": {
                "kind": "EMAIL",
                "value": "buyer@example.invalid",
                "verified": True,
                "current": True,
                "owned_by_account": True,
                "owner_entity_id": "C-OUTREACH-SYNTH",
                "evidence_ids": ["EVD-OUTREACH-INFO-001"],
            },
            "history_digest": state["start"]["history_digest"],
            "authority_digest": state["start"]["authority_digest"],
            "subject": "PVC board sourcing inquiry",
            "body": BODY,
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })

    def test_information_record_route_can_prepare_after_canonical_readiness(self) -> None:
        self._append_information_route(information_id="INFO-OUTREACH-CANONICAL-001")
        readiness = self.runtime.evaluate_outreach_readiness({
            "investigation_id": self.investigation_id,
        })
        self.assertIn("INFO-OUTREACH-CANONICAL-001", readiness["valid_information_route_ids"])
        closure_id = self._append_positive_closure()
        prepared = self._prepare(closure_id)
        self.assertTrue(prepared["prepared"], prepared)
        self.assertEqual(prepared["status"], "PREPARED_FOR_RENDER")
        self.assertEqual(prepared["canonical_route_match_count"], 1)
        self.assertEqual(
            prepared["canonical_route_binding"]["information_id"],
            "INFO-OUTREACH-CANONICAL-001",
        )
        self.assertEqual(
            prepared["canonical_route_binding"]["route_source"],
            "INFORMATION_RECORD",
        )
        self.assertFalse(prepared["sends_message"])

    def test_cross_owner_information_route_remains_blocked(self) -> None:
        self._append_information_route(
            information_id="INFO-OUTREACH-CROSS-OWNER",
            owner_id="OTHER-ACCOUNT",
        )
        closure_id = self._append_positive_closure()
        prepared = self._prepare(closure_id)
        self.assertFalse(prepared["prepared"])
        self.assertIn(
            "ROUTE_NOT_BOUND_TO_CANONICAL_ROUTE_VIEW",
            prepared["block_reasons"],
        )

    def test_guessed_information_route_remains_blocked(self) -> None:
        self._append_information_route(
            information_id="INFO-OUTREACH-GUESSED",
            guessed=True,
        )
        closure_id = self._append_positive_closure()
        prepared = self._prepare(closure_id)
        self.assertFalse(prepared["prepared"])
        self.assertIn(
            "ROUTE_NOT_BOUND_TO_CANONICAL_ROUTE_VIEW",
            prepared["block_reasons"],
        )

    def test_stale_information_route_remains_blocked(self) -> None:
        self._append_information_route(
            information_id="INFO-OUTREACH-STALE",
            current="HISTORICAL",
        )
        closure_id = self._append_positive_closure()
        prepared = self._prepare(closure_id)
        self.assertFalse(prepared["prepared"])
        self.assertIn(
            "ROUTE_NOT_BOUND_TO_CANONICAL_ROUTE_VIEW",
            prepared["block_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
