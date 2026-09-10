from __future__ import annotations

import unittest

from astra_worker.models import TaskEnvelope, TaskValidationError
from astra_worker.protocol import (
    ProtocolError,
    canonical_json_v1,
    decode_signed_envelope,
    encode_signed_envelope,
    hmac_sha256_hex,
    parse_strict_json,
    verify_hmac_sha256,
)


def valid_task_mapping() -> dict:
    return {
        "schema_version": "astra.task.v1",
        "task_id": "task-001",
        "worker_id": "scorp-windows-01",
        "repository_id": "cbi-primary",
        "base_ref": "cbi-v6-3-demand-expansion",
        "base_commit_sha": "a" * 40,
        "issued_at": "2026-09-09T03:00:00Z",
        "expires_at": "2026-09-09T03:30:00Z",
        "nonce": "nonce-001",
        "operations": [
            {
                "kind": "write_text",
                "path": "example.txt",
                "content": "hello\n",
                "expect_absent": True,
            },
            {
                "kind": "run_unittest",
                "targets": ["tests.test_example"],
                "flags": ["-v"],
            },
        ],
        "acceptance": {"max_changed_files": 5, "max_diff_bytes": 4096},
    }


class CanonicalProtocolTests(unittest.TestCase):
    def test_duplicate_key_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":1,"a":2}')

    def test_float_and_non_finite_numbers_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":1.5}')
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":NaN}')

    def test_canonical_bytes_are_stable_utf8(self) -> None:
        left = parse_strict_json('{"z":"越南","a":1}')
        right = parse_strict_json('{"a":1,"z":"越南"}')
        self.assertEqual(canonical_json_v1(left), canonical_json_v1(right))
        self.assertEqual(
            canonical_json_v1(left),
            b'{"a":1,"z":"\xe8\xb6\x8a\xe5\x8d\x97"}',
        )

    def test_out_of_range_integer_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            canonical_json_v1({"n": 2**63})

    def test_changed_payload_invalidates_hmac(self) -> None:
        key = b"k" * 32
        value = {"task_id": "t1", "n": 1}
        signature = hmac_sha256_hex(key, value)
        verify_hmac_sha256(key, value, signature)
        with self.assertRaises(ProtocolError):
            verify_hmac_sha256(key, {"task_id": "t1", "n": 2}, signature)

    def test_signed_envelope_round_trip_and_strict_shape(self) -> None:
        payload = {"task_id": "t1", "n": 1}
        signature = "a" * 64
        encoded = encode_signed_envelope("task", payload, signature)
        decoded_payload, decoded_signature = decode_signed_envelope(encoded, "task")
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(decoded_signature, signature)

        with self.assertRaises(ProtocolError):
            decode_signed_envelope(encoded, "receipt")
        with self.assertRaises(ProtocolError):
            decode_signed_envelope(
                'ASTRA_TASK_V1 {"payload":{},"signature":"' + signature + '","extra":1}',
                "task",
            )


class TaskSchemaTests(unittest.TestCase):
    def test_valid_task_mapping_has_no_local_path_authority(self) -> None:
        task = TaskEnvelope.from_mapping(valid_task_mapping())
        self.assertEqual(task.repository_id, "cbi-primary")
        self.assertEqual(task.base_commit_sha, "a" * 40)
        self.assertFalse(hasattr(task, "repository_root"))

    def test_remote_local_path_and_unknown_top_level_fields_are_rejected(self) -> None:
        payload = valid_task_mapping()
        payload["repository_root"] = "C:/Users/scorp"
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

    def test_arbitrary_run_argv_is_rejected(self) -> None:
        payload = valid_task_mapping()
        payload["operations"] = [
            {"kind": "run", "argv": ["powershell", "-c", "Write-Host pwned"]}
        ]
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

    def test_write_requires_exactly_one_precondition(self) -> None:
        payload = valid_task_mapping()
        payload["operations"] = [
            {"kind": "write_text", "path": "a.txt", "content": "x"}
        ]
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

        payload["operations"] = [
            {
                "kind": "write_text",
                "path": "a.txt",
                "content": "x",
                "expected_sha256": "b" * 64,
                "expect_absent": True,
            }
        ]
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

    def test_task_rejects_unsafe_path_and_non_utc_timestamp(self) -> None:
        payload = valid_task_mapping()
        payload["operations"][0]["path"] = "../escape.txt"
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

        payload = valid_task_mapping()
        payload["issued_at"] = "2026-09-09T03:00:00+08:00"
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

    def test_windows_ambiguous_or_device_paths_are_rejected_portably(self) -> None:
        unsafe_paths = (
            "notes.txt:secret",
            "C:drive-relative.txt",
            "CON",
            "con.txt",
            "folder/NUL.dat",
            "folder/trailing.",
            "folder/trailing. ",
            "bad<name>.txt",
            "bad>name.txt",
            'bad"name.txt',
            "bad|name.txt",
            "bad?name.txt",
            "bad*name.txt",
        )
        for path in unsafe_paths:
            with self.subTest(path=path):
                payload = valid_task_mapping()
                payload["operations"] = [
                    {
                        "kind": "write_text",
                        "path": path,
                        "content": "x",
                        "expect_absent": True,
                    }
                ]
                with self.assertRaises(TaskValidationError):
                    TaskEnvelope.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
