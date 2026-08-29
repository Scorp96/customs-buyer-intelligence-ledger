from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

try:
    from .test_unified_runtime import RuntimeHarness, sha
except ImportError:  # Direct script execution compatibility.
    from test_unified_runtime import RuntimeHarness, sha
from unified_runtime.core import UnifiedRuntime, ValidationError


class V54ResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cbi_v54_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def harness(self) -> RuntimeHarness:
        return RuntimeHarness(self.root)

    def assert_rejected(self, callback, fragment: str) -> None:
        with self.assertRaises(ValidationError) as caught:
            callback()
        self.assertIn(fragment, str(caught.exception))

    @staticmethod
    def information_record(harness: RuntimeHarness, information_id: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        content_hash = sha(f"pending:{information_id}")
        return {
            "information_id": information_id,
            "investigation_id": harness.investigation_id,
            "related_account_id": "ACCT-SYNTH-001",
            "subject_type": "ACCOUNT",
            "subject_owner_id": "ACCT-SYNTH-001",
            "relationship_to_account": "SELF",
            "information_type": "FACT",
            "claim_key": f"pending.{information_id}",
            "value": {"field": "synthetic", "value": "pending journal proof"},
            "source_type": "USER_INPUT",
            "source_reference_type": "USER_INPUT",
            "source_url": "",
            "source_locator": "user-input://synthetic/pending-proof",
            "observed_at": now,
            "content_sha256": content_hash,
            "confidence": "HIGH",
            "temporal_status": "CURRENT",
            "route_scope": "NOT_A_ROUTE",
            "outreach_eligible_claimed": False,
            "supersedes_information_ids": [],
            "conflicts_with_information_ids": [],
            "evidence_ids": [],
            "notes": "Synthetic resilience test only.",
        }

    def test_01_contract_is_self_describing(self):
        runtime = UnifiedRuntime(self.root)
        contract = runtime.get_runtime_contract({})
        self.assertEqual(contract["runtime_version"], "5.4.1")
        self.assertIn("NEGATIVE_EXHAUSTED", contract["enums"]["source_family_terminal_result"])
        self.assertIn("PARTY_ROLE", contract["enums"]["information_type"])
        self.assertIn("source_attempt", contract["required_fields"])
        self.assertEqual(contract["network_policy_defaults"]["closure_strategy"], "QUEUE_PIVOT_SATURATION")
        self.assertFalse(contract["network_saturation_policy"]["fixed_depth_or_anchor_count_closes_research"])
        self.assertEqual(contract["crm_writeback_boundary"]["structured_receipt_tool"], "append_crm_writeback_receipt")
        self.assertTrue(contract["transport_boundary"]["local_runtime_health_is_not_tunnel_health"])
        workflow = contract["workflow_policy"]
        self.assertEqual(workflow["default_mode"], "ANSWER_FIRST")
        self.assertEqual(workflow["answer_first"]["cbi_mcp_tools_allowed"], [])
        self.assertEqual(len(workflow["answer_first"]["cbi_mcp_tools_forbidden"]), 19)
        self.assertFalse(workflow["mcp_initialize_mutates_state"])
        self.assertTrue(workflow["pending_sync_requires_explicit_tool_call"])

    def test_02_canonical_resolver_normalizes_nfc_and_start_is_idempotent(self):
        runtime = UnifiedRuntime(self.root)
        decomposed = unicodedata.normalize("NFD", "Công ty Tưởng")
        first = runtime.resolve_or_create_account({
            "candidate": {"name": decomposed, "country": "Việt Nam"},
        })
        self.assertEqual(first["status"], "CREATED")
        self.assertEqual(first["input_sanitization"]["status"], "NORMALIZED_UNICODE_NFC")
        second = runtime.resolve_or_create_account({
            "candidate": {"name": "Công ty Tưởng", "country": "Việt Nam"},
            "create_if_missing": False,
        })
        self.assertEqual(second["status"], "MATCHED")
        self.assertEqual(second["match"]["account_id"], first["match"]["account_id"])
        args = {
            "account": {"name": "Công ty Tưởng", "country": "Việt Nam"},
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "idempotency_key": "TEST-IDEMPOTENCY-001",
        }
        started = runtime.start_investigation(args)
        resumed = runtime.start_investigation(args)
        self.assertEqual(started["investigation_id"], resumed["investigation_id"])
        self.assertTrue(resumed["resumed_existing"])

    def test_03_negative_is_intermediate_but_negative_exhausted_closes_family(self):
        h = self.harness()
        h.add_attempt("company_profile", "official_home", result="NEGATIVE")
        first = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        detail = first["modules"]["company_profile"]
        self.assertIn("official_home", detail["negative_not_exhausted"])
        h.add_attempt("company_profile", "official_home", result="NEGATIVE_EXHAUSTED")
        second = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertNotIn("official_home", second["modules"]["company_profile"]["negative_not_exhausted"])

    def test_04_not_applicable_justified_is_terminal_and_403_is_not(self):
        h = self.harness()
        h.add_attempt(
            "contact_coverage",
            "zalo_public",
            result="NOT_APPLICABLE_JUSTIFIED",
            blocked_reason="United States account; Zalo is not a generally applicable public business channel for this market.",
        )
        state = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertEqual(
            state["modules"]["contact_coverage"]["family_results"]["zalo_public"],
            "NOT_APPLICABLE_JUSTIFIED",
        )
        self.assert_rejected(
            lambda: h.add_attempt(
                "contact_coverage",
                "whatsapp_public",
                result="NOT_APPLICABLE_JUSTIFIED",
                blocked_reason="United States source returned 403 and login required.",
            ),
            "cannot be marked NOT_APPLICABLE",
        )

    def test_05_research_network_crm_and_outreach_states_are_decoupled(self):
        h = self.harness()
        closure, _ = h.complete_account(operational_positive=False)
        self.assertTrue(closure["closed"])
        self.assertEqual(closure["closed_scope"], "RESEARCH_AND_NETWORK")
        self.assertTrue(closure["research_complete"])
        self.assertTrue(closure["network_complete"])
        self.assertFalse(closure["crm_sync_complete"])
        self.assertFalse(closure["outreach_ready"])
        self.assertIn("CRM_SYNC_INCOMPLETE", closure["operational_blockers"])

    def test_06_pending_journal_replays_and_deduplicates_request_hash(self):
        h = self.harness()
        payload = {
            "investigation_id": h.investigation_id,
            "record": self.information_record(h, "INFO-PENDING-001"),
        }
        first = h.runtime.queue_pending_receipt({
            "target_tool": "append_information_record",
            "payload": payload,
        })
        duplicate = h.runtime.queue_pending_receipt({
            "target_tool": "append_information_record",
            "payload": copy.deepcopy(payload),
        })
        self.assertTrue(first["queued"])
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(first["journal_id"], duplicate["journal_id"])
        dry_run = h.runtime.sync_pending_receipts({"dry_run": True})
        self.assertEqual(dry_run["counts"], {"WOULD_SYNC": 1})
        synced = h.runtime.sync_pending_receipts({})
        self.assertEqual(synced["counts"], {"SYNCED": 1})
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(history["records"][0]["information_id"], "INFO-PENDING-001")

    def test_07_pending_replay_only_deduplicates_proven_equivalent_receipt(self):
        h = self.harness()
        payload = {
            "investigation_id": h.investigation_id,
            "record": self.information_record(h, "INFO-PENDING-002"),
        }
        h.runtime.append_information_record(payload)
        h.runtime.queue_pending_receipt({
            "target_tool": "append_information_record",
            "payload": payload,
        })
        synced = h.runtime.sync_pending_receipts({})
        self.assertEqual(synced["counts"], {"DEDUPLICATED": 1})

    def test_08_pending_payload_tamper_is_rejected(self):
        h = self.harness()
        payload = {
            "investigation_id": h.investigation_id,
            "record": self.information_record(h, "INFO-PENDING-003"),
        }
        queued = h.runtime.queue_pending_receipt({
            "target_tool": "append_information_record",
            "payload": payload,
        })
        path = Path(queued["path"])
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["record"]["notes"] = "tampered"
        path.write_text(json.dumps(envelope, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assert_rejected(lambda: h.runtime.sync_pending_receipts({}), "hash mismatch")

    def test_09_health_reports_local_not_tunnel_scope(self):
        h = self.harness()
        health = h.runtime.get_runtime_health({"investigation_id": h.investigation_id})
        self.assertEqual(health["status"], "READY")
        self.assertTrue(health["local_runtime"])
        self.assertFalse(health["tunnel_reachability_proven"])
        self.assertEqual(health["checked_sessions"], 1)
        self.assertEqual(health["canonical_metrics"]["unique_accounts_loaded"], health["canonical_accounts"])
        self.assertFalse(health["canonical_metrics"]["proves_external_production_crm_total"])

    def test_10_legacy_network_budgets_are_hints_and_quality_gates_stay_strict(self):
        runtime = UnifiedRuntime(self.root)
        base = {
            "account": {"account_id": "NETWORK-POLICY-SYNTH", "country": "Canada"},
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "resume_existing": False,
        }
        started = runtime.start_investigation({
            **base,
            "network_policy": {"max_anchor_depth": 3, "max_promoted_anchors": 25},
        })
        self.assertEqual(started["network_policy"]["legacy_budget_hints"]["max_anchor_depth"], 3)
        self.assertFalse(started["network_policy"]["legacy_budget_hints_enforced"])
        self.assert_rejected(
            lambda: runtime.start_investigation({
                **base,
                "network_policy": {"minimum_target_fit": "B+"},
            }),
            "cannot weaken the Runtime minimum A",
        )
        self.assert_rejected(
            lambda: runtime.start_investigation({
                **base,
                "network_policy": {"require_commercial_novelty": False},
            }),
            "non-relaxable true gate",
        )

    def test_11_invalid_start_does_not_mutate_canonical_registry(self):
        runtime = UnifiedRuntime(self.root)
        self.assert_rejected(
            lambda: runtime.start_investigation({
                "account": {"account_id": "INVALID-START-SYNTH", "country": "Canada"},
                "mode": "INVALID",
                "history": {"events": []},
            }),
            "mode: EXHAUSTIVE or FAST_SCAN required",
        )
        self.assertEqual(runtime.canonical_registry.entries(), [])

    def test_12_exporter_and_manufacturer_roles_remain_distinct(self):
        runtime = UnifiedRuntime(self.root)
        started = runtime.start_investigation({
            "account": {"account_id": "ROLE-SYNTH", "country": "Canada"},
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "supply_chain_parties": {
                "EXPORTER": {"entity_id": "EXP-1", "name": "Synthetic Exporter"},
                "PROBABLE_ACTUAL_MANUFACTURER": {"entity_id": "MFG-1", "name": "Synthetic Factory"},
            },
        })
        self.assertEqual(started["supply_chain_parties"]["EXPORTER"][0]["entity_id"], "EXP-1")
        self.assertEqual(
            started["supply_chain_parties"]["PROBABLE_ACTUAL_MANUFACTURER"][0]["entity_id"],
            "MFG-1",
        )
        history = runtime.get_information_history({"investigation_id": started["investigation_id"]})
        self.assertNotEqual(
            history["declared_supply_chain_parties"]["EXPORTER"][0]["entity_id"],
            history["declared_supply_chain_parties"]["PROBABLE_ACTUAL_MANUFACTURER"][0]["entity_id"],
        )

    def test_13_mcp_initialize_never_replays_pending_receipts(self):
        h = self.harness()
        payload = {
            "investigation_id": h.investigation_id,
            "record": self.information_record(h, "INFO-STARTUP-RECOVERY-001"),
        }
        h.runtime.queue_pending_receipt({
            "target_tool": "append_information_record",
            "payload": payload,
        })
        environment = dict(os.environ)
        environment["CBI_SESSION_ROOT"] = str(self.root)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        server = Path(__file__).resolve().parents[1] / "mcp" / "server.py"
        process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(server), "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        try:
            request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertEqual(response["result"]["serverInfo"]["version"], "6.1.0")
            self.assertIn("Default to ANSWER_FIRST", response["result"]["instructions"])
        finally:
            if process.stdin:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
        status = h.runtime.get_pending_journal_status({"investigation_id": h.investigation_id})
        self.assertEqual(status["counts"], {"PENDING": 1})
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(history["records"], [])

        synced = h.runtime.sync_pending_receipts({"investigation_id": h.investigation_id})
        self.assertEqual(synced["counts"], {"SYNCED": 1})
        status = h.runtime.get_pending_journal_status({"investigation_id": h.investigation_id})
        self.assertEqual(status["counts"], {"SYNCED": 1})
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(history["records"][0]["information_id"], "INFO-STARTUP-RECOVERY-001")

    def test_14_pending_request_hash_dedup_is_atomic_under_concurrency(self):
        h = self.harness()
        payload = {
            "investigation_id": h.investigation_id,
            "record": self.information_record(h, "INFO-CONCURRENT-PENDING-001"),
        }

        def queue_once(_: int) -> dict:
            return h.runtime.queue_pending_receipt({
                "target_tool": "append_information_record",
                "payload": copy.deepcopy(payload),
            })

        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(queue_once, range(16)))
        self.assertEqual(sum(row["queued"] is True for row in rows), 1)
        self.assertEqual(len({row["journal_id"] for row in rows}), 1)
        self.assertEqual(len(list(h.runtime.pending_journal.root.glob("PEND-*.json"))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
