from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from astra_supervisor.local_executor import LocalExecutor
from astra_worker.compiler import TaskCompiler
from astra_worker.config import RepositoryBinding, WorkerConfig
from astra_worker.git_workspace import GitWorkspaceManager
from astra_worker.ledger import TaskLedger
from astra_worker.models import ReceiptEnvelope, TaskEnvelope
from astra_worker.protocol import (
    canonical_json_v1,
    decode_signed_envelope,
    encode_signed_envelope,
    hmac_sha256_hex,
    verify_hmac_sha256,
)
from astra_worker.queue import ReadyTask
from astra_worker.worker import Worker


TASK_KEY = b"t" * 32
RECEIPT_KEY = b"r" * 32
NOW = datetime(2026, 9, 9, 7, 15, tzinfo=timezone.utc)
BASE_REF = "astra-e2e-base"


def run_git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    if not git:
        raise unittest.SkipTest("Git is required for integrated worker acceptance")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("GIT_", "SSH_", "GCM_"))
    }
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        [git, *args],
        cwd=str(root),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Git fixture command failed ({completed.returncode}): {completed.stderr or completed.stdout}"
        )
    return completed.stdout.strip()


def snapshot_checkout(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts or not path.is_file():
            continue
        snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


class SignedFakeQueue:
    """Fake transport that still authenticates the task with the real protocol."""

    def __init__(self, signed_task: str) -> None:
        self.signed_task = signed_task
        self.claimed: list[int] = []
        self.patch_posts: list[tuple[int, str, tuple]] = []
        self.receipts: list[tuple[int, str]] = []

    def find_ready(self, worker_id: str) -> list[ReadyTask]:
        payload, signature = decode_signed_envelope(self.signed_task, "task")
        verify_hmac_sha256(TASK_KEY, payload, signature)
        task = TaskEnvelope.from_mapping(payload)
        if task.worker_id != worker_id:
            return []
        digest = hashlib.sha256(canonical_json_v1(payload)).hexdigest()
        return [ReadyTask(issue_number=77, task=task, task_digest=digest)]

    def claim(self, item: ReadyTask) -> None:
        self.claimed.append(item.issue_number)

    def post_patch_chunks(self, issue_number: int, task_id: str, chunks: tuple) -> None:
        self.patch_posts.append((issue_number, task_id, chunks))

    def post_receipt(self, issue_number: int, signed_receipt: str) -> None:
        self.receipts.append((issue_number, signed_receipt))


class ObservingWorkspace(GitWorkspaceManager):
    """Real workspace manager with read-only observations immediately before cleanup."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.observed_feature: bytes | None = None
        self.status_before_cleanup: str | None = None
        self.last_worktree: Path | None = None
        self.last_branch: str | None = None

    def create_task_worktree(self, task_id: str, base_sha: str):
        handle = super().create_task_worktree(task_id, base_sha)
        self.last_worktree = handle.path
        self.last_branch = handle.branch
        return handle

    def cleanup(self, handle):
        if handle.path.is_dir():
            self.status_before_cleanup = run_git(
                handle.path,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            )
        feature = handle.path / "feature.py"
        if feature.is_file():
            self.observed_feature = feature.read_bytes()
        return super().cleanup(handle)


class IntegratedWorkerAcceptanceTests(unittest.TestCase):
    def test_signed_task_runs_real_worker_executor_evidence_receipt_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="astra-worker-e2e-") as temporary:
            root = Path(temporary).resolve()
            source = root / "developer-checkout"
            source.mkdir()
            run_git(source, "init")
            run_git(source, "config", "user.name", "ASTRA E2E")
            run_git(source, "config", "user.email", "astra-e2e@example.invalid")
            run_git(source, "checkout", "-b", BASE_REF)

            tests_dir = source / "tests"
            tests_dir.mkdir()
            (tests_dir / "__init__.py").write_text("", encoding="utf-8")
            (tests_dir / "test_feature.py").write_text(
                "import unittest\n"
                "import feature\n\n"
                "class FeatureTests(unittest.TestCase):\n"
                "    def test_signed_change_is_active(self):\n"
                "        self.assertEqual(feature.VALUE, 'after')\n",
                encoding="utf-8",
            )
            run_git(source, "add", "tests")
            run_git(source, "commit", "-m", "fixture: add acceptance test")
            base_sha = run_git(source, "rev-parse", "HEAD").lower()
            developer_before = snapshot_checkout(source)

            feature_content = "VALUE = 'after'\n"
            payload = {
                "schema_version": "astra.task.v1",
                "task_id": "integrated-e2e-001",
                "worker_id": "scorp-windows-01",
                "repository_id": "cbi-primary",
                "base_ref": BASE_REF,
                "base_commit_sha": base_sha,
                "issued_at": "2026-09-09T07:00:00Z",
                "expires_at": "2026-09-09T07:30:00Z",
                "nonce": "integrated-e2e-nonce-001",
                "operations": [
                    {
                        "kind": "write_text",
                        "path": "feature.py",
                        "content": feature_content,
                        "expect_absent": True,
                    },
                    {
                        "kind": "run_unittest",
                        "targets": ["tests.test_feature"],
                        "flags": ["-v"],
                    },
                ],
                "acceptance": {"max_changed_files": 1, "max_diff_bytes": 65536},
            }
            task_signature = hmac_sha256_hex(TASK_KEY, payload)
            signed_task = encode_signed_envelope("task", payload, task_signature)
            queue = SignedFakeQueue(signed_task)

            worker_root = root / "worker"
            mirror_root = worker_root / "repos" / "cbi-primary.git"
            mirror_root.parent.mkdir(parents=True)
            binding = RepositoryBinding(
                repository_id="cbi-primary",
                github_repository="Scorp96/customs-buyer-intelligence-ledger",
                expected_origin=str(source),
                mirror_root=mirror_root,
                allowed_base_refs_exact=(BASE_REF,),
                allowed_base_ref_prefixes=(),
                ephemeral_branch_prefix="astra-worker/",
            )
            config = WorkerConfig(
                schema_version="astra.worker.config.v1",
                worker_id="scorp-windows-01",
                queue_repository="Scorp96/customs-buyer-intelligence-ledger",
                repositories={"cbi-primary": binding},
                poll_interval_seconds=15,
                max_task_age_seconds=1800,
                max_task_payload_bytes=65536,
                max_operations=16,
                max_changed_files=5,
                max_diff_bytes=65536,
                max_command_output_bytes=16384,
            )
            workspace = ObservingWorkspace(binding, "", "git")
            ledger = TaskLedger(worker_root / "ledger.sqlite")
            try:
                worker = Worker(
                    config=config,
                    queue=queue,
                    ledger=ledger,
                    workspace_factory=lambda _binding: workspace,
                    compiler=TaskCompiler(),
                    executor=LocalExecutor(),
                    disabled_marker=worker_root / "DISABLED",
                    receipt_key=RECEIPT_KEY,
                    now=lambda: NOW,
                )
                result = worker.run_once()
            finally:
                ledger.close()

            self.assertEqual(
                result.status,
                "COMPLETED",
                f"{result.detail}; cleanup-prestatus={workspace.status_before_cleanup!r}",
            )
            self.assertEqual(workspace.status_before_cleanup, "?? feature.py")
            self.assertEqual(workspace.observed_feature, feature_content.encode("utf-8"))
            self.assertEqual(queue.claimed, [77])
            self.assertEqual(len(queue.patch_posts), 1)
            self.assertEqual(len(queue.receipts), 1)

            issue_number, signed_receipt = queue.receipts[0]
            self.assertEqual(issue_number, 77)
            receipt_payload, receipt_signature = decode_signed_envelope(signed_receipt, "receipt")
            verify_hmac_sha256(RECEIPT_KEY, receipt_payload, receipt_signature)
            receipt = ReceiptEnvelope.from_mapping(receipt_payload)
            self.assertEqual(receipt.status, "APPLY_READY")
            self.assertTrue(receipt.evidence["cleanup_success"])
            self.assertEqual(receipt.evidence["changed_paths"], ["feature.py"])
            expected_final_hash = hashlib.sha256(feature_content.encode("utf-8")).hexdigest()
            self.assertEqual(receipt.evidence["observed_final_hashes"], {"feature.py": expected_final_hash})
            self.assertTrue(receipt.evidence["execution"]["success"])
            run_steps = [
                step
                for step in receipt.evidence["execution"]["steps"]
                if step["kind"] == "run"
            ]
            self.assertEqual(len(run_steps), 1)
            self.assertTrue(run_steps[0]["success"])
            self.assertEqual(run_steps[0]["returncode"], 0)

            chunks = queue.patch_posts[0][2]
            patch_bytes = "".join(chunk.text for chunk in chunks).encode("utf-8")
            self.assertEqual(hashlib.sha256(patch_bytes).hexdigest(), receipt.evidence["patch_sha256"])
            self.assertEqual(
                [chunk.sha256 for chunk in chunks],
                receipt.evidence["patch_chunk_sha256"],
            )
            self.assertIn(b"+VALUE = 'after'", patch_bytes)

            self.assertEqual(snapshot_checkout(source), developer_before)
            self.assertIsNotNone(workspace.last_worktree)
            self.assertFalse(workspace.last_worktree.exists())
            self.assertIsNotNone(workspace.last_branch)
            branch_probe = subprocess.run(
                [
                    shutil.which("git") or "git",
                    "--git-dir",
                    str(mirror_root),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{workspace.last_branch}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(branch_probe.returncode, 1, branch_probe.stderr)


if __name__ == "__main__":
    unittest.main()
