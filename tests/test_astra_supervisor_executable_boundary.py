from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from astra_supervisor import (
    ExecutionManifest,
    LocalExecutionError,
    LocalExecutor,
    ManifestValidationError,
)


class LocalExecutorExecutableBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "repo"
        self.root.mkdir()
        subprocess.run(
            ["git", "-C", str(self.root), "init", "-b", "astra-test"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "astra-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "ASTRA Test"],
            check=True,
        )
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "baseline"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def _manifest(self, argv):
        return ExecutionManifest.from_dict(
            {
                "task_id": "executable-boundary",
                "repository_root": str(self.root),
                "expected_branch": "astra-test",
                "operations": [{"kind": "run", "argv": argv, "cwd": "."}],
            }
        )

    def test_rejects_user_supplied_executable_paths_even_with_allowlisted_basename(self):
        suffix = ".exe" if os.name == "nt" else ""
        cases = (
            [str(self.root / "tools" / f"python{suffix}"), "-m", "unittest"],
            [str(self.root / "tools" / f"git{suffix}"), "status"],
        )
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises((ManifestValidationError, LocalExecutionError)):
                    LocalExecutor().execute(self._manifest(argv), apply=False)

    def test_git_environment_cannot_redirect_branch_and_clean_tree_gates(self):
        subprocess.run(
            ["git", "-C", str(self.root), "branch", "-M", "main"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        decoy = Path(self.tempdir.name) / "decoy"
        decoy.mkdir()
        subprocess.run(
            ["git", "-C", str(decoy), "init", "-b", "astra-test"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(decoy), "config", "user.email", "astra-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(decoy), "config", "user.name", "ASTRA Test"],
            check=True,
        )
        (decoy / "README.md").write_text("decoy\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(decoy), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(decoy), "commit", "-m", "decoy"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        manifest = ExecutionManifest.from_dict(
            {
                "task_id": "git-env-redirection",
                "repository_root": str(self.root),
                "expected_branch": "astra-test",
                "operations": [
                    {"kind": "write_text", "path": "must-not-write.txt", "content": "unsafe\n"}
                ],
            }
        )

        with patch.dict(
            os.environ,
            {"GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy)},
            clear=False,
        ):
            with self.assertRaises(LocalExecutionError):
                LocalExecutor().execute(manifest, apply=True)

        self.assertFalse((self.root / "must-not-write.txt").exists())


if __name__ == "__main__":
    unittest.main()
