from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
import re
from typing import Any, Mapping, Sequence


class TaskValidationError(ValueError):
    """Raised when a remote Phase 2A task asks for invalid or unsafe authority."""


_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:/")
_MAX_OPERATIONS = 32


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise TaskValidationError(f"{context} keys mismatch; missing={missing}, extra={extra}")


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TaskValidationError(f"{field} must be non-empty text without NUL")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TaskValidationError(f"{field} must be a positive integer")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise TaskValidationError(f"{field} must be a 64-hex SHA-256")
    return value.lower()


def _relative_repo_path(value: Any, field: str) -> str:
    raw = _nonempty_text(value, field).replace("\\", "/")
    if raw.startswith("/") or _DRIVE_RE.match(raw):
        raise TaskValidationError(f"{field} must be repository-relative")
    parts = PurePosixPath(raw).parts
    if not parts or parts == (".",) or ".." in parts:
        raise TaskValidationError(f"{field} escapes or does not name a repository path")
    if any(part.lower() == ".git" for part in parts):
        raise TaskValidationError(f"{field} may not access .git metadata")
    return str(PurePosixPath(*parts))


def _utc_timestamp(value: Any, field: str) -> datetime:
    raw = _nonempty_text(value, field)
    if not raw.endswith("Z"):
        raise TaskValidationError(f"{field} must be RFC3339 UTC with a Z suffix")
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise TaskValidationError(f"{field} is not a valid RFC3339 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TaskValidationError(f"{field} must be UTC")
    return parsed


def _text_tuple(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TaskValidationError(f"{field} must be an array of strings")
    result: list[str] = []
    for item in value:
        result.append(_nonempty_text(item, field))
    if not allow_empty and not result:
        raise TaskValidationError(f"{field} must not be empty")
    return tuple(result)


@dataclass(frozen=True)
class WriteTextCapability:
    path: str
    content: str
    expected_sha256: str | None
    expect_absent: bool


@dataclass(frozen=True)
class DeleteFileCapability:
    path: str
    expected_sha256: str


@dataclass(frozen=True)
class RunUnittestCapability:
    targets: tuple[str, ...]
    flags: tuple[str, ...]


@dataclass(frozen=True)
class RunCompileallCapability:
    targets: tuple[str, ...]
    flags: tuple[str, ...]


TaskCapability = WriteTextCapability | DeleteFileCapability | RunUnittestCapability | RunCompileallCapability


@dataclass(frozen=True)
class AcceptanceLimits:
    max_changed_files: int
    max_diff_bytes: int

    @classmethod
    def from_mapping(cls, payload: Any) -> "AcceptanceLimits":
        if not isinstance(payload, Mapping):
            raise TaskValidationError("acceptance must be an object")
        _require_exact_keys(payload, {"max_changed_files", "max_diff_bytes"}, "acceptance")
        return cls(
            max_changed_files=_positive_int(payload["max_changed_files"], "acceptance.max_changed_files"),
            max_diff_bytes=_positive_int(payload["max_diff_bytes"], "acceptance.max_diff_bytes"),
        )


def _operation_from_mapping(payload: Any) -> TaskCapability:
    if not isinstance(payload, Mapping):
        raise TaskValidationError("operation must be an object")
    kind = payload.get("kind")

    if kind == "write_text":
        allowed = {"kind", "path", "content", "expected_sha256", "expect_absent"}
        if set(payload) - allowed or not {"kind", "path", "content"}.issubset(payload):
            raise TaskValidationError("write_text has missing or unknown fields")
        content = payload["content"]
        if not isinstance(content, str):
            raise TaskValidationError("write_text.content must be text")
        has_sha = "expected_sha256" in payload and payload.get("expected_sha256") is not None
        expect_absent = payload.get("expect_absent", False)
        if not isinstance(expect_absent, bool):
            raise TaskValidationError("write_text.expect_absent must be boolean")
        if has_sha == expect_absent:
            raise TaskValidationError(
                "write_text requires exactly one of expected_sha256 or expect_absent=true"
            )
        return WriteTextCapability(
            path=_relative_repo_path(payload["path"], "write_text.path"),
            content=content,
            expected_sha256=_sha256(payload["expected_sha256"], "write_text.expected_sha256") if has_sha else None,
            expect_absent=expect_absent,
        )

    if kind == "delete_file":
        _require_exact_keys(payload, {"kind", "path", "expected_sha256"}, "delete_file")
        return DeleteFileCapability(
            path=_relative_repo_path(payload["path"], "delete_file.path"),
            expected_sha256=_sha256(payload["expected_sha256"], "delete_file.expected_sha256"),
        )

    if kind in {"run_unittest", "run_compileall"}:
        _require_exact_keys(payload, {"kind", "targets", "flags"}, str(kind))
        targets = _text_tuple(payload["targets"], f"{kind}.targets")
        flags = _text_tuple(payload["flags"], f"{kind}.flags", allow_empty=True)
        if kind == "run_unittest":
            return RunUnittestCapability(targets=targets, flags=flags)
        return RunCompileallCapability(targets=targets, flags=flags)

    raise TaskValidationError(f"unsupported task operation kind: {kind!r}")


@dataclass(frozen=True)
class TaskEnvelope:
    schema_version: str
    task_id: str
    worker_id: str
    repository_id: str
    base_ref: str
    base_commit_sha: str
    issued_at: str
    expires_at: str
    nonce: str
    operations: tuple[TaskCapability, ...]
    acceptance: AcceptanceLimits

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TaskEnvelope":
        if not isinstance(payload, Mapping):
            raise TaskValidationError("task must be an object")
        expected = {
            "schema_version", "task_id", "worker_id", "repository_id", "base_ref",
            "base_commit_sha", "issued_at", "expires_at", "nonce", "operations", "acceptance",
        }
        _require_exact_keys(payload, expected, "task")
        if payload["schema_version"] != "astra.task.v1":
            raise TaskValidationError("unsupported task schema_version")
        commit = payload["base_commit_sha"]
        if not isinstance(commit, str) or _SHA1_RE.fullmatch(commit) is None:
            raise TaskValidationError("base_commit_sha must be a 40-hex Git object id")
        issued = _utc_timestamp(payload["issued_at"], "issued_at")
        expires = _utc_timestamp(payload["expires_at"], "expires_at")
        if expires <= issued:
            raise TaskValidationError("expires_at must be later than issued_at")
        raw_operations = payload["operations"]
        if not isinstance(raw_operations, Sequence) or isinstance(raw_operations, (str, bytes)):
            raise TaskValidationError("operations must be an array")
        if not raw_operations or len(raw_operations) > _MAX_OPERATIONS:
            raise TaskValidationError(f"operations must contain 1..{_MAX_OPERATIONS} entries")
        operations = tuple(_operation_from_mapping(item) for item in raw_operations)
        return cls(
            schema_version="astra.task.v1",
            task_id=_nonempty_text(payload["task_id"], "task_id"),
            worker_id=_nonempty_text(payload["worker_id"], "worker_id"),
            repository_id=_nonempty_text(payload["repository_id"], "repository_id"),
            base_ref=_nonempty_text(payload["base_ref"], "base_ref"),
            base_commit_sha=commit.lower(),
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            nonce=_nonempty_text(payload["nonce"], "nonce"),
            operations=operations,
            acceptance=AcceptanceLimits.from_mapping(payload["acceptance"]),
        )


_RECEIPT_STATUSES = {"APPLY_READY", "NOT_APPLY_READY", "REJECTED", "QUARANTINED"}


@dataclass(frozen=True)
class ReceiptEnvelope:
    """Typed outer receipt identity; detailed evidence remains a strict JSON object."""

    schema_version: str
    task_id: str
    worker_id: str
    repository_id: str
    base_ref: str
    base_commit_sha: str
    status: str
    evidence: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ReceiptEnvelope":
        if not isinstance(payload, Mapping):
            raise TaskValidationError("receipt must be an object")
        expected = {
            "schema_version", "task_id", "worker_id", "repository_id", "base_ref",
            "base_commit_sha", "status", "evidence",
        }
        _require_exact_keys(payload, expected, "receipt")
        if payload["schema_version"] != "astra.receipt.v1":
            raise TaskValidationError("unsupported receipt schema_version")
        commit = payload["base_commit_sha"]
        if not isinstance(commit, str) or _SHA1_RE.fullmatch(commit) is None:
            raise TaskValidationError("receipt base_commit_sha must be 40-hex")
        status = payload["status"]
        if status not in _RECEIPT_STATUSES:
            raise TaskValidationError("invalid receipt status")
        evidence = payload["evidence"]
        if not isinstance(evidence, Mapping):
            raise TaskValidationError("receipt evidence must be an object")
        return cls(
            schema_version="astra.receipt.v1",
            task_id=_nonempty_text(payload["task_id"], "receipt.task_id"),
            worker_id=_nonempty_text(payload["worker_id"], "receipt.worker_id"),
            repository_id=_nonempty_text(payload["repository_id"], "receipt.repository_id"),
            base_ref=_nonempty_text(payload["base_ref"], "receipt.base_ref"),
            base_commit_sha=commit.lower(),
            status=status,
            evidence=dict(evidence),
        )
