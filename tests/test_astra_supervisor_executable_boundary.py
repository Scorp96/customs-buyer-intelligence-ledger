from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from astra_supervisor import ExecutionManifest, LocalExecutionError, LocalExecutor


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
                with self.assertRaises(LocalExecutionError):
                    LocalExecutor().execute(self._manifest(argv), apply=False)


if __name__ == "__main__":
    unittest.main()
