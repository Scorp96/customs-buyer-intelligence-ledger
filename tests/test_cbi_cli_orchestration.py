from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unified_runtime import UnifiedRuntime


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "cbi.py"


class CbiCliOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-cli-orchestration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session_root = self.root / "sessions"
        self.input_path = self.root / "synthetic-customs.json"
        self.input_record = {
            "date": "2026-08-17",
            "master_bill": "SYNTH-MBL-001",
            "house_bill": "SYNTH-HBL-001",
            "supplier": "Synthetic Export Supplier Ltd",
            "supplier_address": "1 Synthetic Export Road",
            "buyer": "Synthetic Import Buyer LLC",
            "buyer_address": "100 Synthetic Buyer Avenue",
            "buyer_country": "United States",
            "quantity": "16 PKG",
            "weight_kg": 23820,
            "teu": 2,
            "product": "Synthetic PVC Foam Sheet",
            "origin": "Synthetic Origin",
            "origin_port": "Synthetic Port",
            "destination": "United States",
            "destination_port": "Synthetic US Port",
            "container": "SYNTH0000001",
            "Bill Type": "House Bill",
            "Update Date": "20260818",
            "opaque_source_field": "Synthetic Marker",
        }
        self.input_path.write_text(
            json.dumps(self.input_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_cli(self, *arguments: str) -> tuple[int, dict]:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                "-Xutf8",
                str(CLI),
                "--session-root",
                str(self.session_root),
                *arguments,
            ],
            cwd=str(ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"CLI did not emit one JSON document. rc={proc.returncode} "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ) from exc
        return proc.returncode, payload

    def test_lookup_is_read_only_host_handoff(self) -> None:
        code, payload = self.run_cli("lookup", str(self.input_path))
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "cbi.cli-host-handoff.v1")
        self.assertEqual(payload["mode"], "ANSWER_FIRST")
        self.assertFalse(payload["runtime_persistence_requested"])
        self.assertTrue(payload["host_execution_required"])
        self.assertEqual(payload["buyer"], "Synthetic Import Buyer LLC")
        self.assertTrue(payload["raw_input_preserved"])
        self.assertEqual(
            payload["raw_customs_record"]["opaque_source_field"],
            "Synthetic Marker",
        )
        self.assertEqual(
            payload["normalized_customs_record"]["bill_type"],
            "House Bill",
        )
        self.assertNotIn(
            "opaque_source_field",
            payload["normalized_customs_record"],
        )
        self.assertFalse(self.session_root.exists())

    def test_audit_preview_is_read_only(self) -> None:
        code, payload = self.run_cli("audit-file", str(self.input_path))
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "cbi.cli-audit-preview.v1")
        self.assertEqual(payload["status"], "PREVIEW")
        self.assertFalse(payload["runtime_mutation_performed"])
        self.assertTrue(payload["raw_input_preserved"])
        self.assertGreater(
            payload["raw_flattened_field_count"],
            payload["normalized_field_count"],
        )
        self.assertEqual(
            payload["raw_customs_record"]["opaque_source_field"],
            "Synthetic Marker",
        )
        self.assertEqual(
            payload["normalized_customs_record"]["update_date"],
            "20260818",
        )
        self.assertEqual(
            payload["proposed_initial_claims"],
            ["trade.import_activity", "relationship.supply_chain"],
        )
        self.assertFalse(self.session_root.exists())

    def test_audit_commit_uses_production_wal_and_is_idempotent(self) -> None:
        code, first = self.run_cli(
            "audit-file",
            str(self.input_path),
            "--priority-grade",
            "A",
            "--commit",
        )
        self.assertEqual(code, 0, first)
        self.assertEqual(first["status"], "AUDIT_BOOTSTRAPPED")
        self.assertEqual(first["mutation_path"], "V6_1_PRODUCTION_MCP_WAL")
        self.assertTrue(first["runtime_mutation_performed"])
        self.assertTrue(first["raw_input_preserved"])
        self.assertFalse(first["decision_saturation"]["decision_saturated"])
        self.assertFalse(first["crm_writeback_performed"])
        self.assertFalse(first["outreach_send_performed"])

        investigation_id = first["investigation_id"]
        runtime = UnifiedRuntime(self.session_root)
        state = runtime._v6_state(investigation_id)
        self.assertEqual(len(state["observations"]), 2)
        self.assertEqual(
            {row["claim_key"] for row in state["observations"].values()},
            {"trade.import_activity", "relationship.supply_chain"},
        )
        self.assertTrue(
            all(
                row["source"]["authority_level"]
                == "D1_USER_SUPPLIED_UNVERIFIED"
                for row in state["observations"].values()
            )
        )
        trade_observation = next(
            row
            for row in state["observations"].values()
            if row["claim_key"] == "trade.import_activity"
        )
        self.assertEqual(
            trade_observation["source"]["raw_content"]["raw_input"][
                "opaque_source_field"
            ],
            "Synthetic Marker",
        )
        self.assertEqual(
            trade_observation["source"]["raw_content"]["normalized"][
                "bill_type"
            ],
            "House Bill",
        )
        self.assertEqual(
            trade_observation["value"]["customs_record"]["raw_input"][
                "opaque_source_field"
            ],
            "Synthetic Marker",
        )
        self.assertEqual(
            trade_observation["value"]["customs_record"]["normalized"][
                "update_date"
            ],
            "20260818",
        )
        claims = runtime.get_claims({"investigation_id": investigation_id})[
            "claims"
        ]
        self.assertEqual(claims["identity.ultimate_buyer"]["state"], "UNSEEN")
        self.assertEqual(claims["product.fit"]["state"], "UNSEEN")

        code, second = self.run_cli(
            "audit-file",
            str(self.input_path),
            "--priority-grade",
            "A",
            "--commit",
        )
        self.assertEqual(code, 0, second)
        self.assertEqual(second["investigation_id"], investigation_id)
        self.assertTrue(
            second["investigation_start"]["mutation_meta"]["replayed"]
        )
        self.assertTrue(
            second["customs_evidence_compilation"]["mutation_meta"]["replayed"]
        )
        replay_state = runtime._v6_state(investigation_id)
        self.assertEqual(len(replay_state["observations"]), 2)

    def test_batch_preview_never_persists(self) -> None:
        batch_path = self.root / "synthetic-batch.json"
        second = {
            **self.input_record,
            "master_bill": "SYNTH-MBL-002",
            "house_bill": "SYNTH-HBL-002",
            "buyer": "Synthetic Import Buyer Two LLC",
            "buyer_address": "200 Synthetic Buyer Avenue",
            "opaque_source_field": "Synthetic Marker Two",
        }
        batch_path.write_text(
            json.dumps([self.input_record, second], ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        code, payload = self.run_cli("batch-audit", str(batch_path))
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PREVIEW")
        self.assertEqual(payload["record_count"], 2)
        self.assertFalse(payload["runtime_mutation_performed"])
        self.assertTrue(
            all(row["raw_input_preserved"] for row in payload["records"])
        )
        self.assertEqual(
            payload["records"][1]["raw_customs_record"]["opaque_source_field"],
            "Synthetic Marker Two",
        )
        self.assertFalse(self.session_root.exists())

    def test_invalid_input_fails_closed_before_runtime_write(self) -> None:
        invalid_path = self.root / "invalid.json"
        invalid_path.write_text(
            json.dumps({"product": "Synthetic Sheet"}) + "\n",
            encoding="utf-8",
        )
        code, payload = self.run_cli(
            "audit-file",
            str(invalid_path),
            "--commit",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "ERROR")
        self.assertIn("requires buyer", payload["error"])
        self.assertFalse(self.session_root.exists())


if __name__ == "__main__":
    unittest.main()
