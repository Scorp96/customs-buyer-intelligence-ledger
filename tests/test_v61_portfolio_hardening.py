from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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

        queue = self.runtime.get_portfolio_queue({"limit": 100})
        self.assertEqual([row["investigation_id"] for row in queue["queue"]], [production["investigation_id"]])
        self.assertEqual(queue["excluded_non_production_count"], 2)

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


if __name__ == "__main__":
    unittest.main()
