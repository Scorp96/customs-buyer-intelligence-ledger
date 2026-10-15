"""Isolated host-only postcommit request archive + separate digest pin registry.

NOT a production attestor. Physical directory separation and O_EXCL file
creation are useful integrity controls but do NOT constitute independent
operator/cryptographic authority. No MCP tool registration is permitted here.
The Host must call publish only after the mutation lock is released and must
supply a genuinely trusted postcommit barrier and external session-tail pin.
Original request may contain confidential data: never return/archive it in
diagnostic output or zip deliverables.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from .core import SessionStore, canonical_json, digest
from .wal_immutable_snapshot_v64 import (
    create_immutable_terminal_wal_snapshot,
    read_immutable_wal_snapshot,
)

_TOOL = "append_execution_receipt"
_MAX_REQUEST_BYTES = 2_000_000
_SOURCE_FIELDS = ("call_id", "branch_group", "branch", "source_family", "query")
_CONTACT_FIELDS = ("task_id", "opportunity_id", "route_target", "source_family", "company_name")


def _safe_root(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise OSError("Untrusted or inaccessible Host authority directory")
    return path.resolve(strict=True)


def _safe_json_read(root: Path, filename: str, limit: int = _MAX_REQUEST_BYTES) -> dict[str, Any]:
    path = _safe_root(root) / filename
    if path.is_symlink() or not path.is_file():
        raise OSError("Missing or symlinked Host authority file")
    first = path.stat()
    if not (0 < first.st_size <= limit):
        raise OSError("Host authority file size invalid")
    data = path.read_bytes()
    second = path.stat()
    if (
        len(data) != first.st_size
        or first.st_dev != second.st_dev
        or first.st_ino != second.st_ino
        or first.st_size != second.st_size
        or first.st_mtime_ns != second.st_mtime_ns
    ):
        raise OSError("Host authority file changed during read")
    result = json.loads(data.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Invalid Host authority JSON")
    return result


def _create_once(root: Path, filename: str, value: dict[str, Any]) -> None:
    root = _safe_root(root)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    if not (0 < len(payload) <= _MAX_REQUEST_BYTES):
        raise ValueError("Host authority payload invalid")
    path = root / filename
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _file_ids(idempotency_key: str) -> tuple[str, str, str]:
    import re
    if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,160}", idempotency_key):
        raise ValueError("Invalid original idempotency key")
    token = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return (
        f"{_TOOL}-{token}.json",
        f"{_TOOL}-{token}.request.json",
        f"{_TOOL}-{token}.pin.json",
    )


def _verified_session_event(
    session_store: SessionStore, *, investigation_id: str, account_id: str,
    event: dict[str, Any], expected_last_seq: int, expected_last_hash: str,
) -> bool:
    if type(expected_last_seq) is not int or expected_last_seq < 2:
        return False
    if not isinstance(expected_last_hash, str) or len(expected_last_hash) != 64:
        return False
    events = session_store.read(investigation_id)
    return bool(
        len(events) == expected_last_seq
        and events[-1]["event_hash"] == expected_last_hash
        and events[0]["event_type"] == "INVESTIGATION_STARTED"
        and events[0]["payload"]["account"]["account_id"] == account_id
        and type(event.get("seq")) is int
        and 1 < event["seq"] <= len(events)
        and events[event["seq"] - 1]["event_hash"] == event.get("event_hash")
        and events[event["seq"] - 1]["event_type"] == "EXECUTION_RECEIPT_APPENDED"
    )


class IsolatedHostReceiptAuthority:
    """Host-only isolated fixture. None of the directories may be writable by a caller.

    pin_root MUST be independently protected by the deployment/operator for
    production-grade proof. Merely passing a separate local folder is insufficient.
    """

    def __init__(
        self, *, session_store: SessionStore, request_root: Path,
        snapshot_root: Path, pin_root: Path,
    ) -> None:
        roots = [_safe_root(root) for root in (request_root, snapshot_root, pin_root)]
        if len(set(roots)) != 3:
            raise ValueError("Host request, snapshot and pin directories must differ")
        self.session_store = session_store
        self.request_root, self.snapshot_root, self.pin_root = roots

    def publish_from_host_wal(
        self, *, wal_root: Path, original_arguments: dict[str, Any],
        task: dict[str, Any], event: dict[str, Any], account_id: str,
        expected_last_seq: int, expected_last_hash: str,
        trusted_postcommit_barrier: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], bool] | None,
    ) -> dict[str, Any]:
        if not callable(trusted_postcommit_barrier):
            raise PermissionError("Trusted postcommit barrier required")
        args = copy.deepcopy(original_arguments)
        investigation_id = args.get("investigation_id")
        attempt = args.get("attempt")
        if not isinstance(investigation_id, str) or not isinstance(account_id, str) or not isinstance(attempt, dict):
            raise ValueError("Invalid Host original request")
        if not isinstance(task, dict) or not isinstance(event, dict):
            raise ValueError("Invalid source task or event")
        if attempt.get("owner_id") != account_id or attempt.get("investigation_id") != investigation_id:
            raise PermissionError("Host request owner mismatch")
        fields = _SOURCE_FIELDS if "call_id" in task else _CONTACT_FIELDS
        for k in fields:
            if not isinstance(task.get(k), str) or not task[k] or attempt.get(k) != task[k]:
                raise PermissionError("Task-source ownership not proven")
        if not _verified_session_event(self.session_store, investigation_id=investigation_id,
                                      account_id=account_id, event=event, expected_last_seq=expected_last_seq,
                                      expected_last_hash=expected_last_hash):
            raise PermissionError("Session hash chain invalid or tail not independently pinned")
        persisted = self.session_store.read(investigation_id)[event["seq"] - 1]
        if persisted.get("payload", {}).get("attempt") != attempt:
            raise PermissionError("Committed event/Host source request mismatch")
        if trusted_postcommit_barrier(persisted, args, task) is not True:
            raise PermissionError("Trusted Host postcommit barrier denied")
        wal_name, request_name, pin_name = _file_ids(args.get("idempotency_key"))
        root = _safe_root(wal_root)
        if (self.request_root / request_name).exists() or (self.pin_root / pin_name).exists() or (self.snapshot_root / wal_name).exists():
            raise FileExistsError("Already archived; original evidence cannot be overwritten")
        material = copy.deepcopy(args)
        material.pop("idempotency_key", None)
        material.pop("expected_state_version", None)
        req_hash = digest({"tool": _TOOL, "arguments": material})
        # Host authority is responsible for serializing after the writer lock
        # is released. No snapshot on a live writer.
        snap_sha = create_immutable_terminal_wal_snapshot(
            terminal_wal_path=root / wal_name,
            snapshot_root=self.snapshot_root,
            expected_request_sha256=req_hash,
        )
        _create_once(self.request_root, request_name, args)
        pin = {
            "schema": "cbi.host-wal-postcommit-pin.isolated.v1",
            "wal_filename": wal_name,
            "original_arguments_sha256": digest(args),
            "request_sha256": req_hash,
            "snapshot_sha256": snap_sha,
            "investigation_id": investigation_id,
            "account_id": account_id,
            "event_seq": event["seq"],
            "event_hash": event["event_hash"],
            "task_digest": digest(task),
            "status": "PINNED_FOR_ISOLATED_VALIDATION",
        }
        # The pin is created only after both underlying immutable copies.
        _create_once(self.pin_root, pin_name, pin)
        return {
            "status": "ISOLATED_PIN_CREATED",
            "event_hash": event["event_hash"], "snapshot_sha256": snap_sha,
            "request_sha256": req_hash,
            "contains_raw_arguments": False,
            "independent_operator_authority_proven": False,
        }

    def read_host_binding(
        self, *, event: dict[str, Any], task: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], str]:
        wal_name, request_name, pin_name = _file_ids(idempotency_key)
        pin = _safe_json_read(self.pin_root, pin_name)
        args = _safe_json_read(self.request_root, request_name)
        if (
            pin.get("schema") != "cbi.host-wal-postcommit-pin.isolated.v1"
            or pin.get("status") != "PINNED_FOR_ISOLATED_VALIDATION"
            or pin.get("wal_filename") != wal_name
            or pin.get("event_hash") != event.get("event_hash")
            or pin.get("event_seq") != event.get("seq")
            or pin.get("task_digest") != digest(task)
            or pin.get("original_arguments_sha256") != digest(args)
            or args.get("idempotency_key") != idempotency_key
            or pin.get("investigation_id") != args.get("investigation_id")
            or pin.get("account_id") != args.get("attempt", {}).get("owner_id")
        ):
            raise PermissionError("Host authority pin or request was modified/unbound")
        material = copy.deepcopy(args)
        material.pop("idempotency_key", None)
        material.pop("expected_state_version", None)
        if pin.get("request_sha256") != digest({"tool": _TOOL, "arguments": material}):
            raise PermissionError("Host archived request hash differs")
        # Validate pinned WAL bytes before returning them to an injection
        # provider, never trust only a declared pin value.
        read_immutable_wal_snapshot(
            snapshot_root=self.snapshot_root, filename=wal_name,
            externally_pinned_sha256=pin.get("snapshot_sha256"),
        )
        return args, pin["snapshot_sha256"]
