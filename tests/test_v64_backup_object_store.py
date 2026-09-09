from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from mcp.object_store_persistence import ObjectStoreConflict
from unified_runtime.backup_recovery import SNAPSHOT_SCHEMA


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

    def head(self, key: str):
        if key not in self.objects:
            return False, ""
        return True, self.etags[key]

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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_snapshot(root: Path, *, snapshot_id: str = "SNAP-20260909T103500Z-abcdef123456") -> Path:
    snapshot = root / snapshot_id
    payload = snapshot / "sessions" / "INV-TEST.jsonl"
    payload.parent.mkdir(parents=True)
    payload.write_text('{"seq":1,"event_hash":"' + ('a' * 64) + '"}\n', encoding="utf-8")
    manifest = {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot_id,
        "created_at": "2026-09-09T10:35:00Z",
        "reasons": ["DAILY"],
        "source_session_root": "/var/lib/cbi/live/sessions",
        "files": {"sessions/INV-TEST.jsonl": _sha256(payload)},
        "chains": {"sessions": {}},
        "warnings": [],
    }
    (snapshot / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    return snapshot


class BackupObjectStoreContractTests(unittest.TestCase):
    @staticmethod
    def _api():
        try:
            module = importlib.import_module("unified_runtime.backup_object_store_v64")
        except ModuleNotFoundError:
            return None, None
        return (
            getattr(module, "BackupObjectStoreReplica", None),
            getattr(module, "BackupObjectStoreError", None),
        )

    def _replica(self, client: FakeObjectClient):
        cls, _error = self._api()
        self.assertIsNotNone(cls, "BackupObjectStoreReplica must exist")
        return cls(client, prefix="cbi-test", retention=20)

    def test_first_upload_and_identical_retry_are_immutable_and_idempotent(self) -> None:
        client = FakeObjectClient()
        replica = self._replica(client)
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-object-") as td:
            snapshot = make_snapshot(Path(td))
            first = replica.replicate_snapshot(snapshot, snapshot.name)
            second = replica.replicate_snapshot(snapshot, snapshot.name)

        self.assertTrue(first["verified"])
        self.assertTrue(second["verified"])
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(first["archive_key"], second["archive_key"])
        self.assertEqual(first["archive_sha256"], second["archive_sha256"])
        self.assertEqual(len(client.objects), 2, "one archive + one immutable manifest expected")

    def test_conflicting_existing_immutable_archive_fails_closed(self) -> None:
        client = FakeObjectClient()
        replica = self._replica(client)
        _cls, error = self._api()
        self.assertIsNotNone(error, "BackupObjectStoreError must exist")
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-conflict-") as td:
            snapshot = make_snapshot(Path(td))
            first = replica.replicate_snapshot(snapshot, snapshot.name)
            client.objects[first["archive_key"]] = b"tampered-existing-object"
            client.etags[first["archive_key"]] = client._etag(client.objects[first["archive_key"]])
            with self.assertRaises(error):
                replica.replicate_snapshot(snapshot, snapshot.name)

    def test_same_snapshot_id_with_changed_local_content_fails_closed(self) -> None:
        client = FakeObjectClient()
        replica = self._replica(client)
        _cls, error = self._api()
        self.assertIsNotNone(error)
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-local-conflict-") as td:
            snapshot = make_snapshot(Path(td))
            replica.replicate_snapshot(snapshot, snapshot.name)
            payload = snapshot / "sessions" / "INV-TEST.jsonl"
            payload.write_text("changed\n", encoding="utf-8")
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["sessions/INV-TEST.jsonl"] = _sha256(payload)
            manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(error):
                replica.replicate_snapshot(snapshot, snapshot.name)

    def test_tampered_local_snapshot_is_rejected_before_upload(self) -> None:
        client = FakeObjectClient()
        replica = self._replica(client)
        _cls, error = self._api()
        self.assertIsNotNone(error)
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-tampered-") as td:
            snapshot = make_snapshot(Path(td))
            (snapshot / "sessions" / "INV-TEST.jsonl").write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(error):
                replica.replicate_snapshot(snapshot, snapshot.name)
        self.assertEqual(client.objects, {})

    def test_invalid_snapshot_id_fails_closed(self) -> None:
        client = FakeObjectClient()
        replica = self._replica(client)
        _cls, error = self._api()
        self.assertIsNotNone(error)
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-id-") as td:
            snapshot = Path(td) / "../escape"
            with self.assertRaises(error):
                replica.replicate_snapshot(snapshot, "../escape")

    def test_fresh_replica_rediscovers_and_verifies_external_snapshot(self) -> None:
        client = FakeObjectClient()
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-discovery-") as td:
            snapshot = make_snapshot(Path(td))
            first = self._replica(client).replicate_snapshot(snapshot, snapshot.name)

        fresh = self._replica(client)
        rows = fresh.list_snapshots()
        latest = fresh.latest_snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["snapshot_id"], first["snapshot_id"])
        self.assertTrue(rows[0]["verified"])
        self.assertIsNotNone(latest)
        self.assertEqual(latest["snapshot_id"], first["snapshot_id"])
        self.assertEqual(latest["archive_sha256"], first["archive_sha256"])

    def test_discovery_rejects_manifest_archive_hash_mismatch(self) -> None:
        client = FakeObjectClient()
        replica = self._replica(client)
        _cls, error = self._api()
        self.assertIsNotNone(error)
        with tempfile.TemporaryDirectory(prefix="cbi-v64-backup-manifest-") as td:
            snapshot = make_snapshot(Path(td))
            result = replica.replicate_snapshot(snapshot, snapshot.name)
        client.objects[result["archive_key"]] += b"tamper"
        client.etags[result["archive_key"]] = client._etag(client.objects[result["archive_key"]])
        with self.assertRaises(error):
            self._replica(client).list_snapshots()

    def test_discovery_is_confined_to_dedicated_prefix(self) -> None:
        client = FakeObjectClient()
        client.put("other-prefix/manifests/SNAP-20260909T103500Z-abcdef123456.json", b"{}")
        replica = self._replica(client)
        self.assertEqual(replica.list_snapshots(), [])


if __name__ == "__main__":
    unittest.main()
