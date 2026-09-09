from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

from astra_supervisor.manifest import ExecutionManifest
from .models import (
    DeleteFileCapability,
    RunCompileallCapability,
    RunUnittestCapability,
    TaskEnvelope,
    WriteTextCapability,
)


class CompilerError(RuntimeError):
    """Raised when a signed capability cannot be safely compiled from the exact pre-state."""


def _worktree_root(worktree: Path) -> Path:
    root = Path(worktree).resolve()
    if not root.is_dir():
        raise CompilerError("worktree root does not exist or is not a directory")
    return root


def _resolve_mutation_path(root: Path, relative_path: str) -> Path:
    target = (root / Path(*relative_path.replace("\\", "/").split("/"))).resolve(strict=False)
    try:
        common = os.path.commonpath([str(root), str(target)])
    except ValueError as exc:
        raise CompilerError("mutation path is outside the trusted worktree") from exc
    if common != str(root):
        raise CompilerError("mutation path is outside the trusted worktree")
    return target


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CompilerError("pre-state file could not be read") from exc
    return digest.hexdigest()


def verify_pre_state(task: TaskEnvelope, worktree: Path) -> None:
    if not isinstance(task, TaskEnvelope):
        raise CompilerError("typed task envelope is required")
    root = _worktree_root(worktree)

    for operation in task.operations:
        if isinstance(operation, WriteTextCapability):
            target = _resolve_mutation_path(root, operation.path)
            if operation.expect_absent:
                if target.exists() or target.is_symlink():
                    raise CompilerError(f"write_text expected absent path is present: {operation.path}")
                continue
            if not target.is_file():
                raise CompilerError(f"write_text pre-state file is missing: {operation.path}")
            actual = _sha256_file(target)
            if actual != operation.expected_sha256:
                raise CompilerError(f"write_text pre-state SHA-256 mismatch: {operation.path}")
            continue

        if isinstance(operation, DeleteFileCapability):
            target = _resolve_mutation_path(root, operation.path)
            if not target.is_file():
                raise CompilerError(f"delete_file pre-state file is missing: {operation.path}")
            actual = _sha256_file(target)
            if actual != operation.expected_sha256:
                raise CompilerError(f"delete_file pre-state SHA-256 mismatch: {operation.path}")


def intended_final_hashes(task: TaskEnvelope) -> dict[str, str | None]:
    if not isinstance(task, TaskEnvelope):
        raise CompilerError("typed task envelope is required")
    result: dict[str, str | None] = {}
    for operation in task.operations:
        if isinstance(operation, WriteTextCapability):
            result[operation.path] = hashlib.sha256(operation.content.encode("utf-8")).hexdigest()
        elif isinstance(operation, DeleteFileCapability):
            result[operation.path] = None
    return result


class TaskCompiler:
    """Compiles signed Phase 2A capabilities into the already-hardened Phase 1 manifest."""

    def compile(
        self,
        task: TaskEnvelope,
        worktree: Path,
        expected_branch: str,
    ) -> ExecutionManifest:
        if not isinstance(task, TaskEnvelope):
            raise CompilerError("typed task envelope is required")
        if not isinstance(expected_branch, str) or not expected_branch.strip():
            raise CompilerError("expected_branch must be trusted non-empty text")

        root = _worktree_root(worktree)
        verify_pre_state(task, root)
        operations: list[dict[str, object]] = []

        for operation in task.operations:
            if isinstance(operation, WriteTextCapability):
                operations.append(
                    {
                        "kind": "write_text",
                        "path": operation.path,
                        "content": operation.content,
                    }
                )
                continue
            if isinstance(operation, DeleteFileCapability):
                operations.append({"kind": "delete_file", "path": operation.path})
                continue
            if isinstance(operation, RunUnittestCapability):
                operations.append(
                    {
                        "kind": "run",
                        "argv": [
                            sys.executable,
                            "-m",
                            "unittest",
                            *operation.flags,
                            *operation.targets,
                        ],
                        "cwd": ".",
                    }
                )
                continue
            if isinstance(operation, RunCompileallCapability):
                operations.append(
                    {
                        "kind": "run",
                        "argv": [
                            sys.executable,
                            "-m",
                            "compileall",
                            *operation.flags,
                            *operation.targets,
                        ],
                        "cwd": ".",
                    }
                )
                continue
            raise CompilerError("unsupported typed capability")

        try:
            return ExecutionManifest.from_dict(
                {
                    "task_id": task.task_id,
                    "repository_root": str(root),
                    "expected_branch": expected_branch.strip(),
                    "operations": operations,
                }
            )
        except (TypeError, ValueError) as exc:
            raise CompilerError("capability could not be represented by the Phase 1 manifest") from exc
