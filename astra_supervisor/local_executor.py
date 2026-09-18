from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from typing import Iterable

from .manifest import ExecutionManifest, Operation


class LocalExecutionError(RuntimeError):
    """Raised when local execution cannot proceed safely."""


@dataclass(frozen=True)
class ExecutionStepResult:
    index: int
    kind: str
    success: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    path: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    task_id: str
    success: bool
    applied: bool
    steps: tuple[ExecutionStepResult, ...]
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "applied": self.applied,
            "steps": [asdict(step) for step in self.steps],
            "error": self.error,
        }


class LocalExecutor:
    """Fail-closed local manifest executor with no shell and narrow commands."""

    _PYTHON_EXECUTABLE = re.compile(
        r"^python(?:\d+(?:\.\d+)*)?(?:\.exe)?$",
        re.IGNORECASE,
    )
    _UNITTEST_SWITCHES = {
        "-v",
        "--verbose",
        "-q",
        "--quiet",
        "-f",
        "--failfast",
        "-c",
        "--catch",
        "-b",
        "--buffer",
        "--locals",
    }
    _COMPILEALL_SWITCHES = {"-q", "-f", "-b", "-l"}
    _GIT_DANGEROUS_OPTIONS = {
        "--ext-diff",
        "--textconv",
        "--no-index",
        "--output",
        "--pathspec-from-file",
        "--pathspec-file-nul",
        "--show-signature",
    }

    def __init__(
        self,
        protected_branches: Iterable[str] = ("main", "master", "production"),
        command_timeout_seconds: int = 120,
    ) -> None:
        self.protected_branches = {item.lower() for item in protected_branches}
        self.command_timeout_seconds = int(command_timeout_seconds)
        if self.command_timeout_seconds <= 0:
            raise ValueError("command timeout must be positive")

    def execute(self, manifest: ExecutionManifest, apply: bool = False) -> ExecutionResult:
        root = manifest.repository_root.expanduser().resolve()
        self._validate_repository(root)

        current_branch = self._current_branch(root)
        if current_branch != manifest.expected_branch:
            raise LocalExecutionError(
                f"expected branch {manifest.expected_branch!r}, found {current_branch!r}"
            )

        if apply and current_branch.lower() in self.protected_branches:
            raise LocalExecutionError(f"refusing to apply on protected branch {current_branch!r}")

        if apply and self._working_tree_status(root):
            raise LocalExecutionError("refusing to apply with a dirty working tree")

        prepared = [self._preflight_operation(root, op) for op in manifest.operations]

        if not apply:
            steps = tuple(
                ExecutionStepResult(
                    index=index,
                    kind=operation.kind,
                    success=True,
                    path=operation.path,
                )
                for index, (operation, _resolved) in enumerate(prepared, start=1)
            )
            return ExecutionResult(
                task_id=manifest.task_id,
                success=True,
                applied=False,
                steps=steps,
            )

        step_results: list[ExecutionStepResult] = []
        for index, (operation, resolved) in enumerate(prepared, start=1):
            if operation.kind == "write_text":
                target = resolved
                assert isinstance(target, Path)
                self._atomic_write_text(target, operation.content or "")
                step_results.append(
                    ExecutionStepResult(
                        index=index,
                        kind=operation.kind,
                        success=True,
                        path=operation.path,
                    )
                )
                continue

            if operation.kind == "delete_file":
                target = resolved
                assert isinstance(target, Path)
                if target.exists():
                    if not target.is_file():
                        raise LocalExecutionError(f"delete_file target is not a file: {operation.path}")
                    target.unlink()
                step_results.append(
                    ExecutionStepResult(
                        index=index,
                        kind=operation.kind,
                        success=True,
                        path=operation.path,
                    )
                )
                continue

            if operation.kind == "run":
                cwd = resolved
                assert isinstance(cwd, Path)
                environment = self._sanitized_environment()
                try:
                    completed = subprocess.run(
                        self._execution_argv(operation.argv),
                        cwd=str(cwd),
                        shell=False,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=self.command_timeout_seconds,
                        env=environment,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    result = ExecutionStepResult(
                        index=index,
                        kind=operation.kind,
                        success=False,
                        returncode=None,
                        stderr=str(exc),
                    )
                    step_results.append(result)
                    return ExecutionResult(
                        task_id=manifest.task_id,
                        success=False,
                        applied=True,
                        steps=tuple(step_results),
                        error=f"command failed to start or timed out at step {index}",
                    )

                result = ExecutionStepResult(
                    index=index,
                    kind=operation.kind,
                    success=completed.returncode == 0,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
                step_results.append(result)
                if completed.returncode != 0:
                    return ExecutionResult(
                        task_id=manifest.task_id,
                        success=False,
                        applied=True,
                        steps=tuple(step_results),
                        error=f"command returned {completed.returncode} at step {index}",
                    )
                continue

            raise LocalExecutionError(f"unreachable operation kind: {operation.kind}")

        return ExecutionResult(
            task_id=manifest.task_id,
            success=True,
            applied=True,
            steps=tuple(step_results),
        )

    def _validate_repository(self, root: Path) -> None:
        if not root.is_dir():
            raise LocalExecutionError(f"repository root does not exist: {root}")
        if not (root / ".git").exists():
            raise LocalExecutionError(f"repository root is not a Git worktree: {root}")

    @staticmethod
    def _sanitized_environment() -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(("GIT_", "PYTHON"))
        }
        environment["GIT_PAGER"] = "cat"
        environment["PAGER"] = "cat"
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        environment["GIT_CONFIG_COUNT"] = "1"
        environment["GIT_CONFIG_KEY_0"] = "core.fsmonitor"
        environment["GIT_CONFIG_VALUE_0"] = "false"
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment

    @staticmethod
    def _execution_argv(argv: tuple[str, ...]) -> list[str]:
        executable = Path(argv[0]).name.lower() if argv else ""
        if (
            executable in {"git", "git.exe"}
            and len(argv) >= 2
            and argv[1] in {"diff", "log", "show"}
        ):
            return [argv[0], argv[1], "--no-ext-diff", "--no-textconv", *argv[2:]]
        return list(argv)

    def _git(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        environment = self._sanitized_environment()
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                shell=False,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LocalExecutionError(f"Git inspection failed: {exc}") from exc

    def _current_branch(self, root: Path) -> str:
        completed = self._git(root, "branch", "--show-current")
        branch = completed.stdout.strip()
        if completed.returncode != 0 or not branch:
            detail = completed.stderr.strip() or "detached HEAD or unknown branch"
            raise LocalExecutionError(f"cannot determine current branch: {detail}")
        return branch

    def _working_tree_status(self, root: Path) -> str:
        completed = self._git(root, "status", "--porcelain", "--untracked-files=all")
        if completed.returncode != 0:
            raise LocalExecutionError(
                f"cannot inspect working tree: {completed.stderr.strip() or completed.returncode}"
            )
        return completed.stdout.strip()

    def _preflight_operation(self, root: Path, operation: Operation) -> tuple[Operation, Path]:
        if operation.kind in {"write_text", "delete_file"}:
            assert operation.path is not None
            return operation, self._resolve_under_root(root, operation.path, allow_dot=False)

        if operation.kind == "run":
            cwd = self._resolve_under_root(root, operation.cwd, allow_dot=True)
            if not cwd.exists() or not cwd.is_dir():
                raise LocalExecutionError(f"run cwd does not exist or is not a directory: {operation.cwd}")
            self._validate_command(root, cwd, operation.argv)
            return operation, cwd

        raise LocalExecutionError(f"unsupported operation kind: {operation.kind}")

    def _resolve_under_root(self, root: Path, raw_path: str, allow_dot: bool) -> Path:
        if not isinstance(raw_path, str) or not raw_path:
            raise LocalExecutionError("path must be a non-empty string")

        normalized = raw_path.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
            raise LocalExecutionError(f"absolute path is not allowed: {raw_path}")

        parts = PurePosixPath(normalized).parts
        if ".." in parts:
            raise LocalExecutionError(f"path escapes repository root: {raw_path}")
        if any(part.lower() == ".git" for part in parts):
            raise LocalExecutionError(".git metadata is never writable or executable cwd")
        if not allow_dot and (not parts or parts == (".",)):
            raise LocalExecutionError("file operation requires a concrete relative path")

        target = (root / Path(*parts)).resolve() if parts else root
        try:
            common = os.path.commonpath([str(root), str(target)])
        except ValueError as exc:
            raise LocalExecutionError(f"path is outside repository root: {raw_path}") from exc
        if common != str(root):
            raise LocalExecutionError(f"path is outside repository root: {raw_path}")
        return target

    def _validate_command(self, root: Path, cwd: Path, argv: tuple[str, ...]) -> None:
        if not argv:
            raise LocalExecutionError("run command is empty")

        executable = Path(argv[0]).name.lower()
        if self._PYTHON_EXECUTABLE.fullmatch(executable) or executable in {"py", "py.exe"}:
            if len(argv) < 3 or argv[1] != "-m" or argv[2] not in {"unittest", "compileall"}:
                raise LocalExecutionError(
                    "Python commands are limited to '-m unittest' and '-m compileall'"
                )
            if argv[2] == "unittest":
                self._validate_unittest_args(root, cwd, argv[3:])
            else:
                self._validate_compileall_args(root, cwd, argv[3:])
            return

        if executable in {"git", "git.exe"}:
            self._validate_git_args(root, cwd, argv)
            return

        raise LocalExecutionError(f"executable is not allowed: {argv[0]}")

    def _validate_unittest_args(self, root: Path, cwd: Path, args: tuple[str, ...]) -> None:
        if not args:
            return

        if args[0] == "discover":
            index = 1
            while index < len(args):
                item = args[index]
                if item in self._UNITTEST_SWITCHES:
                    index += 1
                    continue
                if item in {"-s", "--start-directory", "-t", "--top-level-directory"}:
                    if index + 1 >= len(args):
                        raise LocalExecutionError(f"unittest discover option requires a value: {item}")
                    self._validate_command_path(root, cwd, args[index + 1], "unittest discovery path")
                    index += 2
                    continue
                if item in {"-p", "--pattern", "-k"}:
                    if index + 1 >= len(args):
                        raise LocalExecutionError(f"unittest option requires a value: {item}")
                    index += 2
                    continue
                if item.startswith("-k") and len(item) > 2:
                    index += 1
                    continue
                raise LocalExecutionError(f"unittest discover option is not allowed: {item}")
            return

        index = 0
        while index < len(args):
            item = args[index]
            if item in self._UNITTEST_SWITCHES:
                index += 1
                continue
            if item == "-k":
                if index + 1 >= len(args):
                    raise LocalExecutionError("unittest -k requires a value")
                index += 2
                continue
            if item.startswith("-k") and len(item) > 2:
                index += 1
                continue
            if item.startswith("-"):
                raise LocalExecutionError(f"unittest option is not allowed: {item}")
            self._validate_unittest_target(root, cwd, item)
            index += 1

    def _validate_unittest_target(self, root: Path, cwd: Path, target: str) -> None:
        if not isinstance(target, str) or not target or "\x00" in target:
            raise LocalExecutionError("unittest target must be non-empty text")
        if "/" in target or "\\" in target:
            self._validate_command_path(root, cwd, target, "unittest target")
            return
        if target.startswith(".") or target.endswith(".") or ".." in target:
            raise LocalExecutionError(f"unittest dotted target is invalid: {target}")
        parts = target.split(".")
        if any(not part or not part.isidentifier() for part in parts):
            raise LocalExecutionError(f"unittest dotted target is invalid: {target}")

        for end in range(len(parts), 0, -1):
            relative = Path(*parts[:end])
            candidates = (cwd / relative.with_suffix(".py"), cwd / relative / "__init__.py")
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                try:
                    common = os.path.commonpath([str(root), str(resolved)])
                except ValueError as exc:
                    raise LocalExecutionError("unittest dotted target is outside repository") from exc
                if common != str(root):
                    raise LocalExecutionError("unittest dotted target is outside repository")
                return
        raise LocalExecutionError(f"unittest dotted target does not resolve inside repository: {target}")

    def _validate_compileall_args(self, root: Path, cwd: Path, args: tuple[str, ...]) -> None:
        index = 0
        saw_target = False
        while index < len(args):
            item = args[index]
            if item in self._COMPILEALL_SWITCHES:
                index += 1
                continue
            if item.startswith("-"):
                raise LocalExecutionError(f"compileall option is not allowed: {item}")
            self._validate_command_path(root, cwd, item, "compileall target")
            saw_target = True
            index += 1
        if not saw_target:
            raise LocalExecutionError("compileall requires at least one repository-contained target")

    def _validate_command_path(self, root: Path, cwd: Path, raw_path: str, context: str) -> Path:
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            raise LocalExecutionError(f"{context} must be a non-empty relative path")
        normalized = raw_path.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
            raise LocalExecutionError(f"{context} must stay inside repository")
        parts = PurePosixPath(normalized).parts
        if ".." in parts or any(part.lower() == ".git" for part in parts):
            raise LocalExecutionError(f"{context} escapes repository")
        target = (cwd / Path(*parts)).resolve()
        try:
            common = os.path.commonpath([str(root), str(target)])
        except ValueError as exc:
            raise LocalExecutionError(f"{context} is outside repository") from exc
        if common != str(root):
            raise LocalExecutionError(f"{context} is outside repository")
        return target

    def _validate_git_args(self, root: Path, cwd: Path, argv: tuple[str, ...]) -> None:
        if len(argv) < 2:
            raise LocalExecutionError("Git command is missing a subcommand")
        subcommand = argv[1]
        allowed_subcommands = {"status", "diff", "log", "show", "rev-parse", "branch"}
        if subcommand not in allowed_subcommands:
            raise LocalExecutionError(f"Git subcommand is not allowed: {subcommand}")

        for argument in argv[2:]:
            option_name = argument.split("=", 1)[0]
            if option_name in self._GIT_DANGEROUS_OPTIONS:
                raise LocalExecutionError(f"Git option is not allowed: {option_name}")
            if "%G" in argument:
                raise LocalExecutionError("Git signature pretty-format fields are not allowed")

        if subcommand == "branch":
            for argument in argv[2:]:
                if argument.startswith("-") and argument not in {"--show-current", "--list"}:
                    raise LocalExecutionError(f"Git branch option is not allowed: {argument}")

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        except BaseException:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
