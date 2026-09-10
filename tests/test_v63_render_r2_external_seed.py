from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from mcp.object_store_persistence import ObjectStoreConflict
from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_v63_render_r2_pvc_acceptance.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_v63_render_r2_pvc_acceptance", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Task 10 external acceptance CLI is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.etags.pop(key, None)


class V63RenderR2ExternalSeedTests(unittest.TestCase):
    def test_empty_isolated_prefix_is_seeded_once_and_existing_state_is_never_overwritten(self) -> None:
        module = _load_script_module()
        seed_helper = getattr(module, "_ensure_disposable_r2_baseline", None)
        self.assertTrue(
            callable(seed_helper),
            "external acceptance must seed an empty disposable R2 prefix before Render bootstrap",
        )

        client = _MemoryObjectClient()
        manager = RecoveryObjectStoreStateManagerV63(
            client,
            prefix="cbi-v63-external-seed-test",
        )

        first = seed_helper(manager=manager, checkout_root=ROOT)
        self.assertIs(first.get("seeded"), True)
        self.assertEqual(first.get("generation"), 0)
        self.assertEqual(first.get("archive_format"), "migration_v1")

        pointer = manager.read_pointer(required=True)
        self.assertIsNotNone(pointer)
        assert pointer is not None
        self.assertEqual(pointer.generation, 0)
        self.assertEqual(pointer.archive_format, "migration_v1")

        with tempfile.TemporaryDirectory(prefix="cbi-v63-external-seed-restore-") as tmp_name:
            restored = Path(tmp_name) / "live"
            verifier = RecoveryObjectStoreStateManagerV63(
                client,
                prefix="cbi-v63-external-seed-test",
            )
            self.assertTrue(verifier.restore_into(restored))
            self.assertTrue((restored / "sessions").is_dir())
            self.assertTrue(any((restored / "sessions").iterdir()))
            self.assertTrue((restored / "export-manifest.json").is_file())

        snapshot = dict(client.objects)
        second = seed_helper(manager=manager, checkout_root=ROOT)
        self.assertIs(second.get("seeded"), False)
        self.assertEqual(second.get("generation"), 0)
        self.assertEqual(client.objects, snapshot, "existing R2 authority must never be overwritten")

        serialized = repr(first).casefold() + repr(second).casefold()
        self.assertNotIn("idempotency_key", serialized)
        self.assertNotIn("bearer", serialized)
        self.assertNotIn("secret", serialized)


if __name__ == "__main__":
    unittest.main()
