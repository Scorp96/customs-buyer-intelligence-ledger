import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from astra_supervisor import (
    ExecutionManifest,
    ExecutorAvailability,
    ExecutorName,
    LocalExecutionError,
    LocalExecutor,
    ManifestValidationError,
    NoExecutorAvailable,
    TaskKind,
    select_executor,
)
from astra_supervisor.cli import main as cli_main


class ExecutorPolicyTests(unittest.TestCase):
    def test_repository_edit_prefers_github(self):
        availability = ExecutorAvailability(github=True, codex=True, local=True)
        self.assertEqual(
            select_executor(TaskKind.REPOSITORY_EDIT, availability),
            ExecutorName.GITHUB,
        )

    def test_repository_edit_falls_back_to_codex_then_local(self):
        self.assertEqual(
            select_executor(
                TaskKind.REPOSITORY_EDIT,
                ExecutorAvailability(codex=True, local=True),
            ),
            ExecutorName.CODEX,
        )
        self.assertEqual(
            select_executor(
                TaskKind.REPOSITORY_EDIT,
                ExecutorAvailability(local=True),
            ),
            ExecutorName.LOCAL,
        )

    def test_local_workspace_never_selects_github(self):
        self.assertEqual(
            select_executor(
                TaskKind.LOCAL_WORKSPACE,
                ExecutorAvailability(github=True, codex=False, local=True),
            ),
            ExecutorName.LOCAL,
        )

    def test_review_only_needs_no_executor(self):
        self.assertEqual(
            select_executor(TaskKind.REVIEW_ONLY, ExecutorAvailability()),
            ExecutorName.NONE,
        )

    def test_no_eligible_executor_fails_closed(self):
        with self.assertRaises(NoExecutorAvailable):
            select_executor(
                TaskKind.LOCAL_WORKSPACE,
                ExecutorAvailability(github=True),
            )


class ManifestValidationTests(unittest.TestCase):
    def _base(self):
        return {
            "task_id": "task-1",
            "repository_root": ".",
            "expected_branch": "astra-test",
            "operations": [],
        }

    def test_rejects_empty_task_id(self):
        payload = self._base()
        payload["task_id"] = ""
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)

    def test_rejects_path_traversal(self):
        payload = self._base()
        payload["operations"] = [
            {"kind": "write_text", "path": "../outside.txt", "content": "x"}
        ]
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)

    def test_rejects_absolute_path(self):
        payload = self._base()
        absolute = str(Path(os.path.abspath(os.sep)) / "outside.txt")
        payload["operations"] = [
            {"kind": "write_text", "path": absolute, "content": "x"}
        ]
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)

    def test_rejects_git_metadata_write(self):
        payload = self._base()
        payload["operations"] = [
            {"kind": "write_text", "path": ".git/config", "content": "x"}
        ]
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)

    def test_rejects_nested_git_metadata_write(self):
        payload = self._base()
        payload["operations"] = [
            {"kind": "write_text", "path": "nested/.git/config", "content": "x"}
        ]
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)

    def test_rejects_unknown_operation(self):
        payload = self._base()
        payload["operations"] = [{"kind": "launch_missiles"}]
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)

    def test_rejects_string_argv(self):
        payload = self._base()
        payload["operations"] = [
            {"kind": "run", "argv": "python -m unittest", "cwd": "."}
        ]
        with self.assertRaises(ManifestValidationError):
            ExecutionManifest.from_dict(payload)


class LocalExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "repo"
        self.root.mkdir()
        self._git("init", "-b", "astra-test")
        self._git("config", "user.email", "astra-test@example.invalid")
        self._git("config", "user.name", "ASTRA Test")
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        (self.root / "test_generated.py").write_text(
            "import unittest\n\n"
            "class GeneratedTests(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        import generated\n"
            "        self.assertEqual(generated.VALUE, 42)\n",
            encoding="utf-8",
        )
        self._git("add", "README.md", "test_generated.py")
        self._git("commit", "-m", "baseline")

    def tearDown(self):
        self.tempdir.cleanup()

    def _git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _manifest(self, operations, expected_branch="astra-test"):
        return ExecutionManifest.from_dict(
            {
                "task_id": "local-test",
                "repository_root": str(self.root),
                "expected_branch": expected_branch,
                "operations": operations,
            }
        )

    def test_dry_run_does_not_mutate(self):
        manifest = self._manifest(
            [{"kind": "write_text", "path": "generated.py", "content": "VALUE = 42\n"}]
        )
        result = LocalExecutor().execute(manifest, apply=False)
        self.assertTrue(result.success)
        self.assertFalse(result.applied)
        self.assertFalse((self.root / "generated.py").exists())

    def test_apply_rejects_protected_branch(self):
        self._git("branch", "-M", "main")
        manifest = self._manifest([], expected_branch="main")
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=True)

    def test_apply_rejects_expected_branch_mismatch(self):
        manifest = self._manifest([], expected_branch="different-branch")
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=True)

    def test_apply_rejects_dirty_tree(self):
        (self.root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        manifest = self._manifest([])
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=True)

    def test_apply_writes_file_and_runs_unittest(self):
        manifest = self._manifest(
            [
                {"kind": "write_text", "path": "generated.py", "content": "VALUE = 42\n"},
                {
                    "kind": "run",
                    "argv": [sys.executable, "-m", "unittest", "test_generated.py", "-v"],
                    "cwd": ".",
                },
            ]
        )
        result = LocalExecutor().execute(manifest, apply=True)
        self.assertTrue(result.success)
        self.assertTrue(result.applied)
        self.assertEqual((self.root / "generated.py").read_text(encoding="utf-8"), "VALUE = 42\n")
        self.assertEqual(result.steps[-1].returncode, 0)

    def test_rejects_python_c(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": [sys.executable, "-c", "print('unsafe')"], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_python_lookalike_executable(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": ["python-malicious", "-m", "unittest", "test_generated.py"], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_unittest_absolute_target(self):
        absolute = str(Path(self.tempdir.name) / "outside_test.py")
        manifest = self._manifest(
            [{"kind": "run", "argv": [sys.executable, "-m", "unittest", absolute], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_compileall_absolute_target(self):
        absolute = str(Path(self.tempdir.name) / "outside")
        manifest = self._manifest(
            [{"kind": "run", "argv": [sys.executable, "-m", "compileall", absolute], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_shell_executable(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": ["bash", "-c", "echo unsafe"], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_git_push(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": ["git", "push"], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_git_output_option(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": ["git", "diff", "--output=../outside.patch"], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_git_external_diff_option(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": ["git", "diff", "--ext-diff"], "cwd": "."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)

    def test_rejects_escaped_cwd(self):
        manifest = self._manifest(
            [{"kind": "run", "argv": ["git", "status"], "cwd": ".."}]
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=False)


class CliTests(unittest.TestCase):
    def test_cli_dry_run_writes_structured_result(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init", "-b", "astra-test"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "astra-test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "ASTRA Test"], check=True)
            (root / "README.md").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "baseline"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            manifest_path = Path(td) / "manifest.json"
            result_path = Path(td) / "result.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "task_id": "cli-test",
                        "repository_root": str(root),
                        "expected_branch": "astra-test",
                        "operations": [
                            {"kind": "write_text", "path": "generated.py", "content": "VALUE = 42\n"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code = cli_main(["--manifest", str(manifest_path), "--result", str(result_path)])
            self.assertEqual(code, 0)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["success"])
            self.assertFalse(payload["applied"])
            self.assertEqual(payload["task_id"], "cli-test")
            self.assertFalse((root / "generated.py").exists())


if __name__ == "__main__":
    unittest.main()
