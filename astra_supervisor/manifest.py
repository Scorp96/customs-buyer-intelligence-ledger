from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence


class ManifestValidationError(ValueError):
    """Raised when an execution manifest is malformed or unsafe."""


def _validate_relative_file_path(raw_path: str) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ManifestValidationError("operation path must be a non-empty string")

    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ManifestValidationError(f"absolute paths are not allowed: {raw_path}")

    parts = PurePosixPath(normalized).parts
    if not parts or ".." in parts:
        raise ManifestValidationError(f"path traversal is not allowed: {raw_path}")
    if any(part.lower() == ".git" for part in parts):
        raise ManifestValidationError(".git metadata is never writable")

    return str(PurePosixPath(*parts))


@dataclass(frozen=True)
class Operation:
    kind: str
    path: str | None = None
    content: str | None = None
    argv: tuple[str, ...] = ()
    cwd: str = "."

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Operation":
        if not isinstance(payload, Mapping):
            raise ManifestValidationError("each operation must be an object")

        kind = payload.get("kind")
        if kind not in {"write_text", "delete_file", "run"}:
            raise ManifestValidationError(f"unsupported operation kind: {kind!r}")

        if kind == "write_text":
            path = _validate_relative_file_path(payload.get("path"))
            content = payload.get("content")
            if not isinstance(content, str):
                raise ManifestValidationError("write_text content must be a string")
            return cls(kind=kind, path=path, content=content)

        if kind == "delete_file":
            path = _validate_relative_file_path(payload.get("path"))
            return cls(kind=kind, path=path)

        argv = payload.get("argv")
        if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)) or not argv:
            raise ManifestValidationError("run argv must be a non-empty array of strings")
        if not all(isinstance(item, str) and item for item in argv):
            raise ManifestValidationError("run argv must contain only non-empty strings")

        cwd = payload.get("cwd", ".")
        if not isinstance(cwd, str) or not cwd:
            raise ManifestValidationError("run cwd must be a non-empty string")

        return cls(kind=kind, argv=tuple(argv), cwd=cwd)


@dataclass(frozen=True)
class ExecutionManifest:
    task_id: str
    repository_root: Path
    expected_branch: str
    operations: tuple[Operation, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionManifest":
        if not isinstance(payload, Mapping):
            raise ManifestValidationError("manifest must be an object")

        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ManifestValidationError("task_id must be a non-empty string")

        repository_root = payload.get("repository_root")
        if not isinstance(repository_root, str) or not repository_root.strip():
            raise ManifestValidationError("repository_root must be a non-empty string")

        expected_branch = payload.get("expected_branch")
        if not isinstance(expected_branch, str) or not expected_branch.strip():
            raise ManifestValidationError("expected_branch must be a non-empty string")

        raw_operations = payload.get("operations", [])
        if not isinstance(raw_operations, Sequence) or isinstance(raw_operations, (str, bytes)):
            raise ManifestValidationError("operations must be an array")

        operations = tuple(Operation.from_dict(item) for item in raw_operations)
        return cls(
            task_id=task_id.strip(),
            repository_root=Path(repository_root),
            expected_branch=expected_branch.strip(),
            operations=operations,
        )
