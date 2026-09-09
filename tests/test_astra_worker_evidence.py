from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from astra_supervisor.local_executor import ExecutionResult, ExecutionStepResult
from astra_worker.compiler import intended_final_hashes
from astra_worker.evidence import (
    EvidenceError,
    EvidenceLimits,
    build_signed_receipt,
    build_text_patch,
    chunk_patch,
    verify_final_state,
)
from astra_worker.models import ReceiptEnvelope, TaskEnvelope
from astra_worker.protocol import hmac_sha256_hex


def _task(base_sha: str, operations: list[dict], *, max_files: int = 8, max_diff: int = 65536) -> TaskEnvelope:
    return TaskEnvelope.from_mapping(
        {
            "schema_version": "astra.task.v1",
            "task_id": "task-evidence-1",
            "worker_id": "worker-1",
            "repository_id": "cbi-primary",
            "base_ref": "astra-source",
            "base_commit_sha": base_sha,
            "issued_at": "2026-09-09T00:00:00Z",
            "expires_at": "2026-09-09T01:00:00Z",
            "nonce": "nonce-evidence-1",
            "operations": operations,
            "acceptance": {"max_changed_files": max_files, "max_diff_bytes": max_diff},
        }
    )


@unittest.skipUnless(shutil.which("git"), "Git executable required")
class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self._git("init", str(self.root))
        self._git("-C", str(self.root), "config", "user.name", "ASTRA Test")
        self._git("-C", str(self.root), "config", "user.email", "astra@example.invalid")
        (self.root / "tracked.txt").write_bytes(b"before\n")
        (self.root / "delete.txt").write_bytes(b"delete me\n")
        self._git("-C", str(self.root), "add", "tracked.txt", "delete.txt")
        self._git("-C", str(self.root), "commit", "-m", "base")
        self.base_sha = self._git("-C", str(self.root), "rev-parse", "HEAD").stdout.strip().lower()
        self.limits = EvidenceLimits(max_changed_files=20, max_diff_bytes=262144, max_command_output_bytes=256)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [shutil.which("git") or "git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {completed.stderr!r}")
        return completed

    def test_test_created_undeclared_file_quarantines_result(self) -> None:
        task = _task(
            self.base_sha,
            [
                {
                    "kind": "write_text",
                    "path": "tracked.txt",
                    "content": "after\n",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    "expect_absent": False,
                }
            ],
        )
        (self.root / "tracked.txt").write_bytes(b"after\n")
        (self.root / "test-artifact.tmp").write_bytes(b"undeclared\n")
        with self.assertRaises(EvidenceError):
            verify_final_state(task, self.root, intended_final_hashes(task), self.limits)

    def test_declared_file_changed_away_from_signed_content_quarantines(self) -> None:
        task = _task(
            self.base_sha,
            [
                {
                    "kind": "write_text",
                    "path": "tracked.txt",
                    "content": "signed\n",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    "expect_absent": False,
                }
            ],
        )
        (self.root / "tracked.txt").write_bytes(b"different\n")
        with self.assertRaises(EvidenceError):
            verify_final_state(task, self.root, intended_final_hashes(task), self.limits)

    def test_declared_untracked_create_is_verified_and_in_patch(self) -> None:
        task = _task(
            self.base_sha,
            [
                {
                    "kind": "write_text",
                    "path": "new.txt",
                    "content": "created\n",
                    "expect_absent": True,
                }
            ],
        )
        (self.root / "new.txt").write_bytes(b"created\n")
        intended = intended_final_hashes(task)
        evidence = verify_final_state(task, self.root, intended, self.limits)
        patch = build_text_patch(task, self.root, evidence)
        self.assertEqual(evidence.changed_paths, ("new.txt",))
        self.assertEqual(evidence.observed_final_hashes["new.txt"], intended["new.txt"])
        self.assertIn(b"+++ b/new.txt", patch)
        self.assertIn(b"+created", patch)

    def test_binary_diff_is_rejected(self) -> None:
        task = _task(
            self.base_sha,
            [
                {
                    "kind": "delete_file",
                    "path": "tracked.txt",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                }
            ],
        )
        (self.root / "tracked.txt").write_bytes(b"\x00binary\n")
        with self.assertRaises(EvidenceError):
            verify_final_state(task, self.root, {"tracked.txt": hashlib.sha256(b"\x00binary\n").hexdigest()}, self.limits)

    def test_diff_and_changed_file_limits_use_lower_of_local_and_task(self) -> None:
        task_files = _task(
            self.base_sha,
            [
                {
                    "kind": "write_text",
                    "path": "tracked.txt",
                    "content": "after\n",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    "expect_absent": False,
                },
                {
                    "kind": "delete_file",
                    "path": "delete.txt",
                    "expected_sha256": hashlib.sha256(b"delete me\n").hexdigest(),
                },
            ],
            max_files=1,
        )
        (self.root / "tracked.txt").write_bytes(b"after\n")
        (self.root / "delete.txt").unlink()
        with self.assertRaises(EvidenceError):
            verify_final_state(task_files, self.root, intended_final_hashes(task_files), self.limits)

        self._git("-C", str(self.root), "reset", "--hard", "HEAD")
        task_diff = _task(
            self.base_sha,
            [
                {
                    "kind": "write_text",
                    "path": "tracked.txt",
                    "content": "x" * 200 + "\n",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    "expect_absent": False,
                }
            ],
            max_diff=32,
        )
        (self.root / "tracked.txt").write_text("x" * 200 + "\n", encoding="utf-8", newline="")
        with self.assertRaises(EvidenceError):
            verify_final_state(task_diff, self.root, intended_final_hashes(task_diff), self.limits)

    def test_patch_chunk_reorder_changes_bound_hash(self) -> None:
        patch = ("diff --git a/a.txt b/a.txt\n" + "+越南\n" * 20000).encode("utf-8")
        chunks = chunk_patch(patch, max_payload_bytes=4096)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(tuple(chunk.index for chunk in chunks), tuple(range(1, len(chunks) + 1)))
        self.assertTrue(all(len(chunk.text.encode("utf-8")) <= 4096 for chunk in chunks))
        ordered = hashlib.sha256("".join(chunk.sha256 for chunk in chunks).encode("ascii")).hexdigest()
        reordered = hashlib.sha256("".join(chunk.sha256 for chunk in reversed(chunks)).encode("ascii")).hexdigest()
        self.assertNotEqual(ordered, reordered)
        self.assertTrue(all(chunk.patch_sha256 == hashlib.sha256(patch).hexdigest() for chunk in chunks))

    def test_receipt_binds_patch_hash_cleanup_and_bounded_output_without_local_path(self) -> None:
        task = _task(
            self.base_sha,
            [
                {
                    "kind": "write_text",
                    "path": "tracked.txt",
                    "content": "after\n",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    "expect_absent": False,
                }
            ],
        )
        (self.root / "tracked.txt").write_bytes(b"after\n")
        evidence = verify_final_state(task, self.root, intended_final_hashes(task), self.limits)
        patch = build_text_patch(task, self.root, evidence)
        chunks = chunk_patch(patch, max_payload_bytes=128)
        execution = ExecutionResult(
            task_id=task.task_id,
            success=True,
            applied=True,
            steps=(
                ExecutionStepResult(
                    index=1,
                    kind="run",
                    success=True,
                    returncode=0,
                    stdout="O" * 1000,
                    stderr="E" * 1000,
                ),
            ),
        )
        receipt = build_signed_receipt(
            task,
            status="APPLY_READY",
            change_evidence=evidence,
            patch_chunks=chunks,
            cleanup_success=True,
            execution_result=execution,
            max_command_output_bytes=128,
        )
        self.assertIsInstance(receipt, ReceiptEnvelope)
        payload = asdict(receipt)
        rendered = repr(payload)
        self.assertNotIn(str(self.root), rendered)
        self.assertEqual(payload["evidence"]["patch_sha256"], hashlib.sha256(patch).hexdigest())
        self.assertEqual(
            payload["evidence"]["patch_chunk_sha256"],
            [chunk.sha256 for chunk in chunks],
        )
        self.assertTrue(payload["evidence"]["cleanup_success"])
        output = payload["evidence"]["execution"]["steps"][0]["stdout"]
        self.assertTrue(output["truncated"])
        self.assertEqual(output["byte_count"], 1000)
        self.assertEqual(output["sha256"], hashlib.sha256(b"O" * 1000).hexdigest())
        signature = hmac_sha256_hex(b"r" * 32, payload)
        tampered = dict(payload)
        tampered["status"] = "QUARANTINED"
        self.assertNotEqual(signature, hmac_sha256_hex(b"r" * 32, tampered))


if __name__ == "__main__":
    unittest.main()
