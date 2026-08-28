#!/usr/bin/env python3
"""Exact v5.4.1 -> v6 migration crash recovery over Peer Receipt recovery.

Migration is not recovered merely because V6_MIGRATION_REPORT.json exists.
The production handler serializes migrations per resolved target root and, only
after the underlying migration returns and its report matches the returned
result, persists a correlation-bound proof in the mutation-WAL sidecar root.

A PREPARED retry is reconciled only when the proof, request hash, target,
source, report bytes and exact result digest all agree. A crash after migration
but before proof creation remains fail-closed. Recovery never re-runs migration
and never activates the migrated root automatically.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_correlated as _correlated  # noqa: E402
from mcp import server_v61_peer_receipt_recovery as _peer_receipt  # noqa: E402
from unified_runtime.resilience import exclusive_file_lock  # noqa: E402


_v61 = _peer_receipt._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]
_BASE_MIGRATION_HANDLER = _RUNTIME.migrate_v5_4_1_to_v6

_PROOF_SCHEMA = "cbi.migration-mutation-proof.v6.1"
_PROOF_NAME = "CORRELATED_MIGRATION_REPORT_AND_MUTATION_PROOF"
_TEST_CRASH_BEFORE_PROOF = "CBI_V61_TEST_CRASH_AFTER_MIGRATION_BEFORE_PROOF"


def _resolved_material(arguments: dict[str, Any]) -> tuple[Path, Path] | None:
    try:
        source_root = Path(arguments.get("source_session_root") or _RUNTIME.store.root).resolve()
        target_raw = str(arguments.get("target_root") or "").strip()
        if not target_raw:
            return None
        target_root = Path(target_raw).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return source_root, target_root


def _request_hash(arguments: dict[str, Any]) -> str:
    request_args = copy.deepcopy(arguments)
    request_args.pop("idempotency_key", None)
    request_args.pop("expected_state_version", None)
    return _v61._digest({
        "tool": "migrate_v5_4_1_to_v6",
        "arguments": request_args,
    })


def _target_lock(target_root: Path) -> Path:
    identity = hashlib.sha256(str(target_root).encode("utf-8")).hexdigest()
    root = _v61._journal_root() / "migration-target-locks"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{identity}.lock"


def _proof_path(correlation_id: str) -> Path:
    root = _v61._journal_root() / "migration-proofs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{correlation_id}.json"


def _migration_runtime_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    material = _resolved_material(arguments)
    if material is None:
        return _BASE_MIGRATION_HANDLER(arguments)
    source_root, target_root = material
    correlation = _correlated._ACTIVE_MUTATION_CORRELATION.get()
    correlation_id = str((correlation or {}).get("correlation_id") or "").strip()
    if not correlation_id:
        # Production mutation calls should always have correlation. If not,
        # preserve Runtime behavior but do not create a replay proof.
        return _BASE_MIGRATION_HANDLER(arguments)

    runtime_args = copy.deepcopy(arguments)
    runtime_args.pop("idempotency_key", None)
    runtime_args.pop("expected_state_version", None)
    request_sha256 = _request_hash(arguments)

    with exclusive_file_lock(_target_lock(target_root), timeout_seconds=60.0):
        result = _BASE_MIGRATION_HANDLER(runtime_args)
        if os.environ.get(_TEST_CRASH_BEFORE_PROOF) == "1":
            os._exit(91)

        report_path = target_root / "V6_MIGRATION_REPORT.json"
        try:
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _v61.ValidationError(
                "migration returned without a readable V6_MIGRATION_REPORT.json"
            ) from exc
        if not isinstance(report, dict) or report != result:
            raise _v61.ValidationError(
                "migration report does not exactly match the Runtime result"
            )
        if (
            str(report.get("source_session_root") or "") != str(source_root)
            or str(report.get("target_root") or "") != str(target_root)
            or report.get("switched") is not False
        ):
            raise _v61.ValidationError("migration report target/source/activation boundary mismatch")

        proof = {
            "schema": _PROOF_SCHEMA,
            "tool": "migrate_v5_4_1_to_v6",
            "correlation_id": correlation_id,
            "request_sha256": request_sha256,
            "source_session_root": str(source_root),
            "target_root": str(target_root),
            "report_path": str(report_path),
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "result_sha256": _v61._digest(result),
            "source_manifest_sha256_before": str(
                report.get("source_manifest_sha256_before") or ""
            ),
            "source_manifest_sha256_after": str(
                report.get("source_manifest_sha256_after") or ""
            ),
            "source_unchanged": report.get("source_unchanged") is True,
            "switched": False,
        }
        _v61._atomic_json_write(_proof_path(correlation_id), proof)
        return result


def _migration_mcp_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return _v61._invoke_mutation(
        "migrate_v5_4_1_to_v6",
        _migration_runtime_handler,
        arguments,
    )


def _reconcile_migration(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    material = _resolved_material(args)
    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if material is None or not correlation_id:
        return None
    source_root, target_root = material
    proof_path = _proof_path(correlation_id)
    if not proof_path.is_file():
        return None
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        report_path = target_root / "V6_MIGRATION_REPORT.json"
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(proof, dict) or not isinstance(report, dict):
        return None
    if (
        proof.get("schema") != _PROOF_SCHEMA
        or proof.get("tool") != "migrate_v5_4_1_to_v6"
        or str(proof.get("correlation_id") or "") != correlation_id
        or str(proof.get("request_sha256") or "") != request_hash
        or str(proof.get("source_session_root") or "") != str(source_root)
        or str(proof.get("target_root") or "") != str(target_root)
        or str(proof.get("report_path") or "") != str(report_path)
        or str(proof.get("report_sha256") or "")
        != hashlib.sha256(report_bytes).hexdigest()
        or str(proof.get("result_sha256") or "") != _v61._digest(report)
        or str(report.get("source_session_root") or "") != str(source_root)
        or str(report.get("target_root") or "") != str(target_root)
        or str(report.get("source_manifest_sha256_before") or "")
        != str(proof.get("source_manifest_sha256_before") or "")
        or str(report.get("source_manifest_sha256_after") or "")
        != str(proof.get("source_manifest_sha256_after") or "")
        or bool(report.get("source_unchanged")) != bool(proof.get("source_unchanged"))
        or report.get("switched") is not False
        or proof.get("switched") is not False
    ):
        return None

    result = {
        **copy.deepcopy(report),
        "mutation_meta": _v61._reconciled_meta(
            "migrate_v5_4_1_to_v6",
            stored,
            request_hash,
            0,
            _PROOF_NAME,
        ),
    }
    _v61._commit_receipt(path, stored, result, 0)
    return result


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "migrate_v5_4_1_to_v6":
        reconciled = _reconcile_migration(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_migration_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["migration_recovery"] = {
        "enabled": True,
        "tool": "migrate_v5_4_1_to_v6",
        "proof": _PROOF_NAME,
        "target_specific_serialization": True,
        "requires_exact_correlation_bound_proof": True,
        "requires_exact_report_hash": True,
        "migration_complete_but_proof_missing": "FAIL_CLOSED",
        "automatic_activation": False,
        "reexecutes_migration": False,
    }
    return contract


def _health_with_migration_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["migration_recovery"] = {
        "status": "ENABLED",
        "target_specific_serialization": True,
        "requires_report_and_mutation_proof": True,
        "automatic_activation": False,
    }
    return health


_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("migrate_v5_4_1_to_v6")
_v61._server.TOOL_HANDLERS["migrate_v5_4_1_to_v6"] = _migration_mcp_handler
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_migration_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_migration_recovery


def main() -> int:
    return _peer_receipt.main()


if __name__ == "__main__":
    raise SystemExit(main())
