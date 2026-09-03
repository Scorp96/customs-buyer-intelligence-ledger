from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from mcp.object_store_persistence import (
    ObjectStoreConflict,
    ObjectStoreStateManager,
)


class _FakeObjectClient:
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


def _migration_archive(directory: Path) -> Path:
    root = directory / "cbi-cloud-runtime"
    sessions = root / "sessions"
    sessions.mkdir(parents=True)
    session = sessions / "INV-V63-R2.jsonl"
    session.write_text('{"seq":1,"event":"seed"}\n', encoding="utf-8")
    manifest = {
        "schema": "cbi.cloud-runtime-export.v1",
        "hash_chains_valid": True,
        "activation_ready": True,
        "pre_archive_quiescence_check": True,
        "payload_files": {"sessions/INV-V63-R2.jsonl": _sha256_file(session)},
        "source_durable_fingerprint_sha256": "0" * 64,
    }
    (root / "export-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive = directory / "migration.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(root, arcname="cbi-cloud-runtime")
    return archive


class V63ObjectStoreRecoveryStateTests(unittest.TestCase):
    def test_next_generation_restores_sessions_and_prepared_mutation_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            migration = _migration_archive(tmp / "source")
            client = _FakeObjectClient()
            seed = ObjectStoreStateManager(client, prefix="cbi-v63-r2-test")
            seed.seed_migration_archive(migration, _sha256_file(migration))

            live_a = tmp / "live-a"
            writer = ObjectStoreStateManager(client, prefix="cbi-v63-r2-test")
            self.assertTrue(writer.restore_into(live_a))
            writer.attach_existing(live_a)

            session_path = live_a / "sessions" / "INV-V63-R2.jsonl"
            with session_path.open("a", encoding="utf-8") as handle:
                handle.write('{"seq":2,"event":"V63_CANDIDATE_DISCOVERED"}\n')

            wal_dir = live_a / "mcp-idempotency-v61"
            wal_dir.mkdir()
            wal_path = wal_dir / "append_candidate_discovery-test.json"
            wal_bytes = (
                json.dumps(
                    {
                        "schema": "cbi.mutation-wal.v6.1",
                        "status": "PREPARED",
                        "tool": "append_candidate_discovery",
                        "idempotency_key": "v63-r2-recovery-test-key",
                        "request_sha256": "a" * 64,
                        "state_version_before": 1,
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            wal_path.write_bytes(wal_bytes)

            self.assertTrue(writer.sync_if_changed(live_a))

            live_b = tmp / "live-b"
            reader = ObjectStoreStateManager(client, prefix="cbi-v63-r2-test")
            self.assertTrue(reader.restore_into(live_b))
            reader.attach_existing(live_b)

            self.assertEqual(
                (live_b / "sessions" / "INV-V63-R2.jsonl").read_bytes(),
                session_path.read_bytes(),
            )
            restored_wal = live_b / "mcp-idempotency-v61" / wal_path.name
            self.assertTrue(restored_wal.is_file(), "R2 recovery generation omitted mutation WAL")
            self.assertEqual(restored_wal.read_bytes(), wal_bytes)


if __name__ == "__main__":
    unittest.main()
