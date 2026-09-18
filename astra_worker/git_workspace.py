from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlparse

from .config import RepositoryBinding


class GitWorkspaceError(RuntimeError):
    """Raised when the pinned mirror/worktree trust boundary cannot be proven."""


_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_DANGEROUS_ENV_PREFIXES = ("GIT_", "SSH_", "GCM_")
_DANGEROUS_ENV_NAMES = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
}


@dataclass(frozen=True)
class WorktreeHandle:
    task_id: str
    path: Path
    branch: str
    base_commit_sha: str
    mirror_identity: str


@dataclass(frozen=True)
class CleanupResult:
    success: bool
    worktree_removed: bool
    branch_removed: bool
    error: str | None = None


def _require_sha(value: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise GitWorkspaceError("base_commit_sha must be a 40-hex object ID")
    return value.lower()


def _safe_branch_name(ref: str) -> bool:
    if not isinstance(ref, str) or not ref or _SAFE_REF_RE.fullmatch(ref) is None:
        return False
    if ref.startswith("-") or ref.startswith("/") or ref.endswith(("/", ".")):
        return False
    if ".." in ref or "//" in ref or "@{" in ref:
        return False
    for component in ref.split("/"):
        if not component or component.startswith(".") or component.endswith(".lock"):
            return False
    return True


class GitWorkspaceManager:
    """Owns one trusted bare mirror and deterministic ephemeral task worktrees."""

    def __init__(
        self,
        binding: RepositoryBinding,
        token: str,
        git_executable: str,
        *,
        command_timeout_seconds: int = 60,
    ) -> None:
        if not isinstance(binding, RepositoryBinding):
            raise GitWorkspaceError("repository binding is required")
        if not isinstance(token, str) or "\x00" in token:
            raise GitWorkspaceError("GitHub token is invalid")
        if not isinstance(git_executable, str) or not git_executable or "\x00" in git_executable:
            raise GitWorkspaceError("git executable is invalid")
        if command_timeout_seconds <= 0:
            raise GitWorkspaceError("Git command timeout must be positive")

        resolved_git = shutil.which(git_executable) if not Path(git_executable).is_absolute() else git_executable
        if not resolved_git or not Path(resolved_git).is_file():
            raise GitWorkspaceError("trusted Git executable was not found")

        self.binding = binding
        self._token = token
        self._git = str(Path(resolved_git).resolve())
        self._timeout = int(command_timeout_seconds)
        self._verified_base_sha: str | None = None
        self.mirror_root = Path(binding.mirror_root).resolve(strict=False)
        if len(self.mirror_root.parents) < 2:
            raise GitWorkspaceError("mirror root does not provide a worker-owned parent")
        self.worker_root = self.mirror_root.parent.parent.resolve(strict=False)
        self.worktree_root = (self.worker_root / "worktrees" / binding.repository_id).resolve(strict=False)
        self.home_root = (self.worker_root / "home").resolve(strict=False)
        self.xdg_config_root = (self.worker_root / "xdg-config").resolve(strict=False)
        self.empty_hooks_root = (self.worker_root / "empty-hooks").resolve(strict=False)

        for child in (
            self.mirror_root,
            self.worktree_root,
            self.home_root,
            self.xdg_config_root,
            self.empty_hooks_root,
        ):
            if child != self.worker_root and self.worker_root not in child.parents:
                raise GitWorkspaceError("worker-owned Git path escaped worker root")

    def _github_git_auth_header(self) -> str:
        clear = f"x-access-token:{self._token}".encode("utf-8")
        encoded = base64.b64encode(clear).decode("ascii")
        return f"AUTHORIZATION: basic {encoded}"

    def _git_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if upper.startswith(_DANGEROUS_ENV_PREFIXES) or upper in _DANGEROUS_ENV_NAMES:
                continue
            env[key] = value

        self.home_root.mkdir(parents=True, exist_ok=True)
        self.xdg_config_root.mkdir(parents=True, exist_ok=True)
        self.empty_hooks_root.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(self.home_root)
        env["XDG_CONFIG_HOME"] = str(self.xdg_config_root)
        if os.name == "nt":
            env["USERPROFILE"] = str(self.home_root)
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        env["GCM_INTERACTIVE"] = "Never"

        config: list[tuple[str, str]] = [
            ("core.hooksPath", str(self.empty_hooks_root)),
            ("credential.helper", ""),
        ]
        parsed = urlparse(self.binding.expected_origin)
        if (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.casefold() == "github.com"
        ):
            if not self._token:
                raise GitWorkspaceError("GitHub HTTPS mirror requires a token")
            config.append(("http.https://github.com/.extraheader", self._github_git_auth_header()))

        env["GIT_CONFIG_COUNT"] = str(len(config))
        for index, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        return env

    def _safe_output(self, value: str) -> str:
        if self._token:
            value = value.replace(self._token, "[REDACTED]")
            value = value.replace(self._github_git_auth_header(), "AUTHORIZATION: basic [REDACTED]")
        return value[:4096]

    def _run_git(
        self,
        *args: str,
        check: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                [self._git, *args],
                cwd=str(cwd or self.worker_root),
                env=self._git_env(),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitWorkspaceError("trusted Git subprocess could not be executed") from exc
        if check and completed.returncode != 0:
            stderr = self._safe_output(completed.stderr.strip())
            stdout = self._safe_output(completed.stdout.strip())
            detail = stderr or stdout or "no diagnostic output"
            raise GitWorkspaceError(
                f"Git command failed with exit code {completed.returncode}: {detail}"
            )
        return completed

    def _validate_base_ref(self, base_ref: str) -> str:
        if not _safe_branch_name(base_ref):
            raise GitWorkspaceError("base_ref is not a safe branch name")
        if not self.binding.allows_base_ref(base_ref):
            raise GitWorkspaceError("base_ref is outside the trusted repository policy")
        return base_ref

    def _mirror_ref(self, base_ref: str) -> str:
        digest = hashlib.sha256(base_ref.encode("utf-8")).hexdigest()[:24]
        return f"refs/astra/fetched/{digest}"

    def _ensure_mirror(self) -> None:
        self.worker_root.mkdir(parents=True, exist_ok=True)
        self.mirror_root.parent.mkdir(parents=True, exist_ok=True)
        if not self.mirror_root.exists():
            self._run_git("init", "--bare", str(self.mirror_root))
            self._run_git(
                "--git-dir",
                str(self.mirror_root),
                "config",
                "remote.origin.url",
                self.binding.expected_origin,
            )
        elif not self.mirror_root.is_dir():
            raise GitWorkspaceError("configured mirror root is not a directory")

        bare = self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "rev-parse",
            "--is-bare-repository",
        ).stdout.strip()
        if bare != "true":
            raise GitWorkspaceError("configured mirror is not a bare repository")

        origin_probe = self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "config",
            "--get",
            "remote.origin.url",
            check=False,
        )
        if origin_probe.returncode != 0:
            raise GitWorkspaceError("trusted mirror is missing origin URL")
        origin = origin_probe.stdout.strip()
        if origin != self.binding.expected_origin:
            raise GitWorkspaceError("trusted mirror origin does not match configured source")

    def sync_exact(self, base_ref: str, base_sha: str) -> None:
        self._verified_base_sha = None
        base_ref = self._validate_base_ref(base_ref)
        base_sha = _require_sha(base_sha)
        self._ensure_mirror()
        destination = self._mirror_ref(base_ref)
        refspec = f"+refs/heads/{base_ref}:{destination}"
        self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "origin",
            refspec,
        )
        resolved = self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "rev-parse",
            f"{destination}^{{commit}}",
        ).stdout.strip().lower()
        if resolved != base_sha:
            raise GitWorkspaceError("fetched branch head does not match signed base_commit_sha")
        self._verified_base_sha = base_sha

    def create_task_worktree(self, task_id: str, base_sha: str) -> WorktreeHandle:
        if not isinstance(task_id, str) or not task_id or "\x00" in task_id:
            raise GitWorkspaceError("task_id must be non-empty")
        base_sha = _require_sha(base_sha)
        if self._verified_base_sha != base_sha:
            raise GitWorkspaceError(
                "base_commit_sha must be freshly verified by sync_exact in this manager instance"
            )
        self._ensure_mirror()

        object_probe = self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "cat-file",
            "-e",
            f"{base_sha}^{{commit}}",
            check=False,
        )
        if object_probe.returncode != 0:
            raise GitWorkspaceError("signed base_commit_sha is not present in trusted mirror")

        task_digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]
        branch = f"{self.binding.ephemeral_branch_prefix}{task_digest}"
        if not _safe_branch_name(branch):
            raise GitWorkspaceError("derived ephemeral branch is invalid")
        path = (self.worktree_root / task_digest).resolve(strict=False)
        if path == self.worktree_root or self.worktree_root not in path.parents:
            raise GitWorkspaceError("derived worktree path escaped trusted root")
        if path.exists():
            raise GitWorkspaceError("derived task worktree already exists")

        branch_probe = self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        )
        if branch_probe.returncode == 0:
            raise GitWorkspaceError("derived task branch already exists")
        if branch_probe.returncode not in (0, 1):
            raise GitWorkspaceError("could not prove derived task branch is absent")

        self.worktree_root.mkdir(parents=True, exist_ok=True)
        self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(path),
            base_sha,
        )
        resolved = self._run_git("-C", str(path), "rev-parse", "HEAD").stdout.strip().lower()
        if resolved != base_sha:
            cleanup = self.cleanup(
                WorktreeHandle(
                    task_id=task_id,
                    path=path,
                    branch=branch,
                    base_commit_sha=base_sha,
                    mirror_identity=f"{self.binding.repository_id}@{base_sha}",
                )
            )
            raise GitWorkspaceError(
                "new worktree HEAD did not match signed base_commit_sha"
                + ("" if cleanup.success else "; cleanup also failed")
            )
        return WorktreeHandle(
            task_id=task_id,
            path=path,
            branch=branch,
            base_commit_sha=base_sha,
            mirror_identity=f"{self.binding.repository_id}@{base_sha}",
        )

    def cleanup(self, handle: WorktreeHandle) -> CleanupResult:
        if not isinstance(handle, WorktreeHandle):
            return CleanupResult(False, False, False, "invalid worktree handle")
        path = handle.path.resolve(strict=False)
        if path == self.worktree_root or self.worktree_root not in path.parents:
            return CleanupResult(False, False, False, "worktree path escaped trusted root")
        expected_digest = hashlib.sha256(handle.task_id.encode("utf-8")).hexdigest()[:24]
        expected_branch = f"{self.binding.ephemeral_branch_prefix}{expected_digest}"
        if handle.branch != expected_branch:
            return CleanupResult(False, False, False, "worktree branch identity mismatch")

        errors: list[str] = []
        worktree_removed = not path.exists()
        if not worktree_removed:
            result = self._run_git(
                "--git-dir",
                str(self.mirror_root),
                "worktree",
                "remove",
                "--force",
                str(path),
                check=False,
            )
            worktree_removed = result.returncode == 0 and not path.exists()
            if not worktree_removed:
                errors.append("worktree removal failed")

        branch_probe = self._run_git(
            "--git-dir",
            str(self.mirror_root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{handle.branch}",
            check=False,
        )
        if branch_probe.returncode == 1:
            branch_removed = True
        elif branch_probe.returncode == 0:
            delete = self._run_git(
                "--git-dir",
                str(self.mirror_root),
                "branch",
                "-D",
                handle.branch,
                check=False,
            )
            branch_removed = delete.returncode == 0
            if not branch_removed:
                errors.append("generated branch removal failed")
        else:
            branch_removed = False
            errors.append("generated branch state could not be proven")

        success = worktree_removed and branch_removed
        return CleanupResult(
            success=success,
            worktree_removed=worktree_removed,
            branch_removed=branch_removed,
            error=None if success else "; ".join(errors),
        )
