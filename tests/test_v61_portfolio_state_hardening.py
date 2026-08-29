from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unified_runtime import UnifiedRuntime


class V61PortfolioStateHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-portfolio-state-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")

    def test_researched_paused_session_beats_empty_not_saturated_duplicate(self) -> None:
        researched_id = "INV-20260827T084936Z-fccc3b897c27"
        empty_id = "INV-20260828T023831Z-e72aea0c86a0"
        for investigation_id in (researched_id, empty_id):
            (self.runtime.store.root / f"{investigation_id}.jsonl").touch()

        rows = {
            researched_id: {
                "investigation_id": researched_id,
                "account_id": "C001",
                "account_name": "Western Woods, LLC",
                "investigation_scope": "DEFAULT",
                "canonical_scope_key": "C001::DEFAULT",
                "environment": "PRODUCTION",
                "lifecycle": "ACTIVE",
                "commercial_value_grade": "A-",
                "research_confidence": "R3",
                "decision_saturation": "PAUSED_RESOURCE_LIMIT",
                "next_eiv": 0.0,
                "budget": {},
                "observation_count": 12,
                "peer_count": 0,
                "event_count": 202,
                "last_safe_seq": 202,
                "last_safe_event_hash": "a" * 64,
            },
            empty_id: {
                "investigation_id": empty_id,
                "account_id": "C001",
                "account_name": "Western Woods, LLC",
                "investigation_scope": "DEFAULT",
                "canonical_scope_key": "C001::DEFAULT",
                "environment": "PRODUCTION",
                "lifecycle": "ACTIVE",
                "commercial_value_grade": "NQ",
                "research_confidence": "R0",
                "decision_saturation": "NOT_SATURATED",
                "next_eiv": 11.7,
                "budget": {},
                "observation_count": 0,
                "peer_count": 0,
                "event_count": 2,
                "last_safe_seq": 2,
                "last_safe_event_hash": "b" * 64,
            },
        }

        with mock.patch.object(self.runtime, "_portfolio_row", side_effect=lambda inv: rows[inv]):
            queue = self.runtime.get_portfolio_queue({"limit": 100})
            expanded = self.runtime.get_portfolio_queue({
                "limit": 100,
                "include_non_active": True,
                "include_non_production": True,
            })

        self.assertEqual(queue["count"], 1)
        self.assertEqual(queue["queue"][0]["investigation_id"], researched_id)
        expanded_rows = {row["investigation_id"]: row for row in expanded["queue"]}
        self.assertEqual(expanded_rows[researched_id]["lifecycle"], "ACTIVE")
        self.assertEqual(expanded_rows[empty_id]["lifecycle"], "SUPERSEDED")
        self.assertEqual(expanded_rows[empty_id]["superseded_by"], researched_id)
        self.assertFalse(
            queue["policy"]["initialization_only_session_may_supersede_researched_session"]
        )

    def test_historical_synth_and_pending_buyer_ids_are_non_production(self) -> None:
        synth = {
            "account": {
                "account_id": "SYNTH-UNICODE-VERIFY-001",
                "name": "Unicode verification fixture",
                "country": "Unknown",
            },
            "input": {},
        }
        pending = {
            "account": {
                "account_id": "PENDING_BUYER_INPUT",
                "name": "Pending buyer input",
                "country": "Unknown",
            },
            "input": {},
        }

        self.assertEqual(self.runtime._portfolio_environment(synth), "TEST")
        self.assertEqual(self.runtime._explicit_lifecycle(synth, "TEST"), "TEST")
        self.assertEqual(self.runtime._portfolio_environment(pending), "PLACEHOLDER")
        self.assertEqual(
            self.runtime._explicit_lifecycle(pending, "PLACEHOLDER"),
            "PLACEHOLDER",
        )

    def test_production_runtime_wires_state_hardening_before_base_portfolio_layer(self) -> None:
        mro_names = [cls.__name__ for cls in type(self.runtime).__mro__]
        self.assertIn("V61PortfolioStateHardeningMixin", mro_names)
        self.assertIn("V61PortfolioHardeningMixin", mro_names)
        self.assertLess(
            mro_names.index("V61PortfolioStateHardeningMixin"),
            mro_names.index("V61PortfolioHardeningMixin"),
        )


if __name__ == "__main__":
    unittest.main()
