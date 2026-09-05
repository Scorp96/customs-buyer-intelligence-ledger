from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63
from tests.test_v63_render_r2_cross_instance_recovery import (
    _MemoryObjectClient,
    _build_quiescent_migration_archive,
    _sha256_file,
)
from unified_runtime.exact_checkout_crash_scenarios_v63 import (
    anchor_crash_arguments,
    opportunity_crash_arguments,
)
from unified_runtime.exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from unified_runtime.exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from unified_runtime.recovery_semantics_v63 import (
    canonical_v63_wal_request_sha256,
    snapshot_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
OPPORTUNITY_TOOL = "create_product_opportunity"
OPPORTUNITY_EVENT = "V63_PRODUCT_OPPORTUNITY_CREATED"
ANCHOR_TOOL = "promote_opportunity_anchor"
ANCHOR_EVENT = "V63_OPPORTUNITY_ANCHOR_PROMOTED"


def _single_normalized(reader: ExactCheckoutPersistenceReader, investigation_id: str, tool: str):
    evidence = reader.normalize_mutation_evidence(investigation_id, tool)
    events = evidence.get("events") or []
    wal = evidence.get("wal_records") or []
    if len(events) != 1 or len(wal) != 1:
        raise AssertionError(
            f"{tool} evidence cardinality invalid events={len(events)} wal={len(wal)}"
        )
    return evidence, events[0], wal[0]


def _single_raw_event(
    reader: ExactCheckoutPersistenceReader,
    investigation_id: str,
    event_type: str,
):
    matches = [
        event
        for event in reader.read_session_events(investigation_id)
        if event.get("event_type") == event_type
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"{event_type} raw event cardinality invalid count={len(matches)}"
        )
    event = matches[0]
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise AssertionError(f"{event_type} payload missing")
    return event, payload


def _bootstrap_and_seed(
    tmp: Path,
    *,
    account_id: str,
    account_name: str,
    start_key: str,
    prefix: str,
):
    live_a = tmp / "instance-a"
    live_b = tmp / "instance-b"
    object_client = _MemoryObjectClient()

    harness = ExactCheckoutMcpHarness(ROOT, live_a)
    harness.start()
    try:
        started = harness.tool(
            2,
            "start_investigation",
            {
                "account": {
                    "account_id": account_id,
                    "country": "Synthetic",
                    "name": account_name,
                },
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
                "network_policy": {"closure_strategy": "DECISION_SATURATION"},
                "idempotency_key": start_key,
            },
        )
        investigation_id = str(started["investigation_id"])
    finally:
        harness.stop()

    migration_dir = tmp / "baseline-migration"
    migration_dir.mkdir()
    migration = _build_quiescent_migration_archive(live_a, migration_dir)
    seed = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
    seed.seed_migration_archive(migration, _sha256_file(migration))
    writer = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
    writer.attach_existing(live_a)
    return live_a, live_b, object_client, writer, investigation_id


class V63RenderR2CrossInstanceStateShapeTests(unittest.TestCase):
    def test_opportunity_result_snapshot_survives_r2_restore_and_drives_exact_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v63-r2-xinst-opportunity-") as tmp_name:
            tmp = Path(tmp_name)
            live_a, live_b, object_client, writer, investigation_id = _bootstrap_and_seed(
                tmp,
                account_id="C-V63-CRASH-OPPORTUNITY",
                account_name="Synthetic R2 Opportunity Shape Buyer",
                start_key="v63-r2-xinst-opportunity-start-0001",
                prefix="cbi-v63-xinst-opportunity-shape",
            )
            arguments = opportunity_crash_arguments(investigation_id)

            crashing = ExactCheckoutMcpHarness(ROOT, live_a)
            crashing.start(crash_after_handler=OPPORTUNITY_TOOL)
            try:
                crashing.crash_tool(2, OPPORTUNITY_TOOL, arguments)
            finally:
                crashing.stop()

            reader_a = ExactCheckoutPersistenceReader(live_a)
            evidence_a, event_a, wal_a = _single_normalized(
                reader_a,
                investigation_id,
                OPPORTUNITY_TOOL,
            )
            _raw_a, payload_a = _single_raw_event(
                reader_a,
                investigation_id,
                OPPORTUNITY_EVENT,
            )
            expected_sha = canonical_v63_wal_request_sha256(OPPORTUNITY_TOOL, arguments)
            snapshot_a = copy.deepcopy(payload_a.get("result_snapshot"))
            snapshot_sha_a = str(payload_a.get("result_snapshot_sha256") or "")
            self.assertIsInstance(snapshot_a, dict)
            self.assertEqual(snapshot_sha256(snapshot_a), snapshot_sha_a)
            self.assertEqual(event_a["request_sha256"], expected_sha)
            self.assertEqual(wal_a["request_sha256"], expected_sha)
            self.assertEqual(event_a["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(wal_a["status"], "PREPARED")
            self.assertEqual(evidence_a["event_count"], 1)

            self.assertTrue(writer.sync_if_changed(live_a))
            restorer = RecoveryObjectStoreStateManagerV63(
                object_client,
                prefix="cbi-v63-xinst-opportunity-shape",
            )
            self.assertTrue(restorer.restore_into(live_b))
            restorer.attach_existing(live_b)

            reader_b = ExactCheckoutPersistenceReader(live_b)
            evidence_b, event_b, wal_b = _single_normalized(
                reader_b,
                investigation_id,
                OPPORTUNITY_TOOL,
            )
            _raw_b, payload_b = _single_raw_event(
                reader_b,
                investigation_id,
                OPPORTUNITY_EVENT,
            )
            self.assertEqual(payload_b.get("result_snapshot"), snapshot_a)
            self.assertEqual(payload_b.get("result_snapshot_sha256"), snapshot_sha_a)
            self.assertEqual(event_b["correlation_id"], event_a["correlation_id"])
            self.assertEqual(wal_b["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(wal_b["status"], "PREPARED")
            self.assertEqual(evidence_b["event_count"], 1)

            recovered = ExactCheckoutMcpHarness(ROOT, live_b)
            recovered.start()
            try:
                response = recovered.tool(2, OPPORTUNITY_TOOL, arguments)
            finally:
                recovered.stop()
            mutation_meta = response.get("mutation_meta") or {}
            business_result = copy.deepcopy(response)
            business_result.pop("mutation_meta", None)
            self.assertEqual(business_result, snapshot_a)
            self.assertIs(mutation_meta.get("replayed"), True)
            self.assertIs(mutation_meta.get("reconciled_after_crash"), True)

            post, post_event, post_wal = _single_normalized(
                reader_b,
                investigation_id,
                OPPORTUNITY_TOOL,
            )
            self.assertEqual(post_wal["status"], "COMMITTED")
            self.assertEqual(post["event_count"], 1)
            self.assertEqual(post_event["seq"], event_a["seq"])
            self.assertEqual(post_event["result_snapshot"], snapshot_a)
            self.assertEqual(post_event["result_snapshot_sha256"], snapshot_sha_a)

    def test_anchor_eligibility_and_cycle_snapshots_survive_r2_restore_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v63-r2-xinst-anchor-") as tmp_name:
            tmp = Path(tmp_name)
            live_a, live_b, object_client, writer, investigation_id = _bootstrap_and_seed(
                tmp,
                account_id="C-V63-CRASH-ANCHOR",
                account_name="Synthetic R2 Anchor Shape Buyer",
                start_key="v63-r2-xinst-anchor-start-0001",
                prefix="cbi-v63-xinst-anchor-shape",
            )
            arguments = anchor_crash_arguments(investigation_id)

            crashing = ExactCheckoutMcpHarness(ROOT, live_a)
            crashing.start(crash_after_handler=ANCHOR_TOOL)
            try:
                crashing.crash_tool(2, ANCHOR_TOOL, arguments)
            finally:
                crashing.stop()

            reader_a = ExactCheckoutPersistenceReader(live_a)
            evidence_a, event_a, wal_a = _single_normalized(
                reader_a,
                investigation_id,
                ANCHOR_TOOL,
            )
            _raw_a, payload_a = _single_raw_event(
                reader_a,
                investigation_id,
                ANCHOR_EVENT,
            )
            expected_sha = canonical_v63_wal_request_sha256(ANCHOR_TOOL, arguments)
            eligibility_a = copy.deepcopy(payload_a.get("anchor_eligibility_snapshot"))
            cycle_a = copy.deepcopy(payload_a.get("cycle_dedup_snapshot"))
            self.assertEqual(eligibility_a, arguments["anchor_eligibility"])
            self.assertEqual(cycle_a, {"cycle_dedup_complete": True})
            self.assertEqual(event_a["request_sha256"], expected_sha)
            self.assertEqual(wal_a["request_sha256"], expected_sha)
            self.assertEqual(event_a["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(wal_a["status"], "PREPARED")
            self.assertEqual(evidence_a["event_count"], 1)

            self.assertTrue(writer.sync_if_changed(live_a))
            restorer = RecoveryObjectStoreStateManagerV63(
                object_client,
                prefix="cbi-v63-xinst-anchor-shape",
            )
            self.assertTrue(restorer.restore_into(live_b))
            restorer.attach_existing(live_b)

            reader_b = ExactCheckoutPersistenceReader(live_b)
            evidence_b, event_b, wal_b = _single_normalized(
                reader_b,
                investigation_id,
                ANCHOR_TOOL,
            )
            _raw_b, payload_b = _single_raw_event(
                reader_b,
                investigation_id,
                ANCHOR_EVENT,
            )
            self.assertEqual(payload_b.get("anchor_eligibility_snapshot"), eligibility_a)
            self.assertEqual(payload_b.get("cycle_dedup_snapshot"), cycle_a)
            self.assertEqual(event_b["correlation_id"], event_a["correlation_id"])
            self.assertEqual(wal_b["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(wal_b["status"], "PREPARED")
            self.assertEqual(evidence_b["event_count"], 1)

            recovered = ExactCheckoutMcpHarness(ROOT, live_b)
            recovered.start()
            try:
                response = recovered.tool(2, ANCHOR_TOOL, arguments)
            finally:
                recovered.stop()
            mutation_meta = response.get("mutation_meta") or {}
            self.assertEqual(response.get("anchor_eligibility_snapshot"), eligibility_a)
            self.assertEqual(response.get("cycle_dedup_snapshot"), cycle_a)
            self.assertIs(mutation_meta.get("replayed"), True)
            self.assertIs(mutation_meta.get("reconciled_after_crash"), True)

            post, post_event, post_wal = _single_normalized(
                reader_b,
                investigation_id,
                ANCHOR_TOOL,
            )
            self.assertEqual(post_wal["status"], "COMMITTED")
            self.assertEqual(post["event_count"], 1)
            self.assertEqual(post_event["seq"], event_a["seq"])


if __name__ == "__main__":
    unittest.main()
