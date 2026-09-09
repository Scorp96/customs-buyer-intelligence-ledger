from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from astra_supervisor.local_executor import ExecutionResult
from astra_worker.config import RepositoryBinding, WorkerConfig
from astra_worker.evidence import ChangeEvidence
from astra_worker.git_workspace import CleanupResult, WorktreeHandle
from astra_worker.models import ReceiptEnvelope, TaskEnvelope
from astra_worker.protocol import canonical_json_v1, decode_signed_envelope, verify_hmac_sha256
from astra_worker.queue import ReadyTask
from astra_worker.worker import ReconciliationResult, Worker, WorkerCycleResult


RECEIPT_KEY = b"r" * 32
NOW = datetime(2026, 9, 9, 3, 10, tzinfo=timezone.utc)


def task_mapping(**overrides) -> dict:
    payload = {
        "schema_version": "astra.task.v1",
        "task_id": "worker-task-001",
        "worker_id": "scorp-windows-01",
        "repository_id": "cbi-primary",
        "base_ref": "cbi-v6-3-demand-expansion",
        "base_commit_sha": "a" * 40,
        "issued_at": "2026-09-09T03:00:00Z",
        "expires_at": "2026-09-09T03:30:00Z",
        "nonce": "nonce-worker-001",
        "operations": [
            {
                "kind": "write_text",
                "path": "example.txt",
                "content": "hello\n",
                "expect_absent": True,
            }
        ],
        "acceptance": {"max_changed_files": 5, "max_diff_bytes": 4096},
    }
    payload.update(overrides)
    return payload


def typed_task(**overrides) -> TaskEnvelope:
    return TaskEnvelope.from_mapping(task_mapping(**overrides))


def binding() -> RepositoryBinding:
    return RepositoryBinding(
        repository_id="cbi-primary",
        github_repository="Scorp96/customs-buyer-intelligence-ledger",
        expected_origin="https://github.com/Scorp96/customs-buyer-intelligence-ledger",
        mirror_root=Path("D:/ASTRAWorker/repos/cbi-primary.git"),
        allowed_base_refs_exact=("cbi-v6-3-demand-expansion",),
        allowed_base_ref_prefixes=("astra-",),
        ephemeral_branch_prefix="astra-worker/",
    )


def config() -> WorkerConfig:
    return WorkerConfig(
        schema_version="astra.worker.config.v1",
        worker_id="scorp-windows-01",
        queue_repository="Scorp96/customs-buyer-intelligence-ledger",
        repositories={"cbi-primary": binding()},
        poll_interval_seconds=15,
        max_task_age_seconds=1800,
        max_task_payload_bytes=65536,
        max_operations=16,
        max_changed_files=10,
        max_diff_bytes=65536,
        max_command_output_bytes=4096,
    )


def ready(task: TaskEnvelope, issue_number: int = 42) -> ReadyTask:
    payload = task_mapping(
        task_id=task.task_id,
        worker_id=task.worker_id,
        repository_id=task.repository_id,
        base_ref=task.base_ref,
        base_commit_sha=task.base_commit_sha,
        issued_at=task.issued_at,
        expires_at=task.expires_at,
        nonce=task.nonce,
    )
    digest = hashlib.sha256(canonical_json_v1(payload)).hexdigest()
    return ReadyTask(issue_number=issue_number, task=task, task_digest=digest)


class FakeQueue:
    def __init__(self, tasks: list[ReadyTask]) -> None:
        self.tasks = list(tasks)
        self.find_calls = 0
        self.claimed: list[int] = []
        self.patch_posts: list[tuple[int, str, tuple]] = []
        self.receipts: list[tuple[int, str]] = []

    def find_ready(self, worker_id: str) -> list[ReadyTask]:
        self.find_calls += 1
        return list(self.tasks)

    def claim(self, item: ReadyTask) -> None:
        self.claimed.append(item.issue_number)

    def post_patch_chunks(self, issue_number: int, task_id: str, chunks: tuple) -> None:
        self.patch_posts.append((issue_number, task_id, chunks))

    def post_receipt(self, issue_number: int, signed_receipt: str) -> None:
        self.receipts.append((issue_number, signed_receipt))


class FakeLedger:
    def __init__(self, in_progress=None) -> None:
        self.in_progress = list(in_progress or [])
        self.claimed: list[str] = []
        self.executing: list[str] = []
        self.cleanup: list[tuple[str, str]] = []
        self.terminal: list[tuple[str, str]] = []

    def list_in_progress(self):
        return list(self.in_progress)

    def find_replay(self, task_id: str, nonce: str, digest: str):
        return None

    def claim(self, task_id, nonce, digest, repository_id, base_ref, base_commit_sha):
        self.claimed.append(task_id)
        return SimpleNamespace(task_id=task_id, state="CLAIMED")

    def mark_executing(self, task_id: str, **kwargs):
        self.executing.append(task_id)
        return SimpleNamespace(task_id=task_id, state="EXECUTING")

    def mark_cleanup(self, task_id: str, cleanup_state: str):
        self.cleanup.append((task_id, cleanup_state))
        return SimpleNamespace(task_id=task_id, cleanup_state=cleanup_state)

    def mark_terminal(self, task_id: str, receipt_digest: str, *, terminal_state="TERMINAL"):
        self.terminal.append((task_id, terminal_state))
        return SimpleNamespace(task_id=task_id, state=terminal_state, receipt_digest=receipt_digest)

    def acquire_worker_lease(self, worker_id: str):
        class Lease:
            def __enter__(self_nonlocal):
                return self_nonlocal

            def __exit__(self_nonlocal, exc_type, exc, tb):
                return None

        return Lease()


class FakeWorkspace:
    def __init__(self, root: Path, *, cleanup_success: bool = True) -> None:
        self.root = root
        self.cleanup_success = cleanup_success
        self.sync_calls: list[tuple[str, str]] = []
        self.created: list[str] = []
        self.cleaned: list[str] = []

    def sync_exact(self, base_ref: str, base_sha: str) -> None:
        self.sync_calls.append((base_ref, base_sha))

    def create_task_worktree(self, task_id: str, base_sha: str) -> WorktreeHandle:
        self.created.append(task_id)
        return WorktreeHandle(
            task_id=task_id,
            path=self.root,
            branch="astra-worker/worker-task",
            base_commit_sha=base_sha,
            mirror_identity=f"cbi-primary@{base_sha}",
        )

    def cleanup(self, handle: WorktreeHandle) -> CleanupResult:
        self.cleaned.append(handle.task_id)
        if self.cleanup_success:
            return CleanupResult(True, True, True, None)
        return CleanupResult(False, False, False, "simulated cleanup failure")


class FakeCompiler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def compile(self, task: TaskEnvelope, worktree: Path, expected_branch: str):
        self.calls.append(task.task_id)
        return SimpleNamespace(task_id=task.task_id)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, manifest, apply=False) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(
            task_id=manifest.task_id,
            success=True,
            applied=bool(apply),
            steps=(),
        )


class WorkerTests(unittest.TestCase):
    def _worker(
        self,
        root: Path,
        *,
        tasks=None,
        ledger=None,
        workspace=None,
        executor=None,
        disabled_marker=None,
    ) -> tuple[Worker, FakeQueue, FakeLedger, FakeWorkspace, FakeExecutor]:
        queue = FakeQueue(list(tasks or []))
        ledger = ledger or FakeLedger()
        workspace = workspace or FakeWorkspace(root)
        executor = executor or FakeExecutor()
        worker = Worker(
            config=config(),
            queue=queue,
            ledger=ledger,
            workspace_factory=lambda _binding: workspace,
            compiler=FakeCompiler(),
            executor=executor,
            disabled_marker=disabled_marker or (root / "DISABLED"),
            receipt_key=RECEIPT_KEY,
            now=lambda: NOW,
        )
        return worker, queue, ledger, workspace, executor

    def test_disabled_marker_prevents_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "DISABLED"
            marker.write_text("disabled\n", encoding="utf-8")
            worker, queue, ledger, _workspace, executor = self._worker(
                root,
                tasks=[ready(typed_task())],
                disabled_marker=marker,
            )
            result = worker.run_once()
            self.assertIsInstance(result, WorkerCycleResult)
            self.assertEqual(result.status, "DISABLED")
            self.assertEqual(queue.find_calls, 0)
            self.assertEqual(queue.claimed, [])
            self.assertEqual(ledger.claimed, [])
            self.assertEqual(executor.calls, 0)

    def test_only_one_task_executes_per_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = typed_task()
            second = typed_task(task_id="worker-task-002", nonce="nonce-worker-002")
            worker, queue, ledger, workspace, executor = self._worker(
                root,
                tasks=[ready(first, 42), ready(second, 43)],
            )
            intended = {"example.txt": hashlib.sha256(b"hello\n").hexdigest()}
            evidence = ChangeEvidence(
                changed_paths=("example.txt",),
                observed_final_hashes=intended,
                patch_sha256=hashlib.sha256(b"").hexdigest(),
                diff_bytes=0,
            )
            with (
                patch("astra_worker.worker.verify_pre_state", return_value=None),
                patch("astra_worker.worker.verify_final_state", return_value=evidence),
                patch("astra_worker.worker.build_text_patch", return_value=b""),
            ):
                result = worker.run_once()
            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(queue.claimed, [42])
            self.assertEqual(ledger.claimed, [first.task_id])
            self.assertEqual(ledger.executing, [first.task_id])
            self.assertEqual(executor.calls, 1)
            self.assertEqual(workspace.created, [first.task_id])
            self.assertEqual(queue.patch_posts[0][0], 42)
            self.assertEqual(len(queue.receipts), 1)
            self.assertNotIn(second.task_id, ledger.claimed)

    def test_ambiguous_crash_is_quarantined_not_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = SimpleNamespace(
                task_id="crashed-task",
                state="EXECUTING",
                repository_id="cbi-primary",
                base_ref="cbi-v6-3-demand-expansion",
                base_commit_sha="a" * 40,
                mirror_identity="cbi-primary@" + "a" * 40,
                worktree=str(root),
                generated_branch="astra-worker/crashed-task",
            )
            ledger = FakeLedger([record])
            executor = FakeExecutor()
            worker, queue, ledger, workspace, executor = self._worker(
                root,
                ledger=ledger,
                executor=executor,
            )
            results = worker.reconcile_in_progress()
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], ReconciliationResult)
            self.assertEqual(results[0].status, "QUARANTINED")
            self.assertEqual(executor.calls, 0)
            self.assertEqual(queue.claimed, [])
            self.assertEqual(ledger.terminal, [("crashed-task", "QUARANTINED")])

    def test_cleanup_failure_forces_quarantined_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = typed_task()
            workspace = FakeWorkspace(root, cleanup_success=False)
            worker, queue, ledger, workspace, executor = self._worker(
                root,
                tasks=[ready(task)],
                workspace=workspace,
            )
            intended = {"example.txt": hashlib.sha256(b"hello\n").hexdigest()}
            evidence = ChangeEvidence(
                changed_paths=("example.txt",),
                observed_final_hashes=intended,
                patch_sha256=hashlib.sha256(b"").hexdigest(),
                diff_bytes=0,
            )
            with (
                patch("astra_worker.worker.verify_pre_state", return_value=None),
                patch("astra_worker.worker.verify_final_state", return_value=evidence),
                patch("astra_worker.worker.build_text_patch", return_value=b""),
            ):
                result = worker.run_once()
            self.assertEqual(result.status, "QUARANTINED")
            self.assertEqual(ledger.terminal, [(task.task_id, "QUARANTINED")])
            self.assertEqual(len(queue.receipts), 1)
            payload, signature = decode_signed_envelope(queue.receipts[0][1], "receipt")
            verify_hmac_sha256(RECEIPT_KEY, payload, signature)
            receipt = ReceiptEnvelope.from_mapping(payload)
            self.assertEqual(receipt.status, "QUARANTINED")
            self.assertFalse(receipt.evidence["cleanup_success"])

    def test_expired_task_is_rejected_before_local_or_remote_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expired = typed_task(
                issued_at="2026-09-09T02:00:00Z",
                expires_at="2026-09-09T02:30:00Z",
            )
            worker, queue, ledger, _workspace, executor = self._worker(
                root,
                tasks=[ready(expired)],
            )
            result = worker.run_once()
            self.assertEqual(result.status, "REJECTED")
            self.assertEqual(queue.claimed, [])
            self.assertEqual(ledger.claimed, [])
            self.assertEqual(executor.calls, 0)

    def test_worker_source_has_no_inbound_listener(self) -> None:
        source = Path("astra_worker/worker.py").read_text(encoding="utf-8")
        for forbidden in ("http.server", "socketserver", "listen(", "bind("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
