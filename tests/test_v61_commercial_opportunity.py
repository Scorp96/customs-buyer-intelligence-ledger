from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_runtime import COMMERCIAL_OPPORTUNITY_FACTORS, UnifiedRuntime


class V61CommercialOpportunityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-commercial-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-COMM-SYNTH",
                "country": "United States",
                "name": "Synthetic Commercial Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = started["investigation_id"]

    @staticmethod
    def observation(claim_key: str, suffix: str, value: dict) -> dict:
        return {
            "claim_key": claim_key,
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": "C-COMM-SYNTH",
            "value": value,
            "source": {
                "source_family": "synthetic_commercial_evidence",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": f"https://commercial-evidence.invalid/{suffix}",
                "locator": f"https://commercial-evidence.invalid/{suffix}#record",
                "raw_excerpt": f"Synthetic commercial opportunity fixture {suffix}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT_CONFIRMED",
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": (
                "Synthetic commercial opportunity fixture only; every numeric "
                "factor is explicitly carried by this Evidence value."
            ),
        }

    def compile(self, rows: list[dict], bundle_id: str) -> None:
        result = self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": bundle_id, "observations": rows},
        })
        self.assertIn(result["status"], {"ACCEPTED", "PARTIAL_SUCCESS"})

    def core_rows(self, rich_trade: bool = True) -> list[dict]:
        trade_value = {
            "current_import": True,
        }
        if rich_trade:
            trade_value.update({
                "annualized_visible_weight_kg": 620000,
                "shipment_count_12m": 14,
                "suppliers": [
                    "Supplier Alpha",
                    "Supplier Beta",
                    "Supplier Gamma",
                    "Supplier Delta",
                ],
                "growth_rate": 0.18,
                "market_position": "LARGE",
                "strategic_fit": "HIGH",
                "replacement_opportunity": "HIGH",
                "latest_import_date": "2026-08-20",
            })
        return [
            self.observation("identity.legal_entity", "identity", {"legal_entity": "Synthetic Commercial Buyer LLC"}),
            self.observation("identity.ultimate_buyer", "ultimate", {"ultimate_buyer": "Synthetic Commercial Buyer LLC"}),
            self.observation("product.fit", "product", {"product_fit": "HIGH", "product_category": "PVC_FOAM_BOARD"}),
            self.observation("trade.import_activity", "trade", trade_value),
            self.observation("company.operating_status", "operating", {"operating_status": "ACTIVE"}),
            self.observation("commercial.procurement_need", "need", {"procurement_need": "HIGH"}),
            self.observation("relationship.supply_chain", "relationship", {"relationship": "CURRENT_SUPPLIER"}),
        ]

    def test_contract_exposes_all_ten_spec_factors(self) -> None:
        contract = self.runtime.get_runtime_contract({})
        commercial = contract["commercial_opportunity_v6_1"]
        self.assertEqual(set(commercial["factors"]), set(COMMERCIAL_OPPORTUNITY_FACTORS))
        self.assertFalse(commercial["contact_or_crm_caps_grade"])
        self.assertFalse(commercial["single_shipment_implies_growth"])
        self.assertEqual(commercial["model"], "EVIDENCE_BOUND_HEURISTIC_V1")

    def test_large_current_multi_supplier_buyer_can_be_a_plus_without_named_buyer_or_crm(self) -> None:
        rows = self.core_rows(rich_trade=True)
        rows.append(
            self.observation(
                "contact.company_route",
                "company-route",
                {
                    "channel": "PHONE",
                    "value": "+1 555 010 9876",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": False,
                },
            )
        )
        self.compile(rows, "BUNDLE-COMM-RICH-BUYER")

        value = self.runtime.evaluate_commercial_value({
            "investigation_id": self.investigation_id,
        })
        account = self.runtime.get_account_state({
            "investigation_id": self.investigation_id,
        })

        self.assertEqual(value["commercial_value_grade"], "A+")
        self.assertGreater(value["score"], value["baseline_claim_score"])
        self.assertGreaterEqual(value["opportunity_factors"]["volume"]["strength"], 0.9)
        self.assertGreaterEqual(value["opportunity_factors"]["frequency"]["strength"], 1.0)
        self.assertEqual(value["opportunity_factors"]["supplier_diversity"]["strength"], 1.0)
        self.assertEqual(value["opportunity_factors"]["growth"]["status"], "SUPPORTED")
        self.assertNotIn("buying_group.decision_chain", [
            row["claim_key"]
            for row in value["basis"]
            if row["claim_state"] in {"SUPPORTED", "STRONGLY_SUPPORTED"}
        ])
        self.assertEqual(account["crm_sync"], "NOT_REQUESTED")
        self.assertEqual(account["crm_state"]["status"], "NOT_SYNCED")
        self.assertEqual(account["outreach_readiness"]["outreach_readiness"], "COMPANY_ROUTE_READY")
        self.assertFalse(value["contact_or_crm_caps_grade"])

    def test_unknown_opportunity_factors_are_unknown_not_fabricated_negative_facts(self) -> None:
        self.compile(self.core_rows(rich_trade=False), "BUNDLE-COMM-UNKNOWN-FACTORS")
        value = self.runtime.evaluate_commercial_value({
            "investigation_id": self.investigation_id,
        })
        self.assertEqual(value["opportunity_factors"]["growth"]["status"], "UNKNOWN")
        self.assertIsNone(value["opportunity_factors"]["growth"]["strength"])
        self.assertIn("growth", value["unknown_opportunity_factors"])
        self.assertFalse(value["unknown_factors_are_fabricated_zero_facts"])
        self.assertGreaterEqual(value["score"], value["baseline_claim_score"])

    def test_single_shipment_does_not_invent_growth(self) -> None:
        self.compile(
            [
                self.observation("product.fit", "single-product", {"product_fit": "HIGH"}),
                self.observation(
                    "trade.import_activity",
                    "single-trade",
                    {
                        "shipment_count": 1,
                        "total_weight_kg": 9000,
                        "latest_import_date": "2026-08-18",
                    },
                ),
            ],
            "BUNDLE-COMM-SINGLE-SHIPMENT",
        )
        value = self.runtime.evaluate_commercial_value({
            "investigation_id": self.investigation_id,
        })
        self.assertEqual(value["opportunity_factors"]["frequency"]["status"], "SUPPORTED")
        self.assertEqual(value["opportunity_factors"]["growth"]["status"], "UNKNOWN")
        self.assertEqual(value["opportunity_factors"]["growth"]["score_contribution"], 0.0)

    def test_factor_lineage_is_bound_to_compiled_observation_and_evidence_ids(self) -> None:
        self.compile(self.core_rows(rich_trade=True), "BUNDLE-COMM-LINEAGE")
        value = self.runtime.evaluate_commercial_value({
            "investigation_id": self.investigation_id,
        })
        for name in ("volume", "frequency", "supplier_diversity", "recency", "growth"):
            factor = value["opportunity_factors"][name]
            self.assertEqual(factor["status"], "SUPPORTED")
            self.assertTrue(factor["observation_ids"], name)
            self.assertTrue(factor["evidence_ids"], name)
            self.assertTrue(factor["evidence_paths"], name)


if __name__ == "__main__":
    unittest.main()
