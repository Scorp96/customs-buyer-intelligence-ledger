from __future__ import annotations

import hashlib
import unittest

from astra_worker.apply_contract import (
    ApplyContractError,
    RemoteSnapshot,
    VerifiedReceipt,
    build_apply_plan,
)
from astra_worker.models import ReceiptEnvelope, TaskEnvelope
from astra_worker.receipt_gate import ReceiptGateResult


BASE_SHA = "a" * 40
OLD_BYTES = b"old\n"
DELETE_BYTES = b"delete-me\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def valid_task() -> TaskEnvelope:
    return TaskEnvelope.from_mapping(
        {
            "schema_version": "astra.task.v1",
            "task_id": "task-apply-001",
            "worker_id": "scorp-windows-01",
            "repository_id": "cbi-primary",
            "base_ref": "cbi-v6-3-demand-expansion",
            "base_commit_sha": BASE_SHA,
            "issued_at": "2026-09-09T03:00:00Z",
            "expires_at": "2026-09-09T03:30:00Z",
            "nonce": "nonce-apply-001",
            "operations": [
                {
                    "kind": "write_text",
                    "path": "existing.txt",
                    "content": "new\n",
                    "expected_sha256": sha256_bytes(OLD_BYTES),
                },
                {
                    "kind": "write_text",
                    "path": "created.txt",
                    "content": "created\n",
                    "expect_absent": True,
                },
                {
                    "kind": "delete_file",
                    "path": "deleted.txt",
                    "expected_sha256": sha256_bytes(DELETE_BYTES),
                },
                {
                    "kind": "run_unittest",
                    "targets": ["tests.test_astra_worker_apply_contract"],
                    "flags": [],
                },
            ],
            "acceptance": {"max_changed_files": 5, "max_diff_bytes": 8192},
        }
    )


def observed_final_hashes() -> dict[str, str | None]:
    return {
        "existing.txt": sha256_bytes(b"new\n"),
        "created.txt": sha256_bytes(b"created\n"),
        "deleted.txt": None,
    }


def verified_receipt(
    task: TaskEnvelope,
    *,
    observed: dict[str, str | None] | None = None,
    receipt_status: str = "APPLY_READY",
    marker_status: str = "VERIFIED",
) -> VerifiedReceipt:
    receipt = ReceiptEnvelope.from_mapping(
        {
            "schema_version": "astra.receipt.v1",
            "task_id": task.task_id,
            "worker_id": task.worker_id,
            "repository_id": task.repository_id,
            "base_ref": task.base_ref,
            "base_commit_sha": task.base_commit_sha,
            "status": receipt_status,
            "evidence": {
                "observed_final_hashes": observed if observed is not None else observed_final_hashes(),
                # Review-only patch text is deliberately hostile. Apply authority must ignore it.
                "patch_text": "MALICIOUS PATCH CONTENT MUST NEVER BE APPLIED",
            },
        }
    )
    marker = ReceiptGateResult(
        status=marker_status,
        issue_number=42,
        task_id=task.task_id,
        receipt_status=receipt_status,
    )
    return VerifiedReceipt(receipt=receipt, marker=marker)


def remote_snapshot(task: TaskEnvelope, **overrides: bytes | None) -> RemoteSnapshot:
    files: dict[str, bytes | None] = {
        "existing.txt": OLD_BYTES,
        "created.txt": None,
        "deleted.txt": DELETE_BYTES,
    }
    files.update(overrides)
    return RemoteSnapshot(
        base_ref=task.base_ref,
        base_commit_sha=task.base_commit_sha,
        files=files,
    )


class ApplyContractTests(unittest.TestCase):
    def test_remote_base_advance_rejects_verified_worker_result(self) -> None:
        task = valid_task()
        snapshot = RemoteSnapshot(
            base_ref=task.base_ref,
            base_commit_sha="b" * 40,
            files=remote_snapshot(task).files,
        )
        with self.assertRaises(ApplyContractError):
            build_apply_plan(task, verified_receipt(task), snapshot)

    def test_remote_file_hash_change_rejects_apply(self) -> None:
        task = valid_task()
        with self.assertRaises(ApplyContractError):
            build_apply_plan(
                task,
                verified_receipt(task),
                remote_snapshot(task, **{"existing.txt": b"changed remotely\n"}),
            )

    def test_apply_content_comes_from_signed_task_not_patch_text(self) -> None:
        task = valid_task()
        plan = build_apply_plan(task, verified_receipt(task), remote_snapshot(task))
        self.assertEqual(
            [(operation.kind, operation.path, operation.content) for operation in plan.operations],
            [
                ("replace", "existing.txt", "new\n"),
                ("create", "created.txt", "created\n"),
                ("delete", "deleted.txt", None),
            ],
        )
        self.assertNotIn("MALICIOUS PATCH", repr(plan))

    def test_observed_final_hash_must_match_signed_intended_hash(self) -> None:
        task = valid_task()
        wrong = observed_final_hashes()
        wrong["existing.txt"] = sha256_bytes(b"worker-produced-other-content\n")
        with self.assertRaises(ApplyContractError):
            build_apply_plan(task, verified_receipt(task, observed=wrong), remote_snapshot(task))

    def test_unverified_gate_marker_rejects_apply(self) -> None:
        task = valid_task()
        with self.assertRaises(ApplyContractError):
            build_apply_plan(
                task,
                verified_receipt(task, marker_status="UNVERIFIED"),
                remote_snapshot(task),
            )

    def test_non_apply_ready_receipt_rejects_apply_even_with_verified_marker(self) -> None:
        task = valid_task()
        with self.assertRaises(ApplyContractError):
            build_apply_plan(
                task,
                verified_receipt(task, receipt_status="NOT_APPLY_READY"),
                remote_snapshot(task),
            )


if __name__ == "__main__":
    unittest.main()
