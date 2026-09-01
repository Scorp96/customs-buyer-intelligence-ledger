from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import export_cloud_runtime_bundle as exporter
from scripts import import_cloud_runtime_bundle as importer


class CloudMigrationBundleHelperTests(unittest.TestCase):
    def test_expected_archive_sha256_is_strict(self) -> None:
        value = "AB" * 32
        self.assertEqual(value.lower(), importer._expected_sha256(value))
        for bad in ("", "0" * 63, "0" * 65, "g" * 64, "sha256:" + "0" * 64):
            with self.subTest(bad=bad[:16]):
                with self.assertRaises(ValueError):
                    importer._expected_sha256(bad)

    def test_archive_member_path_is_confined_to_expected_root(self) -> None:
        good = importer._safe_relative("cbi-cloud-runtime/sessions/INV-test.jsonl")
        self.assertEqual("cbi-cloud-runtime/sessions/INV-test.jsonl", good.as_posix())
        for bad in (
            "/cbi-cloud-runtime/sessions/x",
            "../cbi-cloud-runtime/sessions/x",
            "cbi-cloud-runtime/../escape",
            "other-root/sessions/x",
            "",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    importer._safe_relative(bad)

    def test_export_source_fingerprint_is_order_independent_but_change_sensitive(self) -> None:
        first = {
            "files": {"b": "2", "a": "1"},
            "chains": {"sessions": {"INV-1": {"seq": 2, "event_hash": "x"}}},
            "warnings": [],
        }
        reordered = {
            "warnings": [],
            "chains": {"sessions": {"INV-1": {"event_hash": "x", "seq": 2}}},
            "files": {"a": "1", "b": "2"},
        }
        changed = {
            **reordered,
            "files": {"a": "1", "b": "CHANGED"},
        }
        self.assertEqual(
            exporter._durable_fingerprint(first),
            exporter._durable_fingerprint(reordered),
        )
        self.assertNotEqual(
            exporter._durable_fingerprint(first),
            exporter._durable_fingerprint(changed),
        )
        with self.assertRaises(SystemExit):
            exporter._assert_same_source_state(first, changed, phase="unit-test")

    def test_payload_inventory_and_hashes_are_exact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cbi-cloud-payload-test-") as tmp_name:
            root = Path(tmp_name)
            session_root = root / "sessions"
            session_root.mkdir()
            payload = session_root / "INV-test.jsonl"
            payload.write_text("test\n", encoding="utf-8")
            relative = payload.relative_to(root).as_posix()
            manifest = {
                "schema": "cbi.cloud-runtime-export.v1",
                "hash_chains_valid": True,
                "activation_ready": True,
                "pre_archive_quiescence_check": True,
                "payload_files": {
                    relative: hashlib.sha256(payload.read_bytes()).hexdigest(),
                },
            }
            (root / "export-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            observed = importer._verify_payload(root)
            self.assertEqual(manifest["payload_files"], observed["payload_files"])

            extra = root / "unexpected.bin"
            extra.write_bytes(b"x")
            with self.assertRaises(ValueError):
                importer._verify_payload(root)
            extra.unlink()

            payload.write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                importer._verify_payload(root)

    def test_import_limits_are_bounded(self) -> None:
        self.assertGreater(importer.MAX_ARCHIVE_MEMBERS, 0)
        self.assertLessEqual(importer.MAX_ARCHIVE_MEMBERS, 1_000_000)
        self.assertGreater(importer.MAX_UNCOMPRESSED_BYTES, 0)
        self.assertLessEqual(importer.MAX_UNCOMPRESSED_BYTES, 20 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
