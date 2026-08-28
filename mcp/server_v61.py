#!/usr/bin/env python3
"""v6.1 production MCP adapter over the stable compatibility server.

The large compatibility server remains readable and regression-stable. This
adapter hardens the public v6 surface without silently rewriting historical v5
semantics: Decision Saturation is the only production closure strategy, every
mutation requires durable idempotency, and callers can use optimistic
state-version guards.

The adapter journal is write-ahead. A PREPARED intent is durably written before
a mutation handler executes. If the process dies after the handler commits but
before the terminal receipt is written, a retry fails closed instead of blindly
executing the mutation a second time unless mutation-family-specific durable
state can mechanically prove and reconstruct the original result.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server as _server  # noqa: E402
from unified_runtime import ValidationError  # noqa: E402
from unified_runtime.resilience import exclusive_file_lock  # noqa: E402


_MUTATING_TOOLS = {
    "resolve_or_create_account",
    "start_investigation",
    "submit_research_objective",
    "compile_and_append_research_bundle",
    "append_information_record",
    "append_execution_receipt",
    "append_provider_receipt",
    "append_peer_receipt",
    "append_peer_discovery",
    "evaluate_peer",
    "promote_anchor",
    "close_pivot",
    "append_crm_writeback_receipt",
    "queue_pending_receipt",
    "sync_pending_receipts",
    "queue_host_bundle",
    "sync_pending_research_bundles",
    "sync_pending_bundles",
    "prepare_outreach",
    "render_outreach_action_card",
    "migrate_v5_4_1_to_v6",
}

_LEGACY_COMPATIBILITY_TOOLS = {
    "append_execution_receipt",
    "append_provider_receipt",
    "append_peer_receipt",
    "evaluate_commercial_readiness",
}

_PIVOT_TERMINAL_STATES = [
    "CONSUMED",
    "DUPLICATE",
    "LOW_VALUE",
    "BLOCKED",
    "EXHAUSTED",
]

_PRODUCTION_FRESHNESS = [
    "CURRENT_CONFIRMED",
    "CURRENT_LIKELY",
    "LIVE",
    "CURRENT",
    "RECENT",
    "HISTORICAL",
    "STALE",
    "UNKNOWN",
]

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
_ORIGINAL_TOOL_DESCRIPTORS = _server.tool_descriptors
_ORIGINAL_HANDLERS = dict(_server.TOOL_HANDLERS)
_WAL_SCHEMA = "cbi.mutation-wal.v6.1"
_TEST_CRASH_AFTER_HANDLER_ENV = "CBI_V61_TEST_CRASH_AFTER_HANDLER"
_AUTOMATIC_RECONCILIATION_TOOLS = {
    "resolve_or_create_account",
    "submit_research_objective",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _journal_path() -> Path:
    return _server.RUNTIME.store.root.parent / "mcp-idempotency-v61"


def _journal_root() -> Path:
    root = _journal_path()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_version(arguments: dict[str, Any]) -> int:
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    if not investigation_id:
        return 0
    try:
        events = _server.RUNTIME.store.read(investigation_id)
    except Exception:
        return 0
    return int(events[-1]["seq"]) if events else 0


def _idempotency_path(tool_name: str, key: str) -> Path:
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]+", "-", tool_name)
    safe_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return _journal_root() / f"{safe_tool}-{safe_key}.json"


def _fsync_directory(path: Path) -> None:
    """Best-effort directory-entry durability after atomic replace on POSIX."""

    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    payload = (_canonical(value) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _journal_status() -> dict[str, Any]:
    root = _journal_path()
    counts = {"PREPARED": 0, "COMMITTED": 0, "COMMITTED_ERROR": 0, "INVALID": 0}
    prepared: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                raw_status = str(row.get("status") or "").upper()
                if not raw_status and isinstance(row.get("result"), dict):
                    raw_status = "COMMITTED"
                if raw_status not in counts:
                    counts["INVALID"] += 1
                    continue
                counts[raw_status] += 1
                if raw_status == "PREPARED":
                    prepared.append({
                        "tool": str(row.get("tool") or ""),
                        "request_sha256": str(row.get("request_sha256") or ""),
                        "state_version_before": int(row.get("state_version_before") or 0),
                        "prepared_at": str(row.get("prepared_at") or ""),
                        "automatic_reconciliation_supported": str(row.get("tool") or "") in _AUTOMATIC_RECONCILIATION_TOOLS,
                    })
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                counts["INVALID"] += 1
    return {
        "schema": "cbi.mutation-wal-health.v6.1",
        "prepared_count": counts["PREPARED"],
        "committed_count": counts["COMMITTED"],
        "committed_error_count": counts["COMMITTED_ERROR"],
        "invalid_count": counts["INVALID"],
        "reconciliation_required": counts["PREPARED"] > 0 or counts["INVALID"] > 0,
        "prepared_intents": prepared,
        "automatic_reexecution_of_unproven_prepared": False,
        "automatic_reconciliation_tools": sorted(_AUTOMATIC_RECONCILIATION_TOOLS),
    }


def _normalize_start_contract(arguments: dict[str, Any]) -> dict[str, Any]:
    args = copy.deepcopy(arguments)
    policy = args.get("network_policy")
    if isinstance(policy, dict):
        strategy = str(policy.get("closure_strategy") or "").strip().upper()
        if strategy and strategy != "DECISION_SATURATION":
            raise ValidationError(
                "network_policy.closure_strategy must be DECISION_SATURATION on the v6.1 production surface"
            )
        policy.pop("closure_strategy", None)
    return args


def _validated_expected_version(expected: Any, before: int) -> None:
    if expected is None:
        return
    try:
        expected_int = int(expected)
    except (TypeError, ValueError) as exc:
        raise ValidationError("expected_state_version must be an integer") from exc
    if expected_int != before:
        raise ValidationError(f"STATE_VERSION_CONFLICT expected={expected_int} current={before}")


def _canonical_candidate_material(args: dict[str, Any]) -> tuple[dict[str, Any], str, bool] | None:
    candidate = args.get("candidate") or args.get("account")
    if not isinstance(candidate, dict):
        return None
    country = str(candidate.get("country") or "").strip()
    if not country:
        return None
    normalized = {**candidate, "country": country}
    requested_account_id = str(
        args.get("requested_account_id") or candidate.get("account_id") or ""
    ).strip()
    create_if_missing = args.get("create_if_missing", True)
    if not isinstance(create_if_missing, bool):
        return None
    return normalized, requested_account_id, create_if_missing


def _prepare_resource_snapshot(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name != "resolve_or_create_account":
        return {}
    material = _canonical_candidate_material(args)
    if material is None:
        return {}
    candidate, requested_account_id, create_if_missing = material
    registry = _server.RUNTIME.canonical_registry
    events = registry.log.read()
    resolution_before = registry.resolve(
        candidate,
        requested_account_id=requested_account_id,
    )
    return {
        "kind": "CANONICAL_ACCOUNT_REGISTRY",
        "registry_seq_before": len(events),
        "registry_tail_hash_before": events[-1]["event_hash"] if events else "0" * 64,
        "candidate_sha256": _digest(candidate),
        "requested_account_id": requested_account_id,
        "create_if_missing": create_if_missing,
        "resolution_before": resolution_before,
    }


def _commit_receipt(
    path: Path,
    prepared: dict[str, Any],
    result: dict[str, Any],
    after: int,
) -> None:
    _atomic_json_write(
        path,
        {
            **prepared,
            "status": "COMMITTED",
            "completed_at": _utc_now(),
            "state_version_after": after,
            "result_sha256": _digest(result),
            "result": result,
        },
    )


def _reconciled_meta(
    tool_name: str,
    stored: dict[str, Any],
    request_hash: str,
    after: int,
    proof: str,
) -> dict[str, Any]:
    return {
        "schema": "cbi.mutation-meta.v6.1",
        "tool": tool_name,
        "idempotency_key": str(stored.get("idempotency_key") or ""),
        "request_sha256": request_hash,
        "state_version_before": int(stored.get("state_version_before") or 0),
        "state_version_after": after,
        "replayed": True,
        "write_ahead_intent": True,
        "reconciled_after_crash": True,
        "reconciliation_proof": proof,
    }


def _reconcile_canonical_account(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    snapshot = stored.get("resource_snapshot_before")
    material = _canonical_candidate_material(args)
    if not isinstance(snapshot, dict) or snapshot.get("kind") != "CANONICAL_ACCOUNT_REGISTRY" or material is None:
        return None
    candidate, requested_account_id, create_if_missing = material
    if snapshot.get("candidate_sha256") != _digest(candidate):
        return None
    if str(snapshot.get("requested_account_id") or "") != requested_account_id:
        return None
    if bool(snapshot.get("create_if_missing")) != create_if_missing:
        return None

    prior = snapshot.get("resolution_before")
    if not isinstance(prior, dict):
        return None
    registry = _server.RUNTIME.canonical_registry
    raw_result: dict[str, Any]
    proof: str

    if prior.get("status") != "NOT_FOUND" or not create_if_missing:
        raw_result = {
            **copy.deepcopy(prior),
            "candidate_sha256": _digest(candidate),
            "registry_path": str(registry.log.path),
            "append_only": True,
        }
        proof = "PREPARED_PRIOR_CANONICAL_RESOLUTION"
    else:
        try:
            seq_before = int(snapshot.get("registry_seq_before") or 0)
            events = registry.log.read()
        except Exception:
            return None
        current = registry.resolve(
            candidate,
            requested_account_id=requested_account_id,
        )
        if current.get("status") != "MATCHED" or not isinstance(current.get("match"), dict):
            return None
        account_id = str(current["match"].get("account_id") or "")
        created = [
            event
            for event in events
            if int(event.get("seq") or 0) > seq_before
            and event.get("event_type") == "CANONICAL_ACCOUNT_CREATED"
            and str((event.get("payload") or {}).get("account_id") or "") == account_id
        ]
        if len(created) != 1:
            return None
        raw_result = {
            "status": "CREATED",
            "match": {
                "account_id": account_id,
                "score": 100,
                "reasons": ["ATOMIC_ALLOCATION"],
                "origin": "CANONICAL_REGISTRY",
            },
            "candidates": [],
            "candidate_sha256": _digest(candidate),
            "registry_path": str(registry.log.path),
            "append_only": True,
        }
        proof = "CANONICAL_ACCOUNT_CREATED_AFTER_PREPARED_REGISTRY_TAIL"

    result = {
        **raw_result,
        "mutation_meta": _reconciled_meta(
            "resolve_or_create_account",
            stored,
            request_hash,
            0,
            proof,
        ),
    }
    _commit_receipt(path, stored, result, 0)
    return result


def _reconcile_research_objective(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    raw = args.get("objective")
    if not investigation_id or not isinstance(raw, dict):
        return None
    try:
        state = _server.RUNTIME._v6_state(investigation_id)
    except Exception:
        return None

    objective_id = str(raw.get("objective_id") or "").strip()
    if not objective_id:
        objective_id = f"OBJ-{_digest({'investigation_id': investigation_id, **raw})[:16]}"
    record = state.get("objectives", {}).get(objective_id)
    if not isinstance(record, dict) or record.get("input_sha256") != _digest(raw):
        return None

    event_seq = int(record.get("_event_seq") or 0)
    before = int(stored.get("state_version_before") or 0)
    if event_seq <= 0:
        return None
    if event_seq <= before:
        raw_result = {
            "accepted": True,
            "deduplicated": True,
            "objective_id": objective_id,
        }
        after = before
    else:
        payload = {key: value for key, value in record.items() if not str(key).startswith("_")}
        raw_result = {
            "accepted": True,
            "deduplicated": False,
            **payload,
        }
        after = event_seq

    result = {
        **raw_result,
        "mutation_meta": _reconciled_meta(
            "submit_research_objective",
            stored,
            request_hash,
            after,
            "OBJECTIVE_ID_INPUT_HASH_AND_EVENT_SEQ",
        ),
    }
    _commit_receipt(path, stored, result, after)
    return result


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "resolve_or_create_account":
        return _reconcile_canonical_account(args, stored, request_hash, path)
    if tool_name == "submit_research_objective":
        return _reconcile_research_objective(args, stored, request_hash, path)
    return None


def _stored_terminal_result(stored: dict[str, Any], request_hash: str) -> dict[str, Any] | None:
    if stored.get("request_sha256") != request_hash:
        raise ValidationError(
            "IDEMPOTENCY_KEY_CONFLICT: key already committed with different request content"
        )
    status = str(stored.get("status") or "").upper()
    if isinstance(stored.get("result"), dict) and status in {"", "COMMITTED"}:
        result = copy.deepcopy(stored["result"])
        result.setdefault("mutation_meta", {})["replayed"] = True
        return result
    if status == "COMMITTED_ERROR":
        error = stored.get("error") if isinstance(stored.get("error"), dict) else {}
        message = str(error.get("message") or "stored mutation error")
        raise ValidationError(f"IDEMPOTENT_REPLAY_ERROR: {message}")
    if status == "PREPARED":
        return None
    raise ValidationError("IDEMPOTENCY_JOURNAL_INVALID_STATE")


def _invoke_mutation(
    tool_name: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    args = copy.deepcopy(arguments)
    if tool_name == "start_investigation":
        args = _normalize_start_contract(args)

    expected = args.pop("expected_state_version", None)
    key = str(args.get("idempotency_key") or "").strip()
    if not key:
        raise ValidationError(
            f"idempotency_key is required for production mutation tool {tool_name}"
        )
    if not _KEY_RE.fullmatch(key):
        raise ValidationError(
            "idempotency_key must be 8-160 characters using letters, digits, dot, underscore, colon or hyphen"
        )

    request_for_hash = copy.deepcopy(args)
    request_for_hash.pop("idempotency_key", None)
    request_hash = _digest({"tool": tool_name, "arguments": request_for_hash})
    path = _idempotency_path(tool_name, key)
    lock = path.with_suffix(".lock")

    with exclusive_file_lock(lock, timeout_seconds=60.0):
        # A terminal receipt always wins over a stale optimistic-concurrency
        # precondition. A PREPARED intent is reconciled only with durable proof.
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            terminal = _stored_terminal_result(stored, request_hash)
            if terminal is not None:
                return terminal
            reconciled = _reconcile_prepared(
                tool_name,
                args,
                stored,
                request_hash,
                path,
            )
            if reconciled is not None:
                return reconciled
            raise ValidationError(
                "MUTATION_RECONCILIATION_REQUIRED: prior attempt has a durable PREPARED intent without a terminal receipt and its mutation family cannot yet be mechanically reconciled; automatic re-execution is blocked to prevent duplicate mutation"
            )

        before = _state_version(args)
        _validated_expected_version(expected, before)
        prepared = {
            "schema": _WAL_SCHEMA,
            "status": "PREPARED",
            "tool": tool_name,
            "idempotency_key": key,
            "request_sha256": request_hash,
            "state_version_before": before,
            "prepared_at": _utc_now(),
        }
        resource_snapshot = _prepare_resource_snapshot(tool_name, args)
        if resource_snapshot:
            prepared["resource_snapshot_before"] = resource_snapshot
        _atomic_json_write(path, prepared)

        try:
            raw_result = handler(args)
            after = _state_version(args)
            result = {
                **raw_result,
                "mutation_meta": {
                    "schema": "cbi.mutation-meta.v6.1",
                    "tool": tool_name,
                    "idempotency_key": key,
                    "request_sha256": request_hash,
                    "state_version_before": before,
                    "state_version_after": after,
                    "replayed": False,
                    "write_ahead_intent": True,
                },
            }
        except Exception as exc:
            _atomic_json_write(
                path,
                {
                    **prepared,
                    "status": "COMMITTED_ERROR",
                    "completed_at": _utc_now(),
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
            )
            raise

        # Test-only cold-process crash injection. The PREPARED intent remains
        # durable while the handler's side effect has already committed.
        if os.environ.get(_TEST_CRASH_AFTER_HANDLER_ENV) == tool_name:
            os._exit(91)

        _commit_receipt(path, prepared, result, after)
        return result


def _wrap_handler(
    tool_name: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def wrapped(arguments: dict[str, Any]) -> dict[str, Any]:
        return _invoke_mutation(tool_name, handler, arguments)

    return wrapped


def _contract_with_adapter_wal(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_ORIGINAL_HANDLERS["get_runtime_contract"](arguments))
    contract["production_adapter_mutation_wal"] = {
        "schema": _WAL_SCHEMA,
        "write_ahead_intent_required": True,
        "terminal_states": ["COMMITTED", "COMMITTED_ERROR"],
        "indeterminate_state": "PREPARED",
        "prepared_auto_replay_without_proof": False,
        "prepared_unproven_retry_result": "MUTATION_RECONCILIATION_REQUIRED",
        "automatic_reconciliation_tools": sorted(_AUTOMATIC_RECONCILIATION_TOOLS),
        "automatic_reconciliation_requires_durable_proof": True,
        "exact_automatic_reconciliation_complete": False,
    }
    return contract


def _health_with_adapter_wal(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_ORIGINAL_HANDLERS["get_runtime_health"](arguments))
    wal = _journal_status()
    health["mutation_wal"] = wal
    if wal["reconciliation_required"]:
        health["status"] = "DEGRADED_RECONCILIATION_REQUIRED"
    return health


def hardened_tool_descriptors() -> list[dict[str, Any]]:
    tools = _ORIGINAL_TOOL_DESCRIPTORS()
    for tool in tools:
        name = tool.get("name")
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            continue
        properties = schema.setdefault("properties", {})

        if name == "start_investigation":
            network = properties.get("network_policy")
            if isinstance(network, dict):
                closure = network.get("properties", {}).get("closure_strategy")
                if isinstance(closure, dict):
                    closure.clear()
                    closure.update(
                        {
                            "type": "string",
                            "const": "DECISION_SATURATION",
                            "description": (
                                "Production v6 closure policy. Legacy queue saturation is compatibility history only."
                            ),
                        }
                    )

        if name == "compile_and_append_research_bundle":
            bundle = properties.get("bundle")
            observations = (
                bundle.get("properties", {}).get("observations")
                if isinstance(bundle, dict)
                else None
            )
            source = (
                observations.get("items", {}).get("properties", {}).get("source")
                if isinstance(observations, dict)
                else None
            )
            freshness = (
                source.get("properties", {}).get("freshness")
                if isinstance(source, dict)
                else None
            )
            if isinstance(freshness, dict):
                freshness["enum"] = list(_PRODUCTION_FRESHNESS)

        if name == "get_runtime_health":
            tool["description"] = (
                str(tool.get("description") or "")
                + " Also reports production-adapter mutation WAL status and unresolved PREPARED intents."
            )

        if name == "get_portfolio_queue":
            properties["include_non_active"] = {
                "type": "boolean",
                "description": "Include SUPERSEDED/ARCHIVED/QUARANTINED lifecycle rows for diagnostics; false by default.",
            }
            properties["include_non_production"] = {
                "type": "boolean",
                "description": "Include TEST/MIGRATION/PLACEHOLDER sessions for diagnostics; false by default.",
            }
            tool["description"] = (
                "Rank only one ACTIVE production investigation per canonical account and scope by default; "
                "historical duplicates are retained as SUPERSEDED and test/placeholder sessions are excluded."
            )

        if name == "prepare_outreach":
            tool["description"] = (
                "Consume one valid Closure ID and bind the exact Account-owned current verified Route from the "
                "Canonical Route View (compiled Evidence or safe append-only Information), plus history, authority, "
                "Subject, Body, Stage and expiry. It never sends."
            )

        if name == "close_pivot":
            status = properties.get("status")
            if isinstance(status, dict):
                status.clear()
                status.update(
                    {
                        "type": "string",
                        "enum": _PIVOT_TERMINAL_STATES,
                        "description": (
                            "Canonical terminal Pivot transition. Newly compiled Pivots are OPEN_MATERIAL or OPEN_OPTIONAL."
                        ),
                    }
                )
            properties["duplicate_of_pivot_id"] = {
                "type": "string",
                "description": "Required when status=DUPLICATE; must reference another Pivot in the investigation.",
            }
            properties["exhausted_by_objective_id"] = {
                "type": "string",
                "description": "Required when status=EXHAUSTED; must reference a later independent objective containing the Pivot value.",
            }
            properties["max_remaining_eiv"] = {
                "type": "number",
                "minimum": 0,
                "description": "Required for LOW_VALUE and EXHAUSTED and must be below the Decision Saturation threshold.",
            }
            tool["description"] = (
                "Transition one open Pivot into CONSUMED, DUPLICATE, LOW_VALUE, BLOCKED or EXHAUSTED. "
                "Only OPEN_MATERIAL blocks Decision Saturation; history is append-only."
            )

        if name in _MUTATING_TOOLS:
            properties["idempotency_key"] = {
                "type": "string",
                "minLength": 8,
                "maxLength": 160,
                "description": "Required durable replay key for every production mutation.",
            }
            required = schema.setdefault("required", [])
            if "idempotency_key" not in required:
                required.append("idempotency_key")
            properties.setdefault(
                "expected_state_version",
                {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Optional optimistic-concurrency guard; stale writers fail with STATE_VERSION_CONFLICT."
                    ),
                },
            )
            tool["description"] = (
                str(tool.get("description") or "")
                + " Production mutations use a durable write-ahead idempotency intent; PREPARED recovery occurs only when durable mutation-family proof can reconstruct the result, otherwise the adapter fails closed."
            )

        if name in _LEGACY_COMPATIBILITY_TOOLS:
            tool["description"] = "[LEGACY_COMPATIBILITY_ONLY] " + str(
                tool.get("description") or ""
            )
    return tools


# Patch only the adapter-facing descriptor/handler tables. The original module
# remains importable for compatibility regression tests and migration tooling.
_server.tool_descriptors = hardened_tool_descriptors
_server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_adapter_wal
_server.TOOL_HANDLERS["get_runtime_health"] = _health_with_adapter_wal
for _name in _MUTATING_TOOLS:
    if _name in _ORIGINAL_HANDLERS:
        _server.TOOL_HANDLERS[_name] = _wrap_handler(
            _name,
            _ORIGINAL_HANDLERS[_name],
        )


def main() -> int:
    return _server.main()


if __name__ == "__main__":
    raise SystemExit(main())
