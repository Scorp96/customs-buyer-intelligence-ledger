"""Isolated, operator-authorized recovery of partial Host postcommit archives.

ONLY resumes a create-once prefix of an existing verified archive. No deletes,
no overwrites, no production registration, no implicit authority from the
claimant, no automatic recovery of mismatched artefacts.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Callable

from .core import canonical_json, digest
from .host_postcommit_archive_v64 import (
    IsolatedHostReceiptAuthority, _CONTACT_FIELDS, _SOURCE_FIELDS,
    _create_once, _file_ids, _safe_json_read, _verified_session_event,
)
from .v61_disk_wal_commit_proof_v64 import make_v61_disk_wal_commit_verifier
from .wal_immutable_snapshot_v64 import read_immutable_wal_snapshot

RecoveryAuthorization = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None
]


def resume_authorized_partial_archive(
    *,
    authority: IsolatedHostReceiptAuthority,
    original_arguments: dict[str, Any],
    task: dict[str, Any],
    event: dict[str, Any],
    account_id: str,
    expected_last_seq: int,
    expected_last_hash: str,
    trusted_postcommit_barrier: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], bool] | None,
    trusted_recovery_authorization: RecoveryAuthorization | None,
) -> dict[str, Any]:
    """Resume only from independently pre-pinned WAL and pin-manifest digests.

    The recovery authorization is a trusted Host callback, never caller JSON.
    In particular, a locally recomputed SHA is NOT an independent operator pin.
    """
    if not callable(trusted_postcommit_barrier) or not callable(trusted_recovery_authorization):
        raise PermissionError("Independent recovery authorization and postcommit barrier required")
    if not isinstance(original_arguments, dict) or not isinstance(task, dict) or not isinstance(event, dict):
        raise ValueError("Invalid original request, source task or event")
    args = copy.deepcopy(original_arguments)
    attempt = args.get("attempt")
    investigation_id = args.get("investigation_id")
    if not isinstance(attempt, dict) or not isinstance(investigation_id, str):
        raise ValueError("Host original request invalid")
    if (
        attempt.get("owner_id") != account_id
        or attempt.get("investigation_id") != investigation_id
    ):
        raise PermissionError("Recovery owner mismatch")
    fields = _SOURCE_FIELDS if "call_id" in task else _CONTACT_FIELDS
    if any(not isinstance(task.get(k), str) or not task[k] or attempt.get(k) != task[k] for k in fields):
        raise PermissionError("Recovery task/source binding invalid")
    if not _verified_session_event(
        authority.session_store, investigation_id=investigation_id,
        account_id=account_id, event=event,
        expected_last_seq=expected_last_seq, expected_last_hash=expected_last_hash,
    ):
        raise PermissionError("Recovery session and independent tail pin invalid")
    committed_event = authority.session_store.read(investigation_id)[event["seq"] - 1]
    if committed_event.get("payload", {}).get("attempt") != attempt:
        raise PermissionError("Recovered attempt not in immutable event")
    if trusted_postcommit_barrier(committed_event, args, task) is not True:
        raise PermissionError("Postcommit barrier denied")
    wal_name, req_name, pin_name, commit_name = _file_ids(args.get("idempotency_key"))
    snap_file = authority.snapshot_root / wal_name
    req_file = authority.request_root / req_name
    pin_file = authority.pin_root / pin_name
    commit_file = authority.pin_root / commit_name
    exists = tuple(p.exists() or p.is_symlink() for p in (snap_file, req_file, pin_file, commit_file))
    if not any(exists):
        raise FileNotFoundError("NO_PARTIAL_ARCHIVE: regular publish path required")
    # Only a contiguous publication prefix is replayable; unexpected later
    # artefacts are custody anomalies requiring human intervention.
    if exists not in (
        (True, False, False, False),
        (True, True, False, False),
        (True, True, True, False),
        (True, True, True, True),
    ):
        raise PermissionError("PARTIAL_ARCHIVE_OUT_OF_ORDER")
    if any(p.is_symlink() for p in (snap_file, req_file, pin_file, commit_file)):
        raise PermissionError("PARTIAL_ARCHIVE_SYMLINK_REJECTED")
    try:
        authorized = trusted_recovery_authorization(committed_event, args, task)
    except Exception as exc:
        raise PermissionError("Independent recovery authority unavailable") from exc
    if not isinstance(authorized, dict) or authorized.get("approved") is not True:
        raise PermissionError("Independent recovery authority denied")

    material = copy.deepcopy(args)
    material.pop("idempotency_key", None)
    material.pop("expected_state_version", None)
    request_sha = digest({"tool": "append_execution_receipt", "arguments": material})
    snapshot_sha = authorized.get("expected_snapshot_sha256")
    pin_sha = authorized.get("expected_pin_sha256")
    for sha in (snapshot_sha, pin_sha):
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise PermissionError("Recovery digests not independently pinned")
    if (
        authorized.get("expected_request_sha256") != request_sha
        or authorized.get("expected_event_hash") != committed_event["event_hash"]
        or authorized.get("expected_task_digest") != digest(task)
        or authorized.get("expected_account_id") != account_id
        or authorized.get("expected_investigation_id") != investigation_id
        or authorized.get("expected_session_tail_hash") != expected_last_hash
        or authorized.get("expected_last_seq") != expected_last_seq
    ):
        raise PermissionError("Recovery authority identity/pin mismatch")

    # Pin is from protected Host evidence. Do NOT derive the expected pin
    # from potentially attacker-edited shadow bytes.
    raw = read_immutable_wal_snapshot(
        snapshot_root=authority.snapshot_root,
        filename=wal_name,
        externally_pinned_sha256=snapshot_sha,
    )
    def known_args(_event, _attempt, _task):
        return copy.deepcopy(args)
    verifier = make_v61_disk_wal_commit_verifier(
        wal_root=authority.snapshot_root,
        trusted_original_arguments=known_args,
        immutable_snapshot_root=authority.snapshot_root,
        trusted_snapshot_sha256=lambda _event, _attempt, _task: snapshot_sha,
    )
    if verifier(committed_event, attempt, task) is not True:
        raise PermissionError("Recovered immutable WAL not an exact COMMITTED receipt")

    pin = {
        "schema": "cbi.host-wal-postcommit-pin.isolated.v1",
        "wal_filename": wal_name,
        "original_arguments_sha256": digest(args),
        "request_sha256": request_sha,
        "snapshot_sha256": snapshot_sha,
        "investigation_id": investigation_id,
        "account_id": account_id,
        "event_seq": event["seq"],
        "event_hash": event["event_hash"],
        "task_digest": digest(task),
        "status": "PINNED_FOR_ISOLATED_VALIDATION",
    }
    actual_pin_sha = hashlib.sha256(canonical_json(pin).encode("utf-8")).hexdigest()
    if pin_sha != actual_pin_sha:
        raise PermissionError("Independent pin differs from recovered manifest")
    marker = {
        "schema": "cbi.host-wal-archive-publication.isolated.v1",
        "status": "PUBLISHED",
        "wal_filename": wal_name,
        "pin_sha256": pin_sha,
        "original_arguments_sha256": pin["original_arguments_sha256"],
        "snapshot_sha256": snapshot_sha,
        "event_hash": event["event_hash"],
        "task_digest": digest(task),
    }

    # Verify all present files BEFORE any new writes. A mismatch never causes
    # a removal, overwrite or a second archive generation.
    for exists_now, root, filename, expected in (
        (exists[1], authority.request_root, req_name, args),
        (exists[2], authority.pin_root, pin_name, pin),
        (exists[3], authority.pin_root, commit_name, marker),
    ):
        if exists_now and _safe_json_read(root, filename) != expected:
            raise PermissionError("Existing archive material differs: custody STOP")

    if exists[3]:
        # A replay of a completed archive is only idempotent when its
        # independent operator anchor is still valid.
        authority.read_host_binding(
            event=event, task=task, idempotency_key=args["idempotency_key"]
        )
        return {
            "status": "ALREADY_PUBLISHED_VERIFIED",
            "new_files_created": 0,
            "independent_operator_authority_proven": True,
            "contains_raw_arguments": False,
        }

    created = 0
    for has_file, root, filename, value in (
        (exists[1], authority.request_root, req_name, args),
        (exists[2], authority.pin_root, pin_name, pin),
        (exists[3], authority.pin_root, commit_name, marker),
    ):
        if not has_file:
            _create_once(root, filename, value)
            created += 1

    # Fail closed when the external operator has not yet pinned the new
    # manifest. An archive can be published but still not prove terminal
    # coverage until an independently verified operator anchor exists.
    return {
        "status": "ISOLATED_PARTIAL_RECOVERY_PUBLISHED",
        "new_files_created": created,
        "independent_operator_authority_proven": False,
        "contains_raw_arguments": False,
        "archive_not_cross_volume_atomic": True,
    }
