from pathlib import Path
import os
import shlex
import subprocess
import sys
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

    def _marker_script(self, name, emit_first_argument=False):
        marker = Path(self.tempdir.name) / f"{name}.marker"
        script = Path(self.tempdir.name) / f"{name}.sh"
        lines = [
            "#!/bin/sh",
            f": > {shlex.quote(str(marker))}",
        ]
        if emit_first_argument:
            lines.append('cat "$1"')
        lines.append("exit 0")
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)
        return script, marker

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

    def test_pythonpath_cannot_redirect_dotted_unittest_target_outside_repository(self):
        outside = Path(self.tempdir.name) / "outside-pythonpath"
        outside.mkdir()
        marker = Path(self.tempdir.name) / "pythonpath-import.marker"
        (outside / "external_test_module.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed\\n', encoding='utf-8')\n"
            "import unittest\n\n"
            "class ExternalTests(unittest.TestCase):\n"
            "    def test_external(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )

        manifest = self._manifest(
            [sys.executable, "-m", "unittest", "external_test_module"]
        )
        with patch.dict(os.environ, {"PYTHONPATH": str(outside)}, clear=False):
            with self.assertRaises(LocalExecutionError):
                LocalExecutor().execute(manifest, apply=True)

        self.assertFalse(marker.exists())

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

    @unittest.skipIf(os.name == "nt", "POSIX Git fsmonitor helper regression")
    def test_git_fsmonitor_config_cannot_execute_during_clean_tree_gate(self):
        script, marker = self._marker_script("fsmonitor")
        subprocess.run(
            ["git", "-C", str(self.root), "config", "core.fsmonitor", str(script)],
            check=True,
        )

        manifest = ExecutionManifest.from_dict(
            {
                "task_id": "git-fsmonitor-boundary",
                "repository_root": str(self.root),
                "expected_branch": "astra-test",
                "operations": [],
            }
        )
        result = LocalExecutor().execute(manifest, apply=True)

        self.assertTrue(result.success)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "POSIX Git external diff helper regression")
    def test_git_diff_external_config_cannot_execute_from_allowlisted_diff(self):
        (self.root / "README.md").write_text("second\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "second"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        script, marker = self._marker_script("external-diff")
        subprocess.run(
            ["git", "-C", str(self.root), "config", "diff.external", str(script)],
            check=True,
        )

        result = LocalExecutor().execute(
            self._manifest(["git", "diff", "HEAD^", "HEAD"]),
            apply=True,
        )

        self.assertTrue(result.success)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "POSIX Git textconv helper regression")
    def test_git_textconv_config_cannot_execute_from_allowlisted_diff(self):
        (self.root / ".gitattributes").write_text("*.foo diff=astra_text\n", encoding="utf-8")
        (self.root / "sample.foo").write_text("first\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", ".gitattributes", "sample.foo"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "textconv baseline"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        (self.root / "sample.foo").write_text("second\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "sample.foo"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "textconv second"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        script, marker = self._marker_script("textconv", emit_first_argument=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "diff.astra_text.textconv", str(script)],
            check=True,
        )

        result = LocalExecutor().execute(
            self._manifest(["git", "diff", "HEAD^", "HEAD"]),
            apply=True,
        )

        self.assertTrue(result.success)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "POSIX Git signature helper regression")
    def test_git_signature_rendering_cannot_execute_configured_gpg_program(self):
        parent = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD^{tree}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        commit_payload = (
            f"tree {tree}\n"
            f"parent {parent}\n"
            "author ASTRA Test <astra-test@example.invalid> 1700000000 +0000\n"
            "committer ASTRA Test <astra-test@example.invalid> 1700000000 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n"
            " Version: ASTRA Test\n"
            " \n"
            " invalid-signature-material\n"
            " -----END PGP SIGNATURE-----\n"
            "\n"
            "synthetic signed commit\n"
        )
        signed_commit = subprocess.run(
            ["git", "-C", str(self.root), "hash-object", "-t", "commit", "-w", "--stdin"],
            input=commit_payload,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.root), "update-ref", "refs/heads/astra-test", signed_commit, parent],
            check=True,
        )

        script, marker = self._marker_script("gpg-program")
        subprocess.run(
            ["git", "-C", str(self.root), "config", "gpg.program", str(script)],
            check=True,
        )

        cases = (
            ["git", "log", "--show-signature", "-1", "HEAD"],
            ["git", "log", "--format=%G?", "-1", "HEAD"],
        )
        for argv in cases:
            marker.unlink(missing_ok=True)
            with self.subTest(argv=argv):
                LocalExecutor().execute(self._manifest(argv), apply=True)
                self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "POSIX Git clean-filter helper regression")
    def test_git_clean_filter_cannot_execute_during_clean_tree_gate(self):
        (self.root / ".gitattributes").write_text("*.flt filter=astra_clean\n", encoding="utf-8")
        (self.root / "sample.flt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", ".gitattributes", "sample.flt"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "clean-filter baseline"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        marker = Path(self.tempdir.name) / "clean-filter.marker"
        script = Path(self.tempdir.name) / "clean-filter.sh"
        script.write_text(
            "#!/bin/sh\n"
            f": > {shlex.quote(str(marker))}\n"
            "cat\n"
            "exit 0\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "filter.astra_clean.clean", str(script)],
            check=True,
        )
        (self.root / "sample.flt").write_text("changed\n", encoding="utf-8")
        marker.unlink(missing_ok=True)

        manifest = ExecutionManifest.from_dict(
            {
                "task_id": "git-clean-filter-boundary",
                "repository_root": str(self.root),
                "expected_branch": "astra-test",
                "operations": [],
            }
        )
        with self.assertRaises(LocalExecutionError):
            LocalExecutor().execute(manifest, apply=True)

        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
