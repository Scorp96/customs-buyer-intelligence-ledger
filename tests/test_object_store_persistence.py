from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from mcp.object_store_persistence import (
    ObjectStoreConflict,
    ObjectStorePointer,
    ObjectStoreStateManager,
    _build_state_archive,
    _extract_tar_safely,
    _sessions_fingerprint,
    _verify_state_v1,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class FakeObjectClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.deleted: list[str] = []

    @staticmethod
    def _etag(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()[:32]

    def get(self, key: str):
        if key not in self.objects:
            return None, ""
        return self.objects[key], self.etags[key]

    def put(self, key: str, body: bytes, *, if_match: str = "", if_none_match: bool = False):
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
        self.deleted.append(key)


def make_migration_archive(directory: Path) -> Path:
    root = directory / "cbi-cloud-runtime"
    sessions = root / "sessions"
    sessions.mkdir(parents=True)
    first = sessions / "INV-TEST.jsonl"
    first.write_text('{"seq":1,"event":"seed"}\n', encoding="utf-8")
    payload = {"sessions/INV-TEST.jsonl": sha256_file(first)}
    manifest = {
        "schema": "cbi.cloud-runtime-export.v1",
        "hash_chains_valid": True,
        "activation_ready": True,
        "pre_archive_quiescence_check": True,
        "payload_files": payload,
        "source_durable_fingerprint_sha256": "0" * 64,
    }
    (root / "export-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    archive = directory / "migration.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(root, arcname="cbi-cloud-runtime")
    return archive


class ObjectStorePersistenceTests(unittest.TestCase):
    def test_object_state_archive_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            sessions = tmp / "sessions"
            sessions.mkdir()
            (sessions / "INV-A.jsonl").write_text("a\nb\n", encoding="utf-8")
            archive = tmp / "state.tar.gz"
            archive_sha, fingerprint = _build_state_archive(sessions, 7, archive)
            self.assertEqual(len(archive_sha), 64)
            staging = tmp / "extract"
            staging.mkdir()
            extracted = _extract_tar_safely(archive, staging, "cbi-object-state")
            manifest = _verify_state_v1(extracted)
            self.assertEqual(manifest["generation"], 7)
            self.assertEqual(manifest["sessions_fingerprint_sha256"], fingerprint)
            self.assertEqual(_sessions_fingerprint(extracted / "sessions"), fingerprint)

    def test_seed_restore_sync_and_second_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            archive = make_migration_archive(tmp / "source")
            client = FakeObjectClient()
            manager = ObjectStoreStateManager(client, prefix="cbi-test", retention=20)
            pointer0 = manager.seed_migration_archive(archive, sha256_file(archive))
            self.assertEqual(pointer0.generation, 0)
            self.assertEqual(pointer0.archive_format, "migration_v1")

            live = tmp / "live-a"
            restored_manager = ObjectStoreStateManager(client, prefix="cbi-test", retention=20)
            self.assertTrue(restored_manager.restore_into(live))
            restored_manager.attach_existing(live)
            self.assertEqual(
                _sessions_fingerprint(live / "sessions"),
                pointer0.sessions_fingerprint_sha256,
            )

            with (live / "sessions" / "INV-TEST.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"seq":2,"event":"cloud"}\n')
            self.assertTrue(restored_manager.sync_if_changed(live))
            pointer1 = restored_manager.pointer
            self.assertIsNotNone(pointer1)
            assert pointer1 is not None
            self.assertEqual(pointer1.generation, 1)
            self.assertEqual(pointer1.archive_format, "object_state_v1")
            self.assertNotEqual(pointer1.sessions_fingerprint_sha256, pointer0.sessions_fingerprint_sha256)
            self.assertFalse(restored_manager.sync_if_changed(live))

            live_b = tmp / "live-b"
            next_boot = ObjectStoreStateManager(client, prefix="cbi-test", retention=20)
            self.assertTrue(next_boot.restore_into(live_b))
            next_boot.attach_existing(live_b)
            self.assertEqual(
                (live_b / "sessions" / "INV-TEST.jsonl").read_text(encoding="utf-8"),
                (live / "sessions" / "INV-TEST.jsonl").read_text(encoding="utf-8"),
            )

    def test_current_pointer_compare_and_swap_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            archive = make_migration_archive(tmp / "source")
            client = FakeObjectClient()
            manager = ObjectStoreStateManager(client, prefix="cbi-test", retention=20)
            manager.seed_migration_archive(archive, sha256_file(archive))

            live = tmp / "live"
            writer_a = ObjectStoreStateManager(client, prefix="cbi-test", retention=20)
            writer_a.restore_into(live)
            writer_a.attach_existing(live)
            stale_etag = writer_a.pointer.etag if writer_a.pointer else ""

            # Another writer advances current.json without writer_a observing it.
            existing_body, _ = client.get(writer_a.pointer_key)
            self.assertIsNotNone(existing_body)
            assert existing_body is not None
            current = ObjectStorePointer.from_bytes(existing_body, client.etags[writer_a.pointer_key])
            foreign = ObjectStorePointer(
                generation=current.generation + 1,
                archive_key=current.archive_key,
                archive_sha256=current.archive_sha256,
                sessions_fingerprint_sha256=current.sessions_fingerprint_sha256,
                archive_format=current.archive_format,
            )
            client.put(writer_a.pointer_key, foreign.to_bytes(), if_match=client.etags[writer_a.pointer_key])
            self.assertNotEqual(client.etags[writer_a.pointer_key], stale_etag)

            with (live / "sessions" / "INV-TEST.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"seq":2,"event":"stale-writer"}\n')
            with self.assertRaises(ObjectStoreConflict):
                writer_a.sync_if_changed(live)
            self.assertEqual(writer_a.health()["last_error"], "OBJECT_STORE_CAS_CONFLICT")

    def test_retention_prunes_old_immutable_generations_only_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            archive = make_migration_archive(tmp / "source")
            client = FakeObjectClient()
            manager = ObjectStoreStateManager(client, prefix="cbi-test", retention=2)
            manager.seed_migration_archive(archive, sha256_file(archive))
            live = tmp / "live"
            manager = ObjectStoreStateManager(client, prefix="cbi-test", retention=2)
            manager.restore_into(live)
            manager.attach_existing(live)
            for seq in range(2, 5):
                with (live / "sessions" / "INV-TEST.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"seq": seq}) + "\n")
                manager.sync_if_changed(live)
            keys = client.list_keys(manager.state_prefix)
            self.assertLessEqual(len(keys), 2)
            self.assertIn(manager.pointer.archive_key, keys)


if __name__ == "__main__":
    unittest.main()
