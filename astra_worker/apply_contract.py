from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from types import MappingProxyType
from typing import Mapping

from .compiler import CompilerError, intended_final_hashes
from .models import (
    DeleteFileCapability,
    ReceiptEnvelope,
    TaskEnvelope,
    WriteTextCapability,
)
from .receipt_gate import ReceiptGateResult


class ApplyContractError(RuntimeError):
    """Raised when a verified worker result is stale or lacks apply authority."""


_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class RemoteSnapshot:
    """Fresh GitHub read authority for the signed base and every mutable path."""

    base_ref: str
    base_commit_sha: str
    files: Mapping[str, bytes | None]

    def __post_init__(self) -> None:
        if not isinstance(self.base_ref, str) or not self.base_ref.strip():
            raise ApplyContractError("remote base_ref must be non-empty text")
        if not isinstance(self.base_commit_sha, str) or _GIT_SHA_RE.fullmatch(self.base_commit_sha) is None:
            raise ApplyContractError("remote base_commit_sha must be lowercase 40-hex")
        if not isinstance(self.files, Mapping):
            raise ApplyContractError("remote files must be a mapping")

        copied: dict[str, bytes | None] = {}
        identities: set[str] = set()
        for path, value in self.files.items():
            if not isinstance(path, str) or not path:
                raise ApplyContractError("remote snapshot paths must be non-empty text")
            identity = path.replace("\\", "/").casefold()
            if identity in identities:
                raise ApplyContractError("remote snapshot contains duplicate or case-colliding paths")
            identities.add(identity)
            if value is not None and not isinstance(value, bytes):
                raise ApplyContractError("remote snapshot file values must be bytes or None")
            copied[path] = value
        object.__setattr__(self, "files", MappingProxyType(copied))


@dataclass(frozen=True)
class VerifiedReceipt:
    """Receipt plus the trusted GitHub receipt-gate verification marker."""

    receipt: ReceiptEnvelope
    marker: ReceiptGateResult

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, ReceiptEnvelope):
            raise ApplyContractError("typed receipt envelope is required")
        if not isinstance(self.marker, ReceiptGateResult):
            raise ApplyContractError("typed receipt-gate marker is required")


@dataclass(frozen=True)
class ApplyOperation:
    kind: str
    path: str
    content: str | None
    expected_sha256: str | None
    intended_sha256: str | None


@dataclass(frozen=True)
class ApplyPlan:
    task_id: str
    repository_id: str
    base_ref: str
    base_commit_sha: str
    verification_issue_number: int
    operations: tuple[ApplyOperation, ...]


def _verify_gate_authority(task: TaskEnvelope, verified: VerifiedReceipt) -> ReceiptEnvelope:
    receipt = verified.receipt
    marker = verified.marker
    if marker.status != "VERIFIED":
        raise ApplyContractError("receipt does not carry a trusted VERIFIED gate marker")
    if marker.task_id != task.task_id or marker.task_id != receipt.task_id:
        raise ApplyContractError("receipt-gate task identity does not match signed task")
    if marker.receipt_status != receipt.status:
        raise ApplyContractError("receipt-gate status does not match typed receipt")
    if receipt.status != "APPLY_READY":
        raise ApplyContractError("only a verified APPLY_READY receipt may be planned for apply")
    return receipt


def _verify_task_receipt_identity(task: TaskEnvelope, receipt: ReceiptEnvelope) -> None:
    for field in ("task_id", "worker_id", "repository_id", "base_ref", "base_commit_sha"):
        if getattr(task, field) != getattr(receipt, field):
            raise ApplyContractError(f"task/receipt {field} mismatch")


def _verify_observed_final_hashes(task: TaskEnvelope, receipt: ReceiptEnvelope) -> dict[str, str | None]:
    observed = receipt.evidence.get("observed_final_hashes")
    if not isinstance(observed, Mapping):
        raise ApplyContractError("receipt observed_final_hashes must be an object")
    try:
        intended = intended_final_hashes(task)
    except CompilerError as exc:
        raise ApplyContractError("signed task mutation set is invalid") from exc
    if dict(observed) != intended:
        raise ApplyContractError("worker-observed final hashes do not match signed task authority")
    return intended


def _remote_bytes(snapshot: RemoteSnapshot, path: str) -> bytes | None:
    if path not in snapshot.files:
        raise ApplyContractError(f"remote snapshot is missing mutable path: {path}")
    return snapshot.files[path]


def _verify_remote_pre_state(task: TaskEnvelope, snapshot: RemoteSnapshot) -> None:
    if snapshot.base_ref != task.base_ref:
        raise ApplyContractError("remote base ref differs from signed task base ref")
    if snapshot.base_commit_sha != task.base_commit_sha:
        raise ApplyContractError("remote base commit advanced or differs from signed task")

    for operation in task.operations:
        if isinstance(operation, WriteTextCapability):
            current = _remote_bytes(snapshot, operation.path)
            if operation.expect_absent:
                if current is not None:
                    raise ApplyContractError(f"remote create target is no longer absent: {operation.path}")
                continue
            if current is None:
                raise ApplyContractError(f"remote replace target is absent: {operation.path}")
            if hashlib.sha256(current).hexdigest() != operation.expected_sha256:
                raise ApplyContractError(f"remote replace pre-state changed: {operation.path}")
            continue

        if isinstance(operation, DeleteFileCapability):
            current = _remote_bytes(snapshot, operation.path)
            if current is None:
                raise ApplyContractError(f"remote delete target is absent: {operation.path}")
            if hashlib.sha256(current).hexdigest() != operation.expected_sha256:
                raise ApplyContractError(f"remote delete pre-state changed: {operation.path}")


def build_apply_plan(
    task: TaskEnvelope,
    verified_receipt: VerifiedReceipt,
    remote_snapshot: RemoteSnapshot,
) -> ApplyPlan:
    """Build a pure stale-safe GitHub apply plan from signed task authority only."""

    if not isinstance(task, TaskEnvelope):
        raise ApplyContractError("typed task envelope is required")
    if not isinstance(verified_receipt, VerifiedReceipt):
        raise ApplyContractError("typed verified receipt is required")
    if not isinstance(remote_snapshot, RemoteSnapshot):
        raise ApplyContractError("typed remote snapshot is required")

    receipt = _verify_gate_authority(task, verified_receipt)
    _verify_task_receipt_identity(task, receipt)
    intended = _verify_observed_final_hashes(task, receipt)
    _verify_remote_pre_state(task, remote_snapshot)

    operations: list[ApplyOperation] = []
    for operation in task.operations:
        if isinstance(operation, WriteTextCapability):
            kind = "create" if operation.expect_absent else "replace"
            operations.append(
                ApplyOperation(
                    kind=kind,
                    path=operation.path,
                    content=operation.content,
                    expected_sha256=operation.expected_sha256,
                    intended_sha256=intended[operation.path],
                )
            )
        elif isinstance(operation, DeleteFileCapability):
            operations.append(
                ApplyOperation(
                    kind="delete",
                    path=operation.path,
                    content=None,
                    expected_sha256=operation.expected_sha256,
                    intended_sha256=None,
                )
            )

    if not operations:
        raise ApplyContractError("signed task contains no authoritative source mutation")

    return ApplyPlan(
        task_id=task.task_id,
        repository_id=task.repository_id,
        base_ref=task.base_ref,
        base_commit_sha=task.base_commit_sha,
        verification_issue_number=verified_receipt.marker.issue_number,
        operations=tuple(operations),
    )
