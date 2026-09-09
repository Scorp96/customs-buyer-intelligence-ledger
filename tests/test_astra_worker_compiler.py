from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from astra_supervisor.local_executor import LocalExecutor
from astra_worker.compiler import CompilerError, TaskCompiler, intended_final_hashes, verify_pre_state
from astra_worker.models import TaskEnvelope


def _task(operations: list[dict]) -> TaskEnvelope:
    return TaskEnvelope.from_mapping(
        {
            "schema_version": "astra.task.v1",
            "task_id": "task-compiler-1",
            "worker_id": "worker-1",
            "repository_id": "cbi-primary",
            "base_ref": "astra-source",
            "base_commit_sha": "1" * 40,
            "issued_at": "2026-09-09T00:00:00Z",
            "expires_at": "2026-09-09T01:00:00Z",
            "nonce": "nonce-compiler-1",
            "operations": operations,
            "acceptance": {"max_changed_files": 8, "max_diff_bytes": 65536},
        }
    )


class CompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.worktree = Path(self._td.name).resolve()

    def test_existing_write_precondition_hashes_raw_bytes(self) -> None:
        target = self.worktree / "payload.bin"
        original = b"\x00\xff\r\nraw-bytes\n"
        target.write_bytes(original)
        task = _task(
            [
                {
                    "kind": "write_text",
                    "path": "payload.bin",
                    "content": "replacement\n",
                    "expected_sha256": hashlib.sha256(original).hexdigest(),
                    "expect_absent": False,
                }
            ]
        )
        verify_pre_state(task, self.worktree)

        target.write_bytes(original + b"drift")
        with self.assertRaises(CompilerError):
            verify_pre_state(task, self.worktree)

    def test_expect_absent_write_rejects_existing_path(self) -> None:
        (self.worktree / "new.txt").write_text("already here", encoding="utf-8")
        task = _task(
            [
                {
                    "kind": "write_text",
                    "path": "new.txt",
                    "content": "signed content\n",
                    "expected_sha256": None,
                    "expect_absent": True,
                }
            ]
        )
        with self.assertRaises(CompilerError):
            verify_pre_state(task, self.worktree)

    def test_delete_precondition_rejects_hash_mismatch(self) -> None:
        (self.worktree / "old.txt").write_text("actual\n", encoding="utf-8")
        task = _task(
            [
                {
                    "kind": "delete_file",
                    "path": "old.txt",
                    "expected_sha256": hashlib.sha256(b"expected\n").hexdigest(),
                }
            ]
        )
        with self.assertRaises(CompilerError):
            verify_pre_state(task, self.worktree)

    def test_intended_final_hashes_bind_exact_utf8_and_delete_state(self) -> None:
        old_sha = hashlib.sha256(b"old\n").hexdigest()
        task = _task(
            [
                {
                    "kind": "write_text",
                    "path": "unicode.txt",
                    "content": "越南\n",
                    "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    "expect_absent": False,
                },
                {
                    "kind": "delete_file",
                    "path": "old.txt",
                    "expected_sha256": old_sha,
                },
            ]
        )
        self.assertEqual(
            intended_final_hashes(task),
            {
                "unicode.txt": hashlib.sha256("越南\n".encode("utf-8")).hexdigest(),
                "old.txt": None,
            },
        )

    def test_compile_translates_mutations_into_phase1_manifest(self) -> None:
        before = b"before\n"
        (self.worktree / "a.txt").write_bytes(before)
        (self.worktree / "b.txt").write_bytes(b"delete me\n")
        task = _task(
            [
                {
                    "kind": "write_text",
                    "path": "a.txt",
                    "content": "after\n",
                    "expected_sha256": hashlib.sha256(before).hexdigest(),
                    "expect_absent": False,
                },
                {
                    "kind": "delete_file",
                    "path": "b.txt",
                    "expected_sha256": hashlib.sha256(b"delete me\n").hexdigest(),
                },
            ]
        )
        manifest = TaskCompiler().compile(task, self.worktree, "astra-worker/test")
        self.assertEqual(manifest.task_id, task.task_id)
        self.assertEqual(manifest.repository_root.resolve(), self.worktree)
        self.assertEqual(manifest.expected_branch, "astra-worker/test")
        self.assertEqual([operation.kind for operation in manifest.operations], ["write_text", "delete_file"])
        self.assertEqual(manifest.operations[0].path, "a.txt")
        self.assertEqual(manifest.operations[0].content, "after\n")
        self.assertEqual(manifest.operations[1].path, "b.txt")

    @unittest.skipUnless(shutil.which("git"), "Git executable required")
    def test_unittest_compiles_to_current_python_and_phase1_validator(self) -> None:
        self._init_git_worktree()
        (self.worktree / "sample_test.py").write_text(
            "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        task = _task(
            [
                {
                    "kind": "run_unittest",
                    "targets": ["sample_test"],
                    "flags": ["-v"],
                }
            ]
        )
        manifest = TaskCompiler().compile(task, self.worktree, "astra-worker/test")
        operation = manifest.operations[0]
        self.assertEqual(operation.argv[:3], (sys.executable, "-m", "unittest"))
        self.assertEqual(operation.argv[3:], ("-v", "sample_test"))
        result = LocalExecutor().execute(manifest, apply=False)
        self.assertTrue(result.success)
        self.assertFalse(result.applied)

    @unittest.skipUnless(shutil.which("git"), "Git executable required")
    def test_compileall_compiles_to_current_python_and_phase1_validator(self) -> None:
        self._init_git_worktree()
        package = self.worktree / "pkg"
        package.mkdir()
        (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        task = _task(
            [
                {
                    "kind": "run_compileall",
                    "targets": ["pkg"],
                    "flags": ["-q"],
                }
            ]
        )
        manifest = TaskCompiler().compile(task, self.worktree, "astra-worker/test")
        operation = manifest.operations[0]
        self.assertEqual(operation.argv[:3], (sys.executable, "-m", "compileall"))
        self.assertEqual(operation.argv[3:], ("-q", "pkg"))
        result = LocalExecutor().execute(manifest, apply=False)
        self.assertTrue(result.success)
        self.assertFalse(result.applied)

    def _init_git_worktree(self) -> None:
        git = shutil.which("git") or "git"
        commands = [
            [git, "init", str(self.worktree)],
            [git, "-C", str(self.worktree), "config", "user.name", "ASTRA Test"],
            [git, "-C", str(self.worktree), "config", "user.email", "astra@example.invalid"],
            [git, "-C", str(self.worktree), "checkout", "-b", "astra-worker/test"],
        ]
        for command in commands:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
            if completed.returncode != 0:
                self.fail(f"git command failed: {command!r}: {completed.stderr}")


if __name__ == "__main__":
    unittest.main()
