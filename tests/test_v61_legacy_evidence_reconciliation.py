from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from unified_runtime import CBI_MCP_TOOL_NAMES, UnifiedRuntime, ValidationError


class V61LegacyEvidenceReconciliationTests(unittest.TestCase):
    BOUNDARY = (
        "Visible PVC shipment weights: 10,000 kg; 20,000 kg; 30,000 kg; "
        "40,000 kg; 50,000 kg. Sum=150,000 kg. Visible records only; "
        "no annualization."
    )
    CONTENT_SHA = "a" * 64

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-legacy-quant-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = UnifiedRuntime(Path(self.temp.name) / "sessions")
        started = self.runtime.start_investigation({
            "account": {
                "account_id": "C-LEGACY-QUANT-001",
                "country": "United States",
                "name": "Legacy Quantitative Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        self.investigation_id = started["investigation_id"]
        self.account_id = started["canonical_account_id"]
        self.evidence_id = "E-LEGACY-QUANT-001"
        self.append_legacy_evidence(
            evidence_id=self.evidence_id,
            owner_type="ACCOUNT",
            owner_id=self.account_id,
            boundary=self.BOUNDARY,
        )

    def append_legacy_evidence(
        self,
        *,
        evidence_id: str,
        owner_type: str,
        owner_id: str,
        boundary: str,
    ) -> None:
        attempt_id = f"ATT-{evidence_id}"
        self.runtime.store.append(
            self.investigation_id,
            "EXECUTION_RECEIPT_APPENDED",
            {
                "attempt": {
                    "attempt_id": attempt_id,
                    "execution_id": f"EXEC-{evidence_id}",
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "module_or_branch": "customs_integrity",
                    "source_family": "customs_math",
                    "result": "POSITIVE",
                    "result_count": 5,
                    "evidence_ids": [evidence_id],
                    "discovered_peer_ids": [],
                    "relationship_evidence_ids": {},
                },
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "claim_key": "LEGACY_OBSERVED_WEIGHT_PROFILE",
                        "module_or_branch": "customs_integrity",
                        "source_family": "customs_math",
                        "source_type": "customs_math",
                        "reference_type": "PUBLIC_URL",
                        "url": "https://trade-evidence.invalid/legacy-quant",
                        "locator": "https://trade-evidence.invalid/legacy-quant",
                        "observed_at": "2026-08-28T00:00:00Z",
                        "freshness": "CURRENT",
                        "evidence_grade": "B1",
                        "content_sha256": self.CONTENT_SHA,
                        "boundary": boundary,
                    }
                ],
                "pivots_generated": [],
                "pivots_consumed": [],
                "manual_visual_items_resolved": [],
            },
        )

    def args(
        self,
        *,
        evidence_id: str | None = None,
        expected_content_sha: str | None = None,
        components: list[dict] | None = None,
        expected_total: int | float = 150000,
        total_proof_literal: str = "Sum=150,000 kg",
        metric: str = "visible_weight_kg",
        annualized: bool = False,
        owner_boundary: str | None = None,
    ) -> dict:
        evidence_id = evidence_id or self.evidence_id
        boundary = owner_boundary or self.BOUNDARY
        tail = self.runtime.store.read(self.investigation_id)[-1]["event_hash"]
        return {
            "investigation_id": self.investigation_id,
            "reconciliation": {
                "legacy_evidence_id": evidence_id,
                "expected_provenance": {
                    "claim_key": "LEGACY_OBSERVED_WEIGHT_PROFILE",
                    "module_or_branch": "customs_integrity",
                    "source_family": "customs_math",
                    "source_type": "customs_math",
                    "reference_type": "PUBLIC_URL",
                    "url": "https://trade-evidence.invalid/legacy-quant",
                    "locator": "https://trade-evidence.invalid/legacy-quant",
                    "content_sha256": expected_content_sha or self.CONTENT_SHA,
                    "observed_at": "2026-08-28T00:00:00Z",
                    "freshness": "CURRENT",
                },
                "expected_boundary_sha256": hashlib.sha256(
                    boundary.encode("utf-8")
                ).hexdigest(),
                "expected_pre_reconciliation_tail_event_hash": tail,
                "target_claim_key": "trade.import_activity",
                "metric": metric,
                "aggregation": "SUM",
                "components": components
                or [
                    {"value": 10000, "proof_literal": "10,000 kg"},
                    {"value": 20000, "proof_literal": "20,000 kg"},
                    {"value": 30000, "proof_literal": "30,000 kg"},
                    {"value": 40000, "proof_literal": "40,000 kg"},
                    {"value": 50000, "proof_literal": "50,000 kg"},
                ],
                "expected_total": expected_total,
                "total_proof_literal": total_proof_literal,
                "annualized": annualized,
            },
        }

    def test_exact_observed_sum_projects_structured_volume_and_is_idempotent(self) -> None:
        first_args = self.args()
        before_count = len(self.runtime.store.read(self.investigation_id))
        result = self.runtime.reconcile_legacy_quantitative_evidence(first_args)
        self.assertEqual(result["status"], "RECONCILED")
        self.assertTrue(result["mutation_performed"])
        self.assertEqual(
            result["plan"]["expected_total"],
            150000,
        )

        state = self.runtime._v6_state(self.investigation_id)
        rows = [
            row
            for row in state["observations"].values()
            if isinstance(row.get("value"), dict)
            and row["value"].get("legacy_reconciliation", {}).get(
                "legacy_evidence_id"
            )
            == self.evidence_id
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"]["visible_weight_kg"], 150000)
        self.assertFalse(rows[0]["value"]["legacy_reconciliation"]["annualized"])
        self.assertNotIn("annualized_visible_weight_kg", rows[0]["value"])

        commercial = self.runtime.evaluate_commercial_value({
            "investigation_id": self.investigation_id
        })
        volume = commercial["opportunity_factors"]["volume"]
        self.assertEqual(volume["status"], "SUPPORTED")
        self.assertGreaterEqual(volume["strength"], 0.8)
        self.assertIn("visible_weight_kg", volume["evidence_paths"])

        second = self.runtime.reconcile_legacy_quantitative_evidence(first_args)
        self.assertEqual(second["status"], "ALREADY_RECONCILED")
        self.assertTrue(second["idempotent_replay"])
        self.assertFalse(second["mutation_performed"])
        self.assertEqual(
            len(self.runtime.store.read(self.investigation_id)),
            before_count + 2,
        )

    def test_preview_validates_without_mutation(self) -> None:
        arguments = self.args()
        arguments["preview_only"] = True
        before = len(self.runtime.store.read(self.investigation_id))
        result = self.runtime.reconcile_legacy_quantitative_evidence(arguments)
        self.assertEqual(result["status"], "PREVIEW_VALIDATED")
        self.assertFalse(result["mutation_performed"])
        self.assertEqual(
            result["planned_observation"]["value"]["visible_weight_kg"],
            150000,
        )
        self.assertEqual(len(self.runtime.store.read(self.investigation_id)), before)

    def test_wrong_content_sha_fails_before_append(self) -> None:
        before = len(self.runtime.store.read(self.investigation_id))
        with self.assertRaises(ValidationError):
            self.runtime.reconcile_legacy_quantitative_evidence(
                self.args(expected_content_sha="b" * 64)
            )
        self.assertEqual(len(self.runtime.store.read(self.investigation_id)), before)

    def test_missing_component_proof_literal_fails_before_append(self) -> None:
        components = [
            {"value": 150000, "proof_literal": "150000 kilograms exactly"},
        ]
        before = len(self.runtime.store.read(self.investigation_id))
        with self.assertRaises(ValidationError):
            self.runtime.reconcile_legacy_quantitative_evidence(
                self.args(components=components)
            )
        self.assertEqual(len(self.runtime.store.read(self.investigation_id)), before)

    def test_arithmetic_mismatch_fails_before_append(self) -> None:
        before = len(self.runtime.store.read(self.investigation_id))
        with self.assertRaises(ValidationError):
            self.runtime.reconcile_legacy_quantitative_evidence(
                self.args(expected_total=150001)
            )
        self.assertEqual(len(self.runtime.store.read(self.investigation_id)), before)

    def test_annualized_metric_is_rejected(self) -> None:
        before = len(self.runtime.store.read(self.investigation_id))
        with self.assertRaises(ValidationError):
            self.runtime.reconcile_legacy_quantitative_evidence(
                self.args(
                    metric="annualized_visible_weight_kg",
                    annualized=True,
                )
            )
        self.assertEqual(len(self.runtime.store.read(self.investigation_id)), before)

    def test_peer_owned_legacy_evidence_is_rejected(self) -> None:
        peer_evidence_id = "E-LEGACY-QUANT-PEER-001"
        self.append_legacy_evidence(
            evidence_id=peer_evidence_id,
            owner_type="PEER",
            owner_id="PEER-SYNTH-001",
            boundary=self.BOUNDARY,
        )
        before = len(self.runtime.store.read(self.investigation_id))
        with self.assertRaises(ValidationError):
            self.runtime.reconcile_legacy_quantitative_evidence(
                self.args(evidence_id=peer_evidence_id)
            )
        self.assertEqual(len(self.runtime.store.read(self.investigation_id)), before)

    def test_contract_exposes_admin_boundary_but_mcp_does_not(self) -> None:
        contract = self.runtime.get_runtime_contract({})
        section = contract["legacy_evidence_reconciliation_v6_1"]
        self.assertFalse(section["ordinary_mcp_tool_exposed"])
        self.assertTrue(section["administrative_direct_runtime_only"])
        self.assertFalse(section["annualization_allowed"])
        self.assertTrue(section["runtime_recomputes_sum"])
        self.assertNotIn(
            "reconcile_legacy_quantitative_evidence",
            CBI_MCP_TOOL_NAMES,
        )


if __name__ == "__main__":
    unittest.main()
