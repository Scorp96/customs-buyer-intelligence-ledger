from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unified_runtime import UnifiedRuntime


class V61PortfolioHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-portfolio-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")

    @staticmethod
    def observation(account_id: str) -> dict:
        return {
            "claim_key": "identity.legal_entity",
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": account_id,
            "value": {"legal_entity": "Synthetic Fixture LLC"},
            "source": {
                "source_family": "synthetic_registry",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": "https://example.invalid/portfolio/legal",
                "locator": "https://example.invalid/portfolio/legal#entity",
                "raw_excerpt": "Synthetic portfolio legal entity fixture",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT_CONFIRMED",
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": "Synthetic test fixture only; no live-company fact is asserted.",
        }

    def start(self, account_id: str, name: str, country: str, **extra: object) -> dict:
        args = {
            "account": {"account_id": account_id, "country": country, "name": name},
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        }
        args.update(extra)
        return self.runtime.start_investigation(args)

    def test_one_active_investigation_per_canonical_account_and_scope(self) -> None:
        first = self.start("C-PORTFOLIO-001", "Portfolio Production Buyer", "United States")
        second = self.start(
            "C-PORTFOLIO-001",
            "Portfolio Production Buyer",
            "United States",
            resume_existing=False,
        )
        self.assertNotEqual(first["investigation_id"], second["investigation_id"])

        self.runtime.compile_and_append_research_bundle({
            "investigation_id": first["investigation_id"],
            "bundle": {
                "bundle_id": "BUNDLE-PORTFOLIO-MATURITY-001",
                "observations": [self.observation(first["canonical_account_id"])],
            },
        })

        queue = self.runtime.get_portfolio_queue({"limit": 100})
        self.assertEqual(queue["count"], 1)
        self.assertEqual(queue["active_count"], 1)
        self.assertEqual(queue["superseded_count"], 1)
        self.assertEqual(queue["queue"][0]["investigation_id"], first["investigation_id"])
        self.assertEqual(queue["queue"][0]["lifecycle"], "ACTIVE")
        group = queue["canonical_duplicate_groups"][
            f"{first['canonical_account_id']}::DEFAULT"
        ]
        self.assertEqual(set(group), {first["investigation_id"], second["investigation_id"]})

        expanded = self.runtime.get_portfolio_queue({
            "limit": 100,
            "include_non_active": True,
            "include_non_production": True,
        })
        rows = {row["investigation_id"]: row for row in expanded["queue"]}
        self.assertEqual(rows[first["investigation_id"]]["lifecycle"], "ACTIVE")
        self.assertEqual(rows[second["investigation_id"]]["lifecycle"], "SUPERSEDED")
        self.assertEqual(
            rows[second["investigation_id"]]["superseded_by"],
            first["investigation_id"],
        )

        resumed = self.runtime.resume_investigation({
            "investigation_id": second["investigation_id"],
        })
        self.assertEqual(resumed["portfolio_priority"]["lifecycle"], "SUPERSEDED")
        self.assertEqual(
            resumed["last_safe_state"]["portfolio_priority"]["superseded_by"],
            first["investigation_id"],
        )

    def test_case_variant_account_ids_share_one_active_portfolio_identity(self) -> None:
        first_id = "INV-20260829T010000Z-aaaaaaaaaaaa"
        second_id = "INV-20260829T010001Z-bbbbbbbbbbbb"
        for investigation_id in (first_id, second_id):
            (self.runtime.store.root / f"{investigation_id}.jsonl").touch()

        rows = {
            first_id: {
                "investigation_id": first_id,
                "account_id": "pending_target_account",
                "account_name": "Pending buyer target",
                "investigation_scope": "DEFAULT",
                "canonical_scope_key": "pending_target_account::DEFAULT",
                "environment": "PRODUCTION",
                "lifecycle": "ACTIVE",
                "commercial_value_grade": "NQ",
                "research_confidence": "D",
                "decision_saturation": "NOT_SATURATED",
                "next_eiv": 0.0,
                "budget": {},
                "observation_count": 0,
                "peer_count": 0,
                "event_count": 1,
                "last_safe_seq": 1,
                "last_safe_event_hash": "a" * 64,
            },
            second_id: {
                "investigation_id": second_id,
                "account_id": "PENDING_TARGET_ACCOUNT",
                "account_name": "Pending target buyer",
                "investigation_scope": "default",
                "canonical_scope_key": "PENDING_TARGET_ACCOUNT::default",
                "environment": "PRODUCTION",
                "lifecycle": "ACTIVE",
                "commercial_value_grade": "NQ",
                "research_confidence": "D",
                "decision_saturation": "NOT_SATURATED",
                "next_eiv": 0.0,
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

        self.assertEqual(queue["count"], 1)
        self.assertEqual(queue["active_count"], 1)
        self.assertEqual(queue["superseded_count"], 1)
        self.assertEqual(queue["queue"][0]["investigation_id"], second_id)
        self.assertEqual(len(queue["canonical_duplicate_groups"]), 1)
        duplicate_ids = next(iter(queue["canonical_duplicate_groups"].values()))
        self.assertEqual(set(duplicate_ids), {first_id, second_id})
        self.assertEqual(
            queue["policy"]["identity_grouping"],
            "CASE_INSENSITIVE_ACCOUNT_ID_AND_SCOPE",
        )

    def test_synthetic_and_placeholder_sessions_are_excluded_by_default(self) -> None:
        production = self.start(
            "C-PORTFOLIO-PROD",
            "Portfolio Production Buyer Two",
            "United States",
        )
        test_session = self.start(
            "C-PORTFOLIO-TEST",
            "Synthetic Queue Fixture",
            "Synthetic",
            input={"synthetic": True},
        )
        placeholder = self.start(
            "PENDING_USER_INPUT",
            "pending_user_input",
            "Unknown",
        )
        pending_target = self.start(
            "PENDING_TARGET_ACCOUNT",
            "Pending target buyer",
            "Unknown",
        )

        queue = self.runtime.get_portfolio_queue({"limit": 100})
        self.assertEqual([row["investigation_id"] for row in queue["queue"]], [production["investigation_id"]])
        self.assertEqual(queue["excluded_non_production_count"], 3)

        expanded = self.runtime.get_portfolio_queue({
            "limit": 100,
            "include_non_active": True,
            "include_non_production": True,
        })
        rows = {row["investigation_id"]: row for row in expanded["queue"]}
        self.assertEqual(rows[test_session["investigation_id"]]["environment"], "TEST")
        self.assertEqual(rows[test_session["investigation_id"]]["lifecycle"], "TEST")
        self.assertEqual(rows[placeholder["investigation_id"]]["environment"], "PLACEHOLDER")
        self.assertEqual(rows[placeholder["investigation_id"]]["lifecycle"], "PLACEHOLDER")
        self.assertEqual(rows[pending_target["investigation_id"]]["environment"], "PLACEHOLDER")
        self.assertEqual(rows[pending_target["investigation_id"]]["lifecycle"], "PLACEHOLDER")


if __name__ == "__main__":
    unittest.main()
