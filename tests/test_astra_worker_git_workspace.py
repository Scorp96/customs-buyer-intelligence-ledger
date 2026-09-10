from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from astra_worker.config import RepositoryBinding
from astra_worker.git_workspace import GitWorkspaceError, GitWorkspaceManager


@unittest.skipUnless(shutil.which("git"), "Git executable required")
class GitWorkspaceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.source = self.root / "source"
        self.remote = self.root / "remote.git"
        self.worker = self.root / "worker"
        self.mirror = self.worker / "repos" / "cbi-primary.git"
        self.worker.mkdir(parents=True)

        self._git("init", str(self.source))
        self._git("-C", str(self.source), "config", "user.name", "ASTRA Test")
        self._git("-C", str(self.source), "config", "user.email", "astra@example.invalid")
        (self.source / "payload.txt").write_text("base\n", encoding="utf-8")
        self._git("-C", str(self.source), "add", "payload.txt")
        self._git("-C", str(self.source), "commit", "-m", "base")
        self._git("-C", str(self.source), "branch", "-M", "astra-source")
        self.base_sha = self._git("-C", str(self.source), "rev-parse", "HEAD").stdout.strip().lower()
        self._git("clone", "--bare", str(self.source), str(self.remote))
        self.remote_uri = self.remote.resolve().as_uri()

    def _git(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [shutil.which("git") or "git", *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"git {' '.join(args)} failed: stdout={completed.stdout!r} stderr={completed.stderr!r}"
            )
        return completed

    def binding(self, *, expected_origin: str | None = None) -> RepositoryBinding:
        return RepositoryBinding(
            repository_id="cbi-primary",
            github_repository="Scorp96/customs-buyer-intelligence-ledger",
            expected_origin=expected_origin or self.remote_uri,
            mirror_root=self.mirror,
            allowed_base_refs_exact=("astra-source",),
            allowed_base_ref_prefixes=("astra-",),
            ephemeral_branch_prefix="astra-worker/",
        )

    def manager(self, *, binding: RepositoryBinding | None = None) -> GitWorkspaceManager:
        return GitWorkspaceManager(
            binding or self.binding(),
            token="unit-test-token",
            git_executable=shutil.which("git") or "git",
        )

    def test_origin_mismatch_is_rejected(self) -> None:
        self.mirror.parent.mkdir(parents=True, exist_ok=True)
        self._git("init", "--bare", str(self.mirror))
        self._git(
            "--git-dir",
            str(self.mirror),
            "remote",
            "add",
            "origin",
            (self.root / "attacker.git").resolve().as_uri(),
        )
        manager = self.manager()
        with self.assertRaises(GitWorkspaceError):
            manager.sync_exact("astra-source", self.base_sha)

    def test_ref_sha_mismatch_fails_before_worktree_creation(self) -> None:
        manager = self.manager()
        wrong_sha = "1" * 40 if self.base_sha != "1" * 40 else "2" * 40
        with self.assertRaises(GitWorkspaceError):
            manager.sync_exact("astra-source", wrong_sha)
        self.assertFalse((self.worker / "worktrees").exists())

    def test_task_cannot_override_remote_or_refspec(self) -> None:
        manager = self.manager()
        dangerous_refs = (
            "astra-source:refs/heads/evil",
            "astra-source refs/heads/evil",
            "astra-source~1",
            "astra-source^{commit}",
            "astra-source..evil",
            "-c",
        )
        for ref in dangerous_refs:
            with self.subTest(ref=ref):
                with self.assertRaises(GitWorkspaceError):
                    manager.sync_exact(ref, self.base_sha)
        self.assertFalse(self.mirror.exists())

    def test_inherited_git_config_and_hooks_are_suppressed(self) -> None:
        malicious_home = self.root / "malicious-home"
        malicious_hooks = self.root / "malicious-hooks"
        malicious_home.mkdir()
        malicious_hooks.mkdir()
        marker = self.root / "HOOK_EXECUTED"
        hook = malicious_hooks / "post-checkout"
        hook.write_text(
            "#!/bin/sh\nprintf 'pwned' > " + repr(str(marker)).replace("'", "\"") + "\n",
            encoding="utf-8",
        )
        try:
            hook.chmod(0o755)
        except OSError:
            pass
        (malicious_home / ".gitconfig").write_text(
            f"[core]\n\thooksPath = {malicious_hooks.as_posix()}\n",
            encoding="utf-8",
        )

        poisoned = dict(os.environ)
        poisoned["HOME"] = str(malicious_home)
        poisoned["GIT_CONFIG_COUNT"] = "1"
        poisoned["GIT_CONFIG_KEY_0"] = "core.hooksPath"
        poisoned["GIT_CONFIG_VALUE_0"] = str(malicious_hooks)
        poisoned["GIT_DIR"] = str(self.root / "redirected.git")
        poisoned["GIT_WORK_TREE"] = str(self.root / "redirected-worktree")
        poisoned["SSH_COMMAND"] = "definitely-not-allowed"
        poisoned["GCM_INTERACTIVE"] = "Always"

        old_env = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update(poisoned)
            manager = self.manager()
            manager.sync_exact("astra-source", self.base_sha)
            handle = manager.create_task_worktree("task-hooks", self.base_sha)
            self.addCleanup(lambda: manager.cleanup(handle))
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        self.assertFalse(marker.exists())
        self.assertEqual(
            self._git("-C", str(handle.path), "rev-parse", "HEAD").stdout.strip().lower(),
            self.base_sha,
        )

    def test_inherited_xdg_git_config_cannot_rewrite_trusted_origin(self) -> None:
        attacker_source = self.root / "attacker-source"
        attacker_remote = self.root / "attacker.git"
        self._git("init", str(attacker_source))
        self._git("-C", str(attacker_source), "config", "user.name", "Attacker Fixture")
        self._git("-C", str(attacker_source), "config", "user.email", "attacker@example.invalid")
        (attacker_source / "payload.txt").write_text("attacker\n", encoding="utf-8")
        self._git("-C", str(attacker_source), "add", "payload.txt")
        self._git("-C", str(attacker_source), "commit", "-m", "attacker")
        self._git("-C", str(attacker_source), "branch", "-M", "astra-source")
        self._git("clone", "--bare", str(attacker_source), str(attacker_remote))
        attacker_uri = attacker_remote.resolve().as_uri()

        xdg_root = self.root / "malicious-xdg"
        git_config = xdg_root / "git" / "config"
        git_config.parent.mkdir(parents=True)
        git_config.write_text(
            f'[url "{attacker_uri}"]\n\tinsteadOf = {self.remote_uri}\n',
            encoding="utf-8",
        )

        old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(xdg_root)
        try:
            manager = self.manager()
            manager.sync_exact("astra-source", self.base_sha)
        finally:
            if old_xdg is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old_xdg

        fetched_ref = "refs/astra/fetched/" + hashlib.sha256(b"astra-source").hexdigest()[:24]
        fetched_sha = self._git(
            "--git-dir",
            str(self.mirror),
            "rev-parse",
            f"{fetched_ref}^{{commit}}",
        ).stdout.strip().lower()
        self.assertEqual(fetched_sha, self.base_sha)

    def test_stale_mirror_object_requires_fresh_sync_authority(self) -> None:
        first = self.manager()
        first.sync_exact("astra-source", self.base_sha)

        fresh_manager = self.manager()
        try:
            handle = fresh_manager.create_task_worktree("task-stale", self.base_sha)
        except GitWorkspaceError:
            return
        cleanup = fresh_manager.cleanup(handle)
        self.assertTrue(cleanup.success)
        self.fail("fresh manager created a worktree without a successful sync_exact authority")

    def test_cleanup_removes_worktree_and_generated_branch(self) -> None:
        manager = self.manager()
        manager.sync_exact("astra-source", self.base_sha)
        handle = manager.create_task_worktree("task-cleanup", self.base_sha)
        expected_branch = "astra-worker/" + hashlib.sha256(b"task-cleanup").hexdigest()[:24]
        self.assertEqual(handle.branch, expected_branch)
        self.assertTrue(handle.path.is_dir())
        self.assertEqual(
            self._git("-C", str(handle.path), "rev-parse", "HEAD").stdout.strip().lower(),
            self.base_sha,
        )

        result = manager.cleanup(handle)
        self.assertTrue(result.success)
        self.assertTrue(result.worktree_removed)
        self.assertTrue(result.branch_removed)
        self.assertFalse(handle.path.exists())
        branch_probe = subprocess.run(
            [
                shutil.which("git") or "git",
                "--git-dir",
                str(self.mirror),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{expected_branch}",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(branch_probe.returncode, 0)


if __name__ == "__main__":
    unittest.main()
