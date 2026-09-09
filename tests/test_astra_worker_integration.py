from __future__ import annotations

from datetime import datetime, timezone
import hashlib
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
    verify_hmac_sha256,
)
from astra_worker.queue import ReadyTask
from astra_worker.worker import Worker


RECEIPT_KEY = b"r" * 32
NOW = datetime(2026, 9, 9, 7, 15, tzinfo=timezone.utc)


class IntegrationQueue:
    def __init__(self, item: ReadyTask) -> None:
        self.item = item
        self.claimed: list[int] = []
        self.patch_posts: list[tuple[int, str, tuple]] = []
        self.receipts: list[tuple[int, str]] = []

    def find_ready(self, worker_id: str) -> list[ReadyTask]:
        if self.item.task.worker_id != worker_id:
            return []
        return [self.item]

    def claim(self, item: ReadyTask) -> None:
        self.claimed.append(item.issue_number)

    def post_patch_chunks(self, issue_number: int, task_id: str, chunks: tuple) -> None:
        self.patch_posts.append((issue_number, task_id, chunks))

    def post_receipt(self, issue_number: int, signed_receipt: str) -> None:
        self.receipts.append((issue_number, signed_receipt))


@unittest.skipUnless(shutil.which("git"), "Git executable required")
class Phase2IntegrationTests(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> str:
        completed = subprocess.run(
            [shutil.which("git") or "git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def _initialize_developer_checkout(self, root: Path) -> tuple[str, bytes]:
        root.mkdir(parents=True)
        completed = subprocess.run(
            [shutil.which("git") or "git", "init", str(root)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self._git(root, "config", "user.name", "ASTRA Integration")
        self._git(root, "config", "user.email", "astra-integration@example.invalid")
        self._git(root, "checkout", "-b", "astra-base")

        original = b'VALUE = "old"\n'
        (root / "module.py").write_bytes(original)
        tests = root / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "test_module.py").write_text(
            "import unittest\n"
            "import module\n\n"
            "class ModuleTest(unittest.TestCase):\n"
            "    def test_worker_applied_signed_content(self):\n"
            "        self.assertEqual(module.VALUE, 'new')\n",
            encoding="utf-8",
        )
        self._git(root, "add", "module.py", "tests/__init__.py", "tests/test_module.py")
        self._git(root, "commit", "-m", "integration base")
        return self._git(root, "rev-parse", "HEAD"), original

    def test_real_worker_round_trip_isolated_from_developer_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            outer = Path(temporary).resolve()
            developer = outer / "developer"
            worker_state = outer / "worker-state"
            worker_state.mkdir()
            base_sha, original = self._initialize_developer_checkout(developer)
            source_status_before = self._git(developer, "status", "--porcelain", "--untracked-files=all")
            source_branches_before = self._git(developer, "branch", "--format=%(refname:short)")

            binding = RepositoryBinding(
                repository_id="cbi-primary",
                github_repository="Scorp96/customs-buyer-intelligence-ledger",
                expected_origin=developer.as_uri(),
                mirror_root=worker_state / "repos" / "cbi-primary.git",
                allowed_base_refs_exact=("astra-base",),
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
                max_changed_files=4,
                max_diff_bytes=65536,
                max_command_output_bytes=8192,
            )

            replacement = 'VALUE = "new"\n'
            task_payload = {
                "schema_version": "astra.task.v1",
                "task_id": "integration-task-001",
                "worker_id": "scorp-windows-01",
                "repository_id": "cbi-primary",
                "base_ref": "astra-base",
                "base_commit_sha": base_sha,
                "issued_at": "2026-09-09T07:00:00Z",
                "expires_at": "2026-09-09T07:30:00Z",
                "nonce": "integration-nonce-001",
                "operations": [
                    {
                        "kind": "write_text",
                        "path": "module.py",
                        "content": replacement,
                        "expected_sha256": hashlib.sha256(original).hexdigest(),
                        "expect_absent": False,
                    },
                    {
                        "kind": "run_unittest",
                        "targets": ["tests.test_module"],
                        "flags": ["-q"],
                    },
                ],
                "acceptance": {"max_changed_files": 1, "max_diff_bytes": 65536},
            }
            task = TaskEnvelope.from_mapping(task_payload)
            task_digest = hashlib.sha256(canonical_json_v1(task_payload)).hexdigest()
            item = ReadyTask(issue_number=901, task=task, task_digest=task_digest)
            queue = IntegrationQueue(item)

            with TaskLedger(worker_state / "ledger.sqlite") as ledger:
                worker = Worker(
                    config=config,
                    queue=queue,
                    ledger=ledger,
                    workspace_factory=lambda repo_binding: GitWorkspaceManager(
                        repo_binding,
                        token="",
                        git_executable=shutil.which("git") or "git",
                    ),
                    compiler=TaskCompiler(),
                    executor=LocalExecutor(),
                    disabled_marker=worker_state / "DISABLED",
                    receipt_key=RECEIPT_KEY,
                    now=lambda: NOW,
                )

                first = worker.run_once()
                self.assertEqual(first.status, "COMPLETED", first.detail)
                second = worker.run_once()
                self.assertEqual(second.status, "REPLAY_BLOCKED", second.detail)

            self.assertEqual(queue.claimed, [901])
            self.assertEqual(len(queue.patch_posts), 1)
            self.assertEqual(len(queue.receipts), 1)

            chunks = queue.patch_posts[0][2]
            patch_bytes = "".join(chunk.text for chunk in chunks).encode("utf-8")
            self.assertIn(b'-VALUE = "old"', patch_bytes)
            self.assertIn(b'+VALUE = "new"', patch_bytes)

            payload, signature = decode_signed_envelope(queue.receipts[0][1], "receipt")
            verify_hmac_sha256(RECEIPT_KEY, payload, signature)
            receipt = ReceiptEnvelope.from_mapping(payload)
            expected_final_sha = hashlib.sha256(replacement.encode("utf-8")).hexdigest()
            self.assertEqual(receipt.status, "APPLY_READY")
            self.assertTrue(receipt.evidence["cleanup_success"])
            self.assertEqual(receipt.evidence["changed_paths"], ["module.py"])
            self.assertEqual(receipt.evidence["observed_final_hashes"]["module.py"], expected_final_sha)
            self.assertEqual(receipt.evidence["patch_sha256"], hashlib.sha256(patch_bytes).hexdigest())

            self.assertEqual((developer / "module.py").read_bytes(), original)
            self.assertEqual(self._git(developer, "rev-parse", "HEAD"), base_sha)
            self.assertEqual(
                self._git(developer, "status", "--porcelain", "--untracked-files=all"),
                source_status_before,
            )
            self.assertEqual(
                self._git(developer, "branch", "--format=%(refname:short)"),
                source_branches_before,
            )

            worktree_root = worker_state / "worktrees" / "cbi-primary"
            if worktree_root.exists():
                self.assertEqual(list(worktree_root.iterdir()), [])
            generated = subprocess.run(
                [
                    shutil.which("git") or "git",
                    "--git-dir",
                    str(binding.mirror_root),
                    "branch",
                    "--list",
                    "astra-worker/*",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.assertEqual(generated.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
