from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


class LegacyEvidenceBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v63-legacy-bridge-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "LEGACY-BUYER-1",
                "country": "Vietnam",
                "name": "Legacy Buyer One",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = started["investigation_id"]

    @staticmethod
    def observation(claim_key: str, suffix: str, value: dict, *, source_type: str = "CUSTOMS") -> dict:
        return {
            "claim_key": claim_key,
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": "LEGACY-BUYER-1",
            "value": value,
            "source": {
                "source_family": source_type,
                "source_type": source_type,
                "reference_type": "PUBLIC_URL",
                "url": f"https://legacy-evidence.invalid/{suffix}",
                "locator": f"https://legacy-evidence.invalid/{suffix}#record",
                "raw_excerpt": f"PVC foam board {suffix}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT_CONFIRMED",
                "observed_at": "2026-09-23T00:00:00Z",
            },
            "boundary": "Legacy v6.1 evidence bridge fixture; no inferred capability or outreach route.",
        }

    def compile(self, rows: list[dict], bundle_id: str = "LEGACY-BRIDGE-BUNDLE") -> None:
        result = self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": bundle_id, "observations": rows},
        })
        self.assertEqual(result["status"], "ACCEPTED")

    def test_legacy_claims_project_to_read_only_product_opportunity(self) -> None:
        self.compile([
            self.observation("product.fit", "product", {"product_profile_id": "PVC", "product_fit": "HIGH"}),
            self.observation("trade.import_activity", "trade", {"product_profile_id": "PVC", "current_import": True}),
            self.observation("commercial.procurement_need", "need", {"product_profile_id": "PVC", "procurement_need": "HIGH"}),
        ])
        session_path = Path(self.runtime.store.root) / f"{self.investigation_id}.jsonl"
        before = hashlib.sha256(session_path.read_bytes()).hexdigest()

        result = self.runtime.get_product_opportunities({"investigation_id": self.investigation_id})

        after = hashlib.sha256(session_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(result["projected_opportunity_count"], 1)
        row = result["opportunities"][0]
        self.assertEqual(row["account_id"], "LEGACY-BUYER-1")
        self.assertEqual(row["product_profile_id"], "PVC")
        self.assertEqual(row["lifecycle_stage"], "DISCOVERED")
        self.assertEqual(row["projection_source"], "V61_LEGACY_EVIDENCE_PROJECTION")
        self.assertTrue(row["projection_read_only"])
        self.assertFalse(row["durable_event_present"])
        self.assertTrue(row["requires_v63_requalification"])
        self.assertTrue(row["product_evidence_ids"])
        self.assertTrue(row["procurement_evidence_ids"])
        self.assertEqual(result["legacy_projection"]["status"], "PROJECTED")

    def test_runtime_contract_declares_bridge_as_read_only_requalification_input(self) -> None:
        bridge = self.runtime.get_runtime_contract({})["demand_expansion_v6_3"]["legacy_evidence_bridge_v6_1"]
        self.assertEqual(bridge["status"], "BOUND_READ_ONLY")
        self.assertTrue(bridge["projection_read_only"])
        self.assertTrue(bridge["requires_v63_requalification"])
        self.assertFalse(bridge["creates_product_opportunity_event"])

    def test_legacy_projection_cannot_be_used_as_durable_mutation_authority(self) -> None:
        self.compile([
            self.observation("product.fit", "product", {"product_profile_id": "PVC"}),
            self.observation("trade.import_activity", "trade", {"product_profile_id": "PVC", "current_import": True}),
        ])
        row = self.runtime.get_product_opportunities({"investigation_id": self.investigation_id})["opportunities"][0]
        with self.assertRaisesRegex(ValueError, "LEGACY_OPPORTUNITY_REQUIRES_V63_REQUALIFICATION"):
            self.runtime.evaluate_product_opportunity({
                "investigation_id": self.investigation_id,
                "opportunity_id": row["opportunity_id"],
                "assessment": {
                    "commercial_value_grade": "B",
                    "commercial_value_score": 65,
                    "commercial_evidence_ids": row["product_evidence_ids"],
                },
            })

        with self.assertRaisesRegex(ValueError, "LEGACY_OPPORTUNITY_REQUIRES_V63_REQUALIFICATION"):
            self.runtime.evaluate_product_opportunity({
                "opportunity": row,
                "assessment": {
                    "commercial_value_grade": "B",
                    "commercial_value_score": 65,
                    "commercial_evidence_ids": row["product_evidence_ids"],
                },
            })

    def test_global_query_includes_eligible_legacy_sessions_as_read_only_rows(self) -> None:
        self.compile([
            self.observation("product.fit", "product", {"product_profile_id": "PVC"}),
            self.observation("trade.import_activity", "trade", {"product_profile_id": "PVC", "current_import": True}),
        ])
        second = self.runtime.start_investigation({
            "account": {
                "account_id": "LEGACY-BUYER-2",
                "country": "Vietnam",
                "name": "Legacy Buyer Two",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        second_id = second["investigation_id"]
        rows = [
            {
                **self.observation("product.fit", "product-2", {"product_profile_id": "PVC"}),
                "owner_id": "LEGACY-BUYER-2",
            },
            {
                **self.observation("trade.import_activity", "trade-2", {"product_profile_id": "PVC", "current_import": True}),
                "owner_id": "LEGACY-BUYER-2",
            },
        ]
        result = self.runtime.compile_and_append_research_bundle({
            "investigation_id": second_id,
            "bundle": {"bundle_id": "LEGACY-BRIDGE-BUNDLE-2", "observations": rows},
        })
        self.assertEqual(result["status"], "ACCEPTED")

        projected = self.runtime.get_product_opportunities({})
        self.assertEqual(projected["projection_scope"], "VISIBLE_PORTFOLIO_QUERY")
        self.assertGreaterEqual(projected["projected_opportunity_count"], 2)
        self.assertTrue(all(row["projection_read_only"] for row in projected["opportunities"]))

    def test_missing_direct_procurement_is_reported_without_projecting_opportunity(self) -> None:
        self.compile([
            self.observation("product.fit", "product", {"product_profile_id": "PVC"}),
            self.observation("commercial.procurement_need", "web-need", {"product_profile_id": "PVC"}, source_type="PUBLIC_WEB"),
        ])
        result = self.runtime.get_product_opportunities({"investigation_id": self.investigation_id})
        self.assertEqual(result["projected_opportunity_count"], 0)
        self.assertEqual(result["legacy_projection"]["status"], "BLOCKED")
        self.assertIn("LEGACY_DIRECT_PROCUREMENT_EVIDENCE_MISSING", result["legacy_projection"]["blockers"])

    def test_similar_customs_directory_label_does_not_prove_direct_procurement(self) -> None:
        self.compile([
            self.observation("product.fit", "product", {"product_profile_id": "PVC"}),
            self.observation(
                "trade.import_activity",
                "broker-directory",
                {"product_profile_id": "PVC", "current_import": True},
                source_type="CUSTOMS_BROKER_DIRECTORY",
            ),
        ])
        result = self.runtime.get_product_opportunities({"investigation_id": self.investigation_id})
        self.assertEqual(result["projected_opportunity_count"], 0)
        self.assertEqual(result["legacy_projection"]["status"], "BLOCKED")
        self.assertIn("LEGACY_DIRECT_PROCUREMENT_EVIDENCE_MISSING", result["legacy_projection"]["blockers"])


if __name__ == "__main__":
    unittest.main()
