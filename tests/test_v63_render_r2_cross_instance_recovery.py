from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from mcp.object_store_persistence import ObjectStoreConflict
from mcp.object_store_recovery_v63 import (
    ARCHIVE_FORMAT_V2,
    RecoveryObjectStoreStateManagerV63,
    STATE_SCHEMA_V2,
)
from unified_runtime.exact_checkout_crash_scenarios_v63 import candidate_crash_arguments
from unified_runtime.exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from unified_runtime.exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from unified_runtime.recovery_semantics_v63 import canonical_v63_wal_request_sha256


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_TOOL = "append_candidate_discovery"
CANDIDATE_EVENT = "V63_CANDIDATE_DISCOVERED"


class _MemoryObjectClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}

    @staticmethod
    def _etag(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()[:32]

    def get(self, key: str):
        if key not in self.objects:
            return None, ""
        return self.objects[key], self.etags[key]

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str = "",
        if_none_match: bool = False,
    ):
        if if_none_match and key in self.objects:
            raise ObjectStoreConflict("exists")
        if if_match and self.etags.get(key, "") != if_match:
            raise ObjectStoreConflict("etag mismatch")
        self.objects[key] = bytes(body)
        self.etags[key] = self._etag(body)
        return self.etags[key]

    def list_keys(self, prefix: str):
        return sorted(key for key in self.objects if key.startswith(prefix))

    def delete(self, key: str):
        self.objects.pop(key, None)
        self.etags.pop(key, None)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_quiescent_migration_archive(live_root: Path, destination: Path) -> Path:
    source = Path(live_root).resolve()
    root = destination / "cbi-cloud-runtime"
    root.mkdir(parents=True)
    for component in ("sessions", "mcp-idempotency-v61"):
        component_source = source / component
        if component_source.is_dir():
            shutil.copytree(component_source, root / component)
    if not (root / "sessions").is_dir():
        raise AssertionError("migration fixture requires sessions")

    payload = {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema": "cbi.cloud-runtime-export.v1",
        "hash_chains_valid": True,
        "activation_ready": True,
        "pre_archive_quiescence_check": True,
        "payload_files": payload,
        "source_durable_fingerprint_sha256": "0" * 64,
    }
    (root / "export-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive = destination / "migration.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(root, arcname="cbi-cloud-runtime")
    return archive


def _candidate_rows(reader: ExactCheckoutPersistenceReader, investigation_id: str):
    evidence = reader.normalize_mutation_evidence(investigation_id, CANDIDATE_TOOL)
    events = evidence.get("events") or []
    wal = evidence.get("wal_records") or []
    if len(events) != 1 or len(wal) != 1:
        raise AssertionError(
            f"candidate evidence cardinality invalid events={len(events)} wal={len(wal)}"
        )
    return evidence, events[0], wal[0]


class V63RenderR2CrossInstanceRecoveryTests(unittest.TestCase):
    def test_candidate_crash_checkpoints_v2_restores_to_fresh_root_and_recovers_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-v63-r2-cross-instance-") as tmp_name:
            tmp = Path(tmp_name)
            live_a = tmp / "instance-a"
            live_b = tmp / "instance-b"
            live_c = tmp / "instance-c-proof"
            prefix = "cbi-v63-cross-instance-candidate"
            object_client = _MemoryObjectClient()

            bootstrap = ExactCheckoutMcpHarness(ROOT, live_a)
            bootstrap.start()
            try:
                started = bootstrap.tool(
                    2,
                    "start_investigation",
                    {
                        "account": {
                            "account_id": "C-V63-R2-XINST-CANDIDATE",
                            "country": "Synthetic",
                            "name": "Synthetic R2 Cross Instance Candidate Buyer",
                        },
                        "mode": "EXHAUSTIVE",
                        "history": {"events": []},
                        "network_policy": {"closure_strategy": "DECISION_SATURATION"},
                        "idempotency_key": "v63-r2-xinst-start-0001",
                    },
                )
                investigation_id = str(started["investigation_id"])
            finally:
                bootstrap.stop()

            migration_dir = tmp / "baseline-migration"
            migration_dir.mkdir()
            migration = _build_quiescent_migration_archive(live_a, migration_dir)
            seed = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
            seed.seed_migration_archive(migration, _sha256_file(migration))
            writer_a = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
            writer_a.attach_existing(live_a)
            self.assertEqual(writer_a.pointer.generation, 0)

            arguments = candidate_crash_arguments(investigation_id)
            crashing = ExactCheckoutMcpHarness(ROOT, live_a)
            crashing.start(crash_after_handler=CANDIDATE_TOOL)
            try:
                crashing.crash_tool(2, CANDIDATE_TOOL, arguments)
            finally:
                crashing.stop()

            reader_a = ExactCheckoutPersistenceReader(live_a)
            before_checkpoint, event_a, wal_a = _candidate_rows(reader_a, investigation_id)
            expected_request_sha = canonical_v63_wal_request_sha256(
                CANDIDATE_TOOL,
                arguments,
            )
            self.assertEqual(event_a["event_type"], CANDIDATE_EVENT)
            self.assertEqual(wal_a["status"], "PREPARED")
            self.assertEqual(event_a["request_sha256"], expected_request_sha)
            self.assertEqual(wal_a["request_sha256"], expected_request_sha)
            self.assertEqual(event_a["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(before_checkpoint["event_count"], 1)

            # Task 3 separately proves this sync is installed post-handler and
            # before the remote cold-exit point. Here we compose that boundary
            # with the real active mutation adapter and recovery-state v2.
            self.assertTrue(writer_a.sync_if_changed(live_a))
            self.assertEqual(writer_a.pointer.archive_format, ARCHIVE_FORMAT_V2)
            self.assertEqual(writer_a.health()["recovery_state_schema"], STATE_SCHEMA_V2)
            crash_generation = writer_a.pointer.generation
            self.assertGreater(crash_generation, 0)

            reader_b_state = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
            self.assertTrue(reader_b_state.restore_into(live_b))
            reader_b_state.attach_existing(live_b)
            self.assertNotEqual(live_a.resolve(), live_b.resolve())
            self.assertEqual(reader_b_state.pointer.generation, crash_generation)

            reader_b = ExactCheckoutPersistenceReader(live_b)
            restored_evidence, restored_event, restored_wal = _candidate_rows(
                reader_b,
                investigation_id,
            )
            self.assertEqual(restored_wal["status"], "PREPARED")
            self.assertEqual(restored_event["seq"], event_a["seq"])
            self.assertEqual(restored_event["correlation_id"], event_a["correlation_id"])
            self.assertEqual(restored_wal["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(restored_event["request_sha256"], expected_request_sha)
            self.assertEqual(restored_wal["request_sha256"], expected_request_sha)
            self.assertEqual(restored_evidence["event_count"], 1)

            recovered = ExactCheckoutMcpHarness(ROOT, live_b)
            recovered.start()
            try:
                response = recovered.tool(2, CANDIDATE_TOOL, arguments)
            finally:
                recovered.stop()

            mutation_meta = response.get("mutation_meta") or {}
            self.assertEqual(response.get("status"), "DISCOVERED")
            self.assertIs(mutation_meta.get("replayed"), True)
            self.assertIs(mutation_meta.get("reconciled_after_crash"), True)

            committed_evidence, committed_event, committed_wal = _candidate_rows(
                reader_b,
                investigation_id,
            )
            self.assertEqual(committed_wal["status"], "COMMITTED")
            self.assertEqual(committed_evidence["event_count"], 1)
            self.assertEqual(committed_event["seq"], event_a["seq"])
            self.assertEqual(committed_event["correlation_id"], event_a["correlation_id"])
            self.assertEqual(committed_wal["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(committed_event["request_sha256"], expected_request_sha)
            self.assertEqual(committed_wal["request_sha256"], expected_request_sha)

            # Remote non-crash dispatch performs the terminal sync after the
            # original adapter commits the WAL. Persist that exact state and
            # prove a third fresh root sees COMMITTED rather than PREPARED.
            self.assertTrue(reader_b_state.sync_if_changed(live_b))
            terminal_generation = reader_b_state.pointer.generation
            self.assertGreater(terminal_generation, crash_generation)

            verifier = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
            self.assertTrue(verifier.restore_into(live_c))
            verifier.attach_existing(live_c)
            reader_c = ExactCheckoutPersistenceReader(live_c)
            final_evidence, final_event, final_wal = _candidate_rows(
                reader_c,
                investigation_id,
            )
            self.assertEqual(final_wal["status"], "COMMITTED")
            self.assertEqual(final_evidence["event_count"], 1)
            self.assertEqual(final_event["seq"], event_a["seq"])
            self.assertEqual(final_event["correlation_id"], event_a["correlation_id"])
            self.assertEqual(final_wal["correlation_id"], wal_a["correlation_id"])
            self.assertEqual(final_event["request_sha256"], expected_request_sha)
            self.assertEqual(final_wal["request_sha256"], expected_request_sha)


if __name__ == "__main__":
    unittest.main()
