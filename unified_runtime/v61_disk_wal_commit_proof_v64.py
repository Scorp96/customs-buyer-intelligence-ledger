"""Isolated read-only parser for the REAL CBI v6.1 mutation WAL file format.

NOT wired to production. Uses an operator-selected WAL directory and a trusted
Host-side original-arguments provider, never MCP JSON metadata supplied by the
receipt claimant. COMMITTED status alone is NOT proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .core import digest
from .wal_safe_reader_v64 import read_consistent_wal_bytes
from .wal_immutable_snapshot_v64 import read_immutable_wal_snapshot

_SCHEMA = "cbi.mutation-wal.v6.1"
_CORRELATION_SCHEMA = "cbi.mutation-correlation.v6.1"
_META_SCHEMA = "cbi.mutation-meta.v6.1"
_TOOL = "append_execution_receipt"
_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
_WAL_MAX_BYTES = 2_000_000
TrustedArgumentsProvider = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None]


def make_v61_disk_wal_commit_verifier(
    *,
    wal_root: Path,
    trusted_original_arguments: TrustedArgumentsProvider | None,
    immutable_snapshot_root: Path | None = None,
    trusted_snapshot_sha256: TrustedArgumentsProvider | None = None,
) -> Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], bool]:
    """Produce a fail-closed Host callback that reads but NEVER writes WAL.

    trusted_original_arguments must retrieve the exact originally accepted
    mutation request from a protected Host-side store; it is NOT available
    in the legacy terminal WAL record and cannot be inferred from a receipt.
    """
    def verify(event: dict[str, Any], attempt: dict[str, Any], task: dict[str, Any]) -> bool:
        if not callable(trusted_original_arguments):
            return False
        snapshot_enabled = immutable_snapshot_root is not None
        if snapshot_enabled != callable(trusted_snapshot_sha256):
            return False
        if not isinstance(event, dict) or not isinstance(attempt, dict) or not isinstance(task, dict):
            return False
        try:
            args = trusted_original_arguments(event, attempt, task)
            if not isinstance(args, dict):
                return False
            key = args.get("idempotency_key")
            if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
                return False
            investigation_id = args.get("investigation_id")
            if (
                not isinstance(investigation_id, str)
                or investigation_id != attempt.get("investigation_id")
                or not isinstance(args.get("attempt"), dict)
            ):
                return False

            # Original request snapshot must prove the SAME attempted work.
            original_attempt = args["attempt"]
            for field in ("investigation_id", "attempt_id", "execution_id", "owner_id",
                          "module_or_branch", "source_family", "query", "result",
                          "completed_at", "content_sha256", "raw_result_locator"):
                if original_attempt.get(field) != attempt.get(field):
                    return False
            for field in ("call_id", "branch_group", "branch", "task_id",
                          "opportunity_id", "route_target", "company_name"):
                if field in task and original_attempt.get(field) != task.get(field):
                    return False
            if not isinstance(args.get("evidence", []), list):
                return False
            if len(args.get("evidence", [])) != len(event.get("payload", {}).get("evidence", [])):
                return False

            material = dict(args)
            material.pop("idempotency_key", None)
            material.pop("expected_state_version", None)
            request_sha = digest({"tool": _TOOL, "arguments": material})
            correlation_id = (
                "MUTCORR-" + hashlib.sha256(f"{_TOOL}:{key}".encode("utf-8")).hexdigest()[:24]
            )
            expected_correlation = {
                "schema": _CORRELATION_SCHEMA,
                "correlation_id": correlation_id,
                "tool": _TOOL,
            }
            if event.get("mutation_correlation") != expected_correlation:
                return False

            # Exactly one *known* WAL path; no untrusted directory traversal,
            # globbing of private customer records, or symlink following.
            root = Path(immutable_snapshot_root if snapshot_enabled else wal_root)
            if not root.is_dir() or root.is_symlink():
                return False
            safe_filename = f"{_TOOL}-{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
            if snapshot_enabled:
                # Preferred Windows path: never hold a reader handle open
                # on the live WAL while a writer is replacing that WAL file.
                # The SHA pin MUST be obtained from an independent trusted
                # Host register, not from a claimant's submitted receipt.
                pinned = trusted_snapshot_sha256(event, attempt, task)
                raw = read_immutable_wal_snapshot(
                    snapshot_root=root, filename=safe_filename,
                    externally_pinned_sha256=pinned,
                )
            else:
                # Isolated legacy/direct read; not approved for a concurrent
                # live Windows production WAL writer.
                raw = read_consistent_wal_bytes(
                    root / safe_filename, max_bytes=_WAL_MAX_BYTES
                )
            row = json.loads(raw.decode("utf-8"))
            if not isinstance(row, dict):
                return False
            if (
                row.get("schema") != _SCHEMA
                or row.get("status") != "COMMITTED"
                or row.get("tool") != _TOOL
                or row.get("idempotency_key") != key
                or row.get("mutation_correlation_id") != correlation_id
                or row.get("request_sha256") != request_sha
                or not isinstance(row.get("result"), dict)
            ):
                return False
            seq = event.get("seq")
            if (
                not isinstance(seq, int) or isinstance(seq, bool)
                or type(row.get("state_version_before")) is not int
                or type(row.get("state_version_after")) is not int
                or row["state_version_before"] != seq - 1
                or row["state_version_after"] != seq
            ):
                return False
            result = row["result"]
            if row.get("result_sha256") != digest(result):
                return False
            meta = result.get("mutation_meta")
            if not isinstance(meta, dict):
                return False
            if (
                meta.get("schema") != _META_SCHEMA
                or meta.get("tool") != _TOOL
                or meta.get("idempotency_key") != key
                or meta.get("request_sha256") != request_sha
                or meta.get("state_version_before") != seq - 1
                or meta.get("state_version_after") != seq
                or meta.get("write_ahead_intent") is not True
                or meta.get("replayed") is not False
                or result.get("accepted") is not True
                or result.get("attempt_id") != attempt.get("attempt_id")
                or type(result.get("evidence_count")) is not int
                or result["evidence_count"] != len(event.get("payload", {}).get("evidence", []))
            ):
                return False
            return True
        except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            return False
        except Exception:
            # Unavailable Host authority and adversarial providers never
            # become a terminal Source Family verdict.
            return False
    return verify
