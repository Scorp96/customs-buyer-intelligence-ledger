#!/usr/bin/env python3
"""Read-only authoritative production evidence primitives for v6.4 acceptance.

This module deliberately separates two evidence needs:

* recovery self-restore proof never exports the production recovery payload. It
  asks the already-bound object-store manager to restore the current generation
  into an isolated temporary directory and returns only cryptographic identity
  and stability metadata.
* exact-session capture may return one raw append-only session only while an
  explicit short-lived operator window is enabled for exactly one investigation.
  The capture is tail-pinned, size-bounded and double-read stable.

Neither operation calls a mutation handler, creates a backup, syncs the object
store, changes the hot current pointer, writes the mutation WAL, or modifies the
live Runtime root.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.object_store_recovery_v63 import _recovery_fingerprint


TOOL_NAME = "capture_authoritative_source_evidence"
RECOVERY_PROOF_SCHEMA = "cbi.v64-authoritative-recovery-self-restore-proof.v1"
SESSION_CAPTURE_SCHEMA = "cbi.v64-authoritative-single-session-capture.v1"
_MAX_SESSION_BYTES_HARD = 2 * 1024 * 1024
_INVESTIGATION_RE = re.compile(r"^INV-[A-Za-z0-9._:-]{1,150}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AuthoritativeSourceEvidenceError(RuntimeError):
    """Fail-closed evidence capture/verification error."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise AuthoritativeSourceEvidenceError(f"{field} must be a lowercase SHA-256 hex digest")
    return text


def _pointer_identity(pointer: Any) -> tuple[int, str, str, str, str]:
    generation = getattr(pointer, "generation", None)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise AuthoritativeSourceEvidenceError("object-store pointer generation is invalid")
    archive_sha = _require_sha256(
        getattr(pointer, "archive_sha256", ""),
        field="object-store pointer archive_sha256",
    )
    sessions_fp = _require_sha256(
        getattr(pointer, "sessions_fingerprint_sha256", ""),
        field="object-store pointer sessions_fingerprint_sha256",
    )
    recovery_fp = _require_sha256(
        getattr(pointer, "recovery_fingerprint_sha256", ""),
        field="object-store pointer recovery_fingerprint_sha256",
    )
    archive_format = str(getattr(pointer, "archive_format", "") or "").strip()
    if archive_format != "object_state_v2":
        raise AuthoritativeSourceEvidenceError("authoritative recovery proof requires object_state_v2")
    return generation, archive_sha, sessions_fp, recovery_fp, archive_format


def build_recovery_self_restore_proof(
    *,
    persistence: Any,
    live_root: Path,
    expected_generation: int,
    expected_recovery_fingerprint_sha256: str,
) -> dict[str, Any]:
    """Restore the current production generation into an isolated temp target.

    The source object store and live Runtime root are treated as read-only. The
    temporary target is discarded before return and no recovered payload leaves
    the process.
    """

    if persistence is None:
        raise AuthoritativeSourceEvidenceError("production object store is not bound")
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 0:
        raise AuthoritativeSourceEvidenceError("expected generation must be a non-negative integer")
    expected_fp = _require_sha256(
        expected_recovery_fingerprint_sha256,
        field="expected recovery fingerprint",
    )
    root = Path(live_root).expanduser().resolve()
    if not root.is_dir():
        raise AuthoritativeSourceEvidenceError("production live root is missing")

    live_before = _recovery_fingerprint(root)
    if live_before != expected_fp:
        raise AuthoritativeSourceEvidenceError("production live recovery fingerprint does not match expected source")

    pointer_before = persistence.read_pointer(required=True)
    if pointer_before is None:
        raise AuthoritativeSourceEvidenceError("production object-store pointer is missing")
    before_identity = _pointer_identity(pointer_before)
    generation, archive_sha, sessions_fp, recovery_fp, archive_format = before_identity
    if generation != expected_generation:
        raise AuthoritativeSourceEvidenceError(
            f"production object-store generation mismatch: expected={expected_generation} observed={generation}"
        )
    if recovery_fp != expected_fp:
        raise AuthoritativeSourceEvidenceError("production object-store recovery fingerprint mismatch")

    archive_key = str(getattr(pointer_before, "archive_key", "") or "").strip()
    archive_key_binding = _sha256_bytes(archive_key.encode("utf-8")) if archive_key else ""

    with tempfile.TemporaryDirectory(prefix="cbi-v64-authoritative-recovery-proof-") as tmp_name:
        restore_target = Path(tmp_name).resolve() / "restored-production-state"
        if restore_target == root or root in restore_target.parents or restore_target in root.parents:
            raise AuthoritativeSourceEvidenceError("restore target is not isolated from production live root")
        restored = persistence.restore_into(restore_target)
        if restored is not True:
            raise AuthoritativeSourceEvidenceError("production recovery payload could not be restored")
        restored_fp = _recovery_fingerprint(restore_target)
        if restored_fp != recovery_fp:
            raise AuthoritativeSourceEvidenceError("isolated recovery fingerprint mismatch")

    live_after = _recovery_fingerprint(root)
    if live_after != live_before:
        raise AuthoritativeSourceEvidenceError("production live state changed during recovery self-restore proof")

    pointer_after = persistence.read_pointer(required=True)
    if pointer_after is None or _pointer_identity(pointer_after) != before_identity:
        raise AuthoritativeSourceEvidenceError("production object-store pointer changed during recovery self-restore proof")

    return {
        "schema": RECOVERY_PROOF_SCHEMA,
        "verified": True,
        "generation": generation,
        "archive_format": archive_format,
        "production_source_archive_sha256": archive_sha,
        "sessions_fingerprint_sha256": sessions_fp,
        "recovery_fingerprint_sha256": recovery_fp,
        "archive_key_sha256": archive_key_binding,
        "restore_target_isolated": True,
        "production_live_root_unchanged": True,
        "object_store_write_performed": False,
        "production_write_performed": False,
        "recovered_payload_exported": False,
    }


def _flag(name: str) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"", "0", "false", "no", "off"}:
        return False
    raise AuthoritativeSourceEvidenceError(f"{name} must be a boolean flag")


def _session_export_window(investigation_id: str) -> int:
    if not _flag("CBI_V64_AUTHORITATIVE_SESSION_EXPORT_ENABLED"):
        raise AuthoritativeSourceEvidenceError("authoritative single-session export is disabled")
    allowed = str(os.environ.get("CBI_V64_AUTHORITATIVE_SESSION_EXPORT_INVESTIGATION_ID") or "").strip()
    if allowed != investigation_id:
        raise AuthoritativeSourceEvidenceError("investigation is not allowlisted for authoritative session export")

    raw_expiry = str(os.environ.get("CBI_V64_AUTHORITATIVE_SESSION_EXPORT_EXPIRES_AT") or "").strip()
    if not raw_expiry:
        raise AuthoritativeSourceEvidenceError("authoritative session export expiry is required")
    try:
        expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthoritativeSourceEvidenceError("authoritative session export expiry is invalid") from exc
    if expiry.tzinfo is None:
        raise AuthoritativeSourceEvidenceError("authoritative session export expiry must be timezone-aware")
    now = datetime.now(timezone.utc)
    expiry = expiry.astimezone(timezone.utc)
    if expiry <= now:
        raise AuthoritativeSourceEvidenceError("authoritative session export window has expired")
    if (expiry - now).total_seconds() > 30 * 60 + 5:
        raise AuthoritativeSourceEvidenceError("authoritative session export window may not exceed 30 minutes")

    raw_max = str(os.environ.get("CBI_V64_AUTHORITATIVE_SESSION_EXPORT_MAX_BYTES") or str(_MAX_SESSION_BYTES_HARD)).strip()
    try:
        max_bytes = int(raw_max)
    except ValueError as exc:
        raise AuthoritativeSourceEvidenceError("authoritative session export max bytes is invalid") from exc
    if max_bytes < 1 or max_bytes > _MAX_SESSION_BYTES_HARD:
        raise AuthoritativeSourceEvidenceError("authoritative session export size limit is outside the safe range")
    return max_bytes


def capture_exact_session_source(
    *,
    runtime: Any,
    investigation_id: str,
    expected_last_safe_seq: int,
    expected_last_safe_event_hash: str,
    acknowledge_private_state: bool,
) -> dict[str, Any]:
    """Return one exact append-only session during a short operator export window."""

    investigation_id = str(investigation_id or "").strip()
    if not _INVESTIGATION_RE.fullmatch(investigation_id):
        raise AuthoritativeSourceEvidenceError("investigation_id is invalid for single-session capture")
    if acknowledge_private_state is not True:
        raise AuthoritativeSourceEvidenceError("private-state acknowledgement is required")
    if isinstance(expected_last_safe_seq, bool) or not isinstance(expected_last_safe_seq, int) or expected_last_safe_seq < 1:
        raise AuthoritativeSourceEvidenceError("expected last-safe seq is invalid")
    expected_hash = _require_sha256(expected_last_safe_event_hash, field="expected last-safe event hash")
    max_bytes = _session_export_window(investigation_id)

    root = Path(runtime.store.root).expanduser().resolve()
    source = (root / f"{investigation_id}.jsonl").resolve()
    if source.parent != root or not source.is_file():
        raise AuthoritativeSourceEvidenceError("authoritative session source file is missing")

    before = source.read_bytes()
    if len(before) > max_bytes:
        raise AuthoritativeSourceEvidenceError("authoritative session source exceeds configured size limit")
    before_sha = _sha256_bytes(before)

    try:
        events, warning = runtime.store.read_valid_prefix(investigation_id)
    except Exception as exc:
        raise AuthoritativeSourceEvidenceError("authoritative session hash-chain validation failed") from exc
    if warning:
        raise AuthoritativeSourceEvidenceError("authoritative session has a non-empty prefix warning")
    if not events:
        raise AuthoritativeSourceEvidenceError("authoritative session has no valid events")
    tail = events[-1]
    observed_seq = tail.get("seq")
    observed_hash = str(tail.get("event_hash") or "").strip().lower()
    if observed_seq != expected_last_safe_seq or observed_hash != expected_hash:
        raise AuthoritativeSourceEvidenceError("authoritative session tail does not match the exact expected pin")

    after = source.read_bytes()
    after_sha = _sha256_bytes(after)
    if before != after or before_sha != after_sha:
        raise AuthoritativeSourceEvidenceError("authoritative session source changed during capture")

    return {
        "schema": SESSION_CAPTURE_SCHEMA,
        "investigation_id": investigation_id,
        "last_safe_seq": expected_last_safe_seq,
        "last_safe_event_hash": expected_hash,
        "payload_sha256": before_sha,
        "payload_size_bytes": len(before),
        "payload_base64": base64.b64encode(before).decode("ascii"),
        "source_stable_through_capture": True,
        "contains_private_state": True,
        "production_write_performed": False,
    }


def _tool_descriptor() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": (
            "[OPERATOR_READ_ONLY] Produce authoritative production acceptance evidence. "
            "RECOVERY_SELF_RESTORE_PROOF restores the current object-state generation only into an isolated temporary target and returns hashes only. "
            "EXACT_SESSION_CAPTURE returns one exact private append-only session only while a short-lived server-side allowlist window is explicitly enabled. Never sends outreach and never mutates production state."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["operation"],
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["RECOVERY_SELF_RESTORE_PROOF", "EXACT_SESSION_CAPTURE"],
                },
                "expected_generation": {"type": "integer", "minimum": 0},
                "expected_recovery_fingerprint_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "investigation_id": {"type": "string", "pattern": "^INV-[A-Za-z0-9._:-]{1,150}$"},
                "expected_last_safe_seq": {"type": "integer", "minimum": 1},
                "expected_last_safe_event_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "acknowledge_private_state": {"type": "boolean"},
            },
        },
    }


def install_remote_authoritative_source_evidence_tool(
    *,
    server_module: Any,
    persistence: Any,
    runtime: Any,
    live_root: Path,
) -> None:
    """Install exactly one remote-only operator read tool without mutation wrapping."""

    original_descriptors = server_module.tool_descriptors

    def descriptors() -> list[dict[str, Any]]:
        tools = copy.deepcopy(original_descriptors())
        if not any(isinstance(row, dict) and row.get("name") == TOOL_NAME for row in tools):
            tools.append(_tool_descriptor())
        return tools

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        args = dict(arguments or {}) if isinstance(arguments, dict) else {}
        operation = str(args.get("operation") or "").strip().upper()
        if operation == "RECOVERY_SELF_RESTORE_PROOF":
            return build_recovery_self_restore_proof(
                persistence=persistence,
                live_root=live_root,
                expected_generation=args.get("expected_generation"),
                expected_recovery_fingerprint_sha256=args.get("expected_recovery_fingerprint_sha256"),
            )
        if operation == "EXACT_SESSION_CAPTURE":
            return capture_exact_session_source(
                runtime=runtime,
                investigation_id=args.get("investigation_id"),
                expected_last_safe_seq=args.get("expected_last_safe_seq"),
                expected_last_safe_event_hash=args.get("expected_last_safe_event_hash"),
                acknowledge_private_state=args.get("acknowledge_private_state") is True,
            )
        raise AuthoritativeSourceEvidenceError("unsupported authoritative source evidence operation")

    server_module.tool_descriptors = descriptors
    server_module.TOOL_HANDLERS[TOOL_NAME] = handler
