#!/usr/bin/env python3
"""Crash-safe exact batch recovery for the three v6.1 sync mutation tools.

The outer mutation WAL freezes batch membership before execution. Each frozen
item then gets a deterministic child correlation and child WAL under a nested
journal directory that is not counted as a top-level user mutation. Exact item
outcomes are persisted in the existing append-only sidecar event log.

Recovery never re-selects the current queue. It resumes only the frozen item
list. An existing child PREPARED intent may be completed only from a durable,
correlated family-specific proof or an exact sidecar outcome snapshot. If a
child PREPARED intent has neither proof, automatic re-execution is blocked.
Items with no child WAL are mechanically proven not to have started and may be
executed during batch recovery.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_correlated as _correlated  # noqa: E402
from mcp import server_v61_migration_recovery as _migration  # noqa: E402
from unified_runtime.resilience import exclusive_file_lock  # noqa: E402


_v61 = _migration._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_PREPARE_RESOURCE_SNAPSHOT = _v61._prepare_resource_snapshot
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]

_PENDING_TOOL = "sync_pending_receipts"
_HOST_TOOLS = {"sync_pending_bundles", "sync_pending_research_bundles"}
_SYNC_TOOLS = {_PENDING_TOOL, *_HOST_TOOLS}
_PENDING_TERMINAL = {"SYNCED", "DEDUPLICATED"}
_HOST_TERMINAL = {"SYNCED"}
_BATCH_PROOF = "FROZEN_BATCH_WITH_CORRELATED_EXACT_ITEM_OUTCOMES"
_CHILD_SCHEMA = "cbi.sync-item-wal.v6.1"
_TEST_CRASH_AFTER_CHILD_PREPARED = "CBI_V61_TEST_CRASH_SYNC_AFTER_CHILD_PREPARED"
_TEST_CRASH_AFTER_CHILD_HANDLER = "CBI_V61_TEST_CRASH_SYNC_AFTER_CHILD_HANDLER"
_TEST_CRASH_AFTER_ITEM_RECORDED = "CBI_V61_TEST_CRASH_SYNC_AFTER_ITEM_RECORDED"


def _arg_limit(args: dict[str, Any], *, host: bool) -> int | None:
    raw = args.get("limit", 100)
    if host:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
    else:
        if not isinstance(raw, int):
            return None
        value = raw
    return value if 1 <= value <= 1000 else None


def _pending_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    limit = _arg_limit(args, host=False)
    dry_run = args.get("dry_run", False)
    if limit is None or not isinstance(dry_run, bool):
        return {}
    investigation_id = str(args.get("investigation_id") or "").strip()
    rows = [
        row
        for row in _RUNTIME.pending_journal.entries()
        if str(row.get("status") or "") not in _PENDING_TERMINAL
    ]
    if investigation_id:
        rows = [row for row in rows if str(row.get("investigation_id") or "") == investigation_id]
    items = [
        {
            "journal_id": str(row.get("journal_id") or ""),
            "investigation_id": str(row.get("investigation_id") or ""),
            "target_tool": str(row.get("target_tool") or ""),
            "request_sha256": str(row.get("request_sha256") or ""),
        }
        for row in rows[:limit]
    ]
    return {
        "kind": "PENDING_RECEIPT_SYNC_BATCH",
        "tool": _PENDING_TOOL,
        "investigation_id": investigation_id,
        "limit": limit,
        "dry_run": dry_run,
        "items": items,
        "items_sha256": _v61._digest(items),
    }


def _host_snapshot(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    limit = _arg_limit(args, host=True)
    if limit is None:
        return {}
    investigation_id = str(args.get("investigation_id") or "").strip()
    dry_run = args.get("dry_run") is True
    queue = _RUNTIME._v6_queue()
    rows = [
        row
        for row in queue.entries()
        if str(row.get("status") or "") not in _HOST_TERMINAL
    ]
    if investigation_id:
        rows = [row for row in rows if str(row.get("investigation_id") or "") == investigation_id]
    items = [
        {
            "bundle_queue_id": str(row.get("bundle_queue_id") or ""),
            "investigation_id": str(row.get("investigation_id") or ""),
            "request_sha256": str(row.get("request_sha256") or ""),
        }
        for row in rows[:limit]
    ]
    return {
        "kind": "HOST_BUNDLE_SYNC_BATCH",
        "tool": tool_name,
        "investigation_id": investigation_id,
        "limit": limit,
        "dry_run": dry_run,
        "items": items,
        "items_sha256": _v61._digest(items),
    }


def _prepare_resource_snapshot(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == _PENDING_TOOL:
        return _pending_snapshot(args)
    if tool_name in _HOST_TOOLS:
        return _host_snapshot(tool_name, args)
    return _BASE_PREPARE_RESOURCE_SNAPSHOT(tool_name, args)


def _validate_snapshot(tool_name: str, args: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    snapshot = stored.get("resource_snapshot_before")
    expected_kind = "PENDING_RECEIPT_SYNC_BATCH" if tool_name == _PENDING_TOOL else "HOST_BUNDLE_SYNC_BATCH"
    if not isinstance(snapshot, dict) or snapshot.get("kind") != expected_kind:
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: sync batch has no frozen membership snapshot")
    items = snapshot.get("items")
    if not isinstance(items, list) or snapshot.get("items_sha256") != _v61._digest(items):
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen sync batch membership is invalid")
    if str(snapshot.get("tool") or "") != tool_name:
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen sync batch tool mismatch")
    current_limit = _arg_limit(args, host=tool_name in _HOST_TOOLS)
    if current_limit is None or int(snapshot.get("limit") or 0) != current_limit:
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen sync batch limit mismatch")
    current_investigation = str(args.get("investigation_id") or "").strip()
    if str(snapshot.get("investigation_id") or "") != current_investigation:
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen sync batch investigation mismatch")
    current_dry_run = args.get("dry_run", False) is True
    if bool(snapshot.get("dry_run")) != current_dry_run:
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen sync batch dry-run mismatch")
    return snapshot


def _outer_stored(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("idempotency_key") or "").strip()
    path = _v61._idempotency_path(tool_name, key)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _v61.ValidationError("sync outer WAL is unreadable") from exc
    if stored.get("status") != "PREPARED":
        raise _v61.ValidationError("sync outer WAL is not PREPARED during batch execution")
    return stored


def _child_root() -> Path:
    root = _v61._journal_root() / "sync-item-wal"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _child_identity(
    outer_correlation_id: str,
    item_tool: str,
    item_id: str,
    request_sha256: str,
) -> dict[str, str]:
    material = f"{outer_correlation_id}:{item_tool}:{item_id}:{request_sha256}"
    correlation_id = "MUTITEM-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return {
        "schema": "cbi.mutation-correlation.v6.1",
        "correlation_id": correlation_id,
        "tool": item_tool,
    }


def _child_path(correlation_id: str) -> Path:
    return _child_root() / f"{correlation_id}.json"


def _child_request_hash(item_tool: str, arguments: dict[str, Any]) -> str:
    return _v61._digest({"tool": item_tool, "arguments": arguments})


def _child_prepared(
    item_tool: str,
    item_id: str,
    arguments: dict[str, Any],
    outer_correlation_id: str,
    expected_request_sha256: str,
) -> tuple[Path, dict[str, Any], dict[str, str], bool]:
    correlation = _child_identity(
        outer_correlation_id,
        item_tool,
        item_id,
        expected_request_sha256,
    )
    path = _child_path(correlation["correlation_id"])
    request_hash = _child_request_hash(item_tool, arguments)
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: child sync WAL is unreadable") from exc
        if (
            stored.get("schema") != _v61._WAL_SCHEMA
            or str(stored.get("tool") or "") != item_tool
            or str(stored.get("request_sha256") or "") != request_hash
            or str(stored.get("mutation_correlation_id") or "") != correlation["correlation_id"]
            or str(stored.get("batch_item_id") or "") != item_id
        ):
            raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: child sync WAL identity mismatch")
        return path, stored, correlation, False

    before = _v61._state_version(arguments)
    prepared = {
        "schema": _v61._WAL_SCHEMA,
        "child_schema": _CHILD_SCHEMA,
        "status": "PREPARED",
        "tool": item_tool,
        "idempotency_key": correlation["correlation_id"],
        "request_sha256": request_hash,
        "state_version_before": before,
        "prepared_at": _v61._utc_now(),
        "mutation_correlation_id": correlation["correlation_id"],
        "batch_parent_correlation_id": outer_correlation_id,
        "batch_item_id": item_id,
        "queue_request_sha256": expected_request_sha256,
    }
    token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        _v61._atomic_json_write(path, prepared)
    finally:
        _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)
    return path, prepared, correlation, True


def _strip_mutation_meta(result: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in result.items() if key != "mutation_meta"}


def _child_committed_outcome(stored: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if str(stored.get("status") or "").upper() != "COMMITTED":
        return None, None
    result = stored.get("result")
    if not isinstance(result, dict):
        return None, None
    outcome = result.get("batch_item_outcome")
    if isinstance(outcome, dict):
        return copy.deepcopy(outcome), None
    return None, _strip_mutation_meta(result)


def _commit_child_outcome(
    path: Path,
    prepared: dict[str, Any],
    correlation: dict[str, str],
    arguments: dict[str, Any],
    outcome: dict[str, Any],
) -> None:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _v61.ValidationError("child sync WAL became unreadable") from exc
    if str(current.get("status") or "").upper() != "PREPARED":
        return
    after = _v61._state_version(arguments)
    wrapped = {
        "batch_item_outcome": copy.deepcopy(outcome),
        "mutation_meta": {
            "schema": "cbi.mutation-meta.v6.1",
            "tool": str(prepared.get("tool") or ""),
            "idempotency_key": correlation["correlation_id"],
            "request_sha256": str(prepared.get("request_sha256") or ""),
            "state_version_before": int(prepared.get("state_version_before") or 0),
            "state_version_after": after,
            "replayed": False,
            "write_ahead_intent": True,
            "batch_child": True,
        },
    }
    token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        _v61._commit_receipt(path, prepared, wrapped, after)
    finally:
        _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)


def _sidecar_index(events: list[dict[str, Any]], event_type: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("event_type") != event_type:
            continue
        correlation = event.get("mutation_correlation")
        if not isinstance(correlation, dict):
            continue
        correlation_id = str(correlation.get("correlation_id") or "")
        if correlation_id:
            index.setdefault(correlation_id, []).append(event)
    return index


def _exact_sidecar_outcome(
    index: dict[str, list[dict[str, Any]]],
    correlation: dict[str, str],
    *,
    item_id_field: str,
    item_id: str,
    request_sha256: str,
) -> dict[str, Any] | None:
    matches = index.get(correlation["correlation_id"], [])
    if not matches:
        return None
    if len(matches) != 1:
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: ambiguous child sync sidecar outcomes")
    event = matches[0]
    persisted_correlation = event.get("mutation_correlation") or {}
    payload = event.get("payload")
    if (
        not isinstance(payload, dict)
        or str(persisted_correlation.get("tool") or "") != correlation["tool"]
        or str(payload.get(item_id_field) or "") != item_id
        or str(payload.get("request_sha256") or "") != request_sha256
    ):
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: child sync sidecar identity mismatch")
    outcome = payload.get("outcome_snapshot")
    if not isinstance(outcome, dict) or str(payload.get("outcome_sha256") or "") != _v61._digest(outcome):
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: child sync outcome snapshot is invalid")
    return copy.deepcopy(outcome)


def _record_pending_outcome(
    envelope: dict[str, Any],
    outcome: dict[str, Any],
    correlation: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "journal_id": envelope["journal_id"],
        "investigation_id": envelope["investigation_id"],
        "target_tool": envelope["target_tool"],
        "request_sha256": envelope["request_sha256"],
        "status": outcome["status"],
        "result_digest": _v61._digest(outcome.get("result") or {}),
        "error": str(outcome.get("error") or outcome.get("reason") or ""),
        "outcome_snapshot": copy.deepcopy(outcome),
        "outcome_sha256": _v61._digest(outcome),
    }
    token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        return _RUNTIME.pending_journal.events.append("PENDING_RECEIPT_SYNC_RESULT", payload)
    finally:
        _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)


def _record_host_outcome(
    queue: Any,
    envelope: dict[str, Any],
    outcome: dict[str, Any],
    correlation: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "bundle_queue_id": envelope["bundle_queue_id"],
        "request_sha256": envelope["request_sha256"],
        "status": outcome["status"],
        "result_sha256": _v61._digest(outcome.get("result") or {}),
        "error": str(outcome.get("error") or ""),
        "outcome_snapshot": copy.deepcopy(outcome),
        "outcome_sha256": _v61._digest(outcome),
    }
    token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        return queue.events.append("HOST_BUNDLE_SYNC_RESULT", payload)
    finally:
        _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)


def _maybe_test_crash(env_name: str, outer_tool: str, code: int) -> None:
    if os.environ.get(env_name) == outer_tool:
        os._exit(code)


def _pending_handlers() -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    return {
        "append_information_record": _RUNTIME.append_information_record,
        "append_execution_receipt": _RUNTIME.append_execution_receipt,
        "append_provider_receipt": _RUNTIME.append_provider_receipt,
        "append_peer_receipt": _RUNTIME.append_peer_receipt,
        "append_crm_writeback_receipt": _RUNTIME.append_crm_writeback_receipt,
    }


def _pending_success_outcome(journal_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"journal_id": journal_id, "status": "SYNCED", "result": copy.deepcopy(result)}


def _host_success_outcome(bundle_queue_id: str, result: dict[str, Any]) -> dict[str, Any]:
    status = "SYNCED" if str(result.get("status") or "") == "ACCEPTED" else str(result.get("status") or "")
    return {"bundle_queue_id": bundle_queue_id, "status": status, "result": copy.deepcopy(result)}


def _recover_target_result(
    item_tool: str,
    arguments: dict[str, Any],
    stored: dict[str, Any],
    path: Path,
    correlation: dict[str, str],
) -> dict[str, Any] | None:
    request_hash = str(stored.get("request_sha256") or "")
    token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        recovered = _BASE_RECONCILE_PREPARED(
            item_tool,
            arguments,
            stored,
            request_hash,
            path,
        )
    finally:
        _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)
    return _strip_mutation_meta(recovered) if isinstance(recovered, dict) else None


def _pending_item(
    outer_tool: str,
    outer_correlation_id: str,
    item: dict[str, Any],
    sidecars: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    journal_id = str(item.get("journal_id") or "")
    envelope = _RUNTIME.pending_journal.load(journal_id)
    if (
        str(envelope.get("request_sha256") or "") != str(item.get("request_sha256") or "")
        or str(envelope.get("target_tool") or "") != str(item.get("target_tool") or "")
    ):
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen pending receipt changed")
    target_tool = str(envelope["target_tool"])
    payload = copy.deepcopy(envelope["payload"])
    path, child, correlation, created = _child_prepared(
        target_tool,
        journal_id,
        payload,
        outer_correlation_id,
        str(envelope["request_sha256"]),
    )
    sidecar = _exact_sidecar_outcome(
        sidecars,
        correlation,
        item_id_field="journal_id",
        item_id=journal_id,
        request_sha256=str(envelope["request_sha256"]),
    )
    if sidecar is not None:
        _commit_child_outcome(path, child, correlation, payload, sidecar)
        return sidecar

    committed_outcome, committed_target = _child_committed_outcome(child)
    if committed_outcome is not None:
        event = _record_pending_outcome(envelope, committed_outcome, correlation)
        sidecars[correlation["correlation_id"]] = [event]
        return committed_outcome
    if committed_target is not None:
        outcome = _pending_success_outcome(journal_id, committed_target)
        event = _record_pending_outcome(envelope, outcome, correlation)
        sidecars[correlation["correlation_id"]] = [event]
        return outcome

    if not created:
        recovered = _recover_target_result(target_tool, payload, child, path, correlation)
        if recovered is None:
            raise _v61.ValidationError(
                "MUTATION_RECONCILIATION_REQUIRED: existing pending-sync child PREPARED intent has no exact durable proof"
            )
        outcome = _pending_success_outcome(journal_id, recovered)
        event = _record_pending_outcome(envelope, outcome, correlation)
        sidecars[correlation["correlation_id"]] = [event]
        return outcome

    _maybe_test_crash(_TEST_CRASH_AFTER_CHILD_PREPARED, outer_tool, 93)
    handler = _pending_handlers().get(target_tool)
    if handler is None:
        outcome = {"journal_id": journal_id, "status": "FAILED_VALIDATION", "error": "handler unavailable"}
    else:
        token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
        try:
            try:
                result = handler(payload)
                _maybe_test_crash(_TEST_CRASH_AFTER_CHILD_HANDLER, outer_tool, 92)
                outcome = _pending_success_outcome(journal_id, result)
            except _v61.ValidationError as exc:
                if _RUNTIME._pending_equivalent(target_tool, payload):
                    outcome = {"journal_id": journal_id, "status": "DEDUPLICATED", "reason": str(exc)}
                else:
                    outcome = {"journal_id": journal_id, "status": "FAILED_VALIDATION", "error": str(exc)}
            except Exception as exc:
                outcome = {
                    "journal_id": journal_id,
                    "status": "RETRYABLE_FAILURE",
                    "error": f"{type(exc).__name__}: {exc}",
                }
        finally:
            _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)
    event = _record_pending_outcome(envelope, outcome, correlation)
    sidecars[correlation["correlation_id"]] = [event]
    _maybe_test_crash(_TEST_CRASH_AFTER_ITEM_RECORDED, outer_tool, 94)
    _commit_child_outcome(path, child, correlation, payload, outcome)
    return outcome


def _host_item(
    outer_tool: str,
    outer_correlation_id: str,
    item: dict[str, Any],
    sidecars: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    queue = _RUNTIME._v6_queue()
    queue_id = str(item.get("bundle_queue_id") or "")
    envelope = queue.load(queue_id)
    if str(envelope.get("request_sha256") or "") != str(item.get("request_sha256") or ""):
        raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: frozen host bundle changed")
    payload = copy.deepcopy(envelope["payload"])
    item_tool = "compile_and_append_research_bundle"
    path, child, correlation, created = _child_prepared(
        item_tool,
        queue_id,
        payload,
        outer_correlation_id,
        str(envelope["request_sha256"]),
    )
    sidecar = _exact_sidecar_outcome(
        sidecars,
        correlation,
        item_id_field="bundle_queue_id",
        item_id=queue_id,
        request_sha256=str(envelope["request_sha256"]),
    )
    if sidecar is not None:
        _commit_child_outcome(path, child, correlation, payload, sidecar)
        return sidecar

    committed_outcome, committed_target = _child_committed_outcome(child)
    if committed_outcome is not None:
        event = _record_host_outcome(queue, envelope, committed_outcome, correlation)
        sidecars[correlation["correlation_id"]] = [event]
        return committed_outcome
    if committed_target is not None:
        outcome = _host_success_outcome(queue_id, committed_target)
        event = _record_host_outcome(queue, envelope, outcome, correlation)
        sidecars[correlation["correlation_id"]] = [event]
        return outcome

    if not created:
        recovered = _recover_target_result(item_tool, payload, child, path, correlation)
        if recovered is None:
            raise _v61.ValidationError(
                "MUTATION_RECONCILIATION_REQUIRED: existing host-sync child PREPARED intent has no exact durable proof"
            )
        outcome = _host_success_outcome(queue_id, recovered)
        event = _record_host_outcome(queue, envelope, outcome, correlation)
        sidecars[correlation["correlation_id"]] = [event]
        return outcome

    _maybe_test_crash(_TEST_CRASH_AFTER_CHILD_PREPARED, outer_tool, 93)
    token = _correlated._ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        try:
            result = _RUNTIME.compile_and_append_research_bundle(payload)
            _maybe_test_crash(_TEST_CRASH_AFTER_CHILD_HANDLER, outer_tool, 92)
            outcome = _host_success_outcome(queue_id, result)
        except _v61.ValidationError as exc:
            outcome = {"bundle_queue_id": queue_id, "status": "FAILED_VALIDATION", "error": str(exc)}
    finally:
        _correlated._ACTIVE_MUTATION_CORRELATION.reset(token)
    event = _record_host_outcome(queue, envelope, outcome, correlation)
    sidecars[correlation["correlation_id"]] = [event]
    _maybe_test_crash(_TEST_CRASH_AFTER_ITEM_RECORDED, outer_tool, 94)
    _commit_child_outcome(path, child, correlation, payload, outcome)
    return outcome


def _run_pending_batch(tool_name: str, args: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    snapshot = _validate_snapshot(tool_name, args, stored)
    items = snapshot["items"]
    if snapshot["dry_run"]:
        outcomes = [
            {
                "journal_id": str(item.get("journal_id") or ""),
                "status": "WOULD_SYNC",
                "target_tool": str(item.get("target_tool") or ""),
            }
            for item in items
        ]
    else:
        outer_correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
        if not outer_correlation_id:
            raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: sync batch lacks outer correlation")
        sidecars = _sidecar_index(
            _RUNTIME.pending_journal.events.read(),
            "PENDING_RECEIPT_SYNC_RESULT",
        )
        outcomes = [
            _pending_item(tool_name, outer_correlation_id, item, sidecars)
            for item in items
        ]
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
    return {"dry_run": bool(snapshot["dry_run"]), "processed": len(outcomes), "counts": counts, "outcomes": outcomes}


def _run_host_batch(tool_name: str, args: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    snapshot = _validate_snapshot(tool_name, args, stored)
    items = snapshot["items"]
    if snapshot["dry_run"]:
        outcomes = [
            {"bundle_queue_id": str(item.get("bundle_queue_id") or ""), "status": "WOULD_SYNC"}
            for item in items
        ]
    else:
        outer_correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
        if not outer_correlation_id:
            raise _v61.ValidationError("MUTATION_RECONCILIATION_REQUIRED: sync batch lacks outer correlation")
        queue = _RUNTIME._v6_queue()
        sidecars = _sidecar_index(queue.events.read(), "HOST_BUNDLE_SYNC_RESULT")
        outcomes = [
            _host_item(tool_name, outer_correlation_id, item, sidecars)
            for item in items
        ]
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
    return {"processed": len(outcomes), "counts": counts, "outcomes": outcomes, "dry_run": bool(snapshot["dry_run"])}


def _fresh_sync_handler(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    stored = _outer_stored(tool_name, args)
    if tool_name == _PENDING_TOOL:
        return _run_pending_batch(tool_name, args, stored)
    return _run_host_batch(tool_name, args, stored)


def _sync_mcp_handler(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == _PENDING_TOOL:
        lock = _RUNTIME.pending_journal.root / "journal-sync.lock"
    else:
        lock = _RUNTIME._v6_queue().root / "host-queue-sync.lock"
    with exclusive_file_lock(lock, timeout_seconds=60.0):
        return _v61._invoke_mutation(
            tool_name,
            lambda args: _fresh_sync_handler(tool_name, args),
            arguments,
        )


def _reconcile_sync_batch(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any]:
    raw = (
        _run_pending_batch(tool_name, args, stored)
        if tool_name == _PENDING_TOOL
        else _run_host_batch(tool_name, args, stored)
    )
    after = _v61._state_version(args)
    result = {
        **raw,
        "mutation_meta": _v61._reconciled_meta(
            tool_name,
            stored,
            request_hash,
            after,
            _BATCH_PROOF,
        ),
    }
    _v61._commit_receipt(path, stored, result, after)
    return result


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name in _SYNC_TOOLS:
        return _reconcile_sync_batch(tool_name, args, stored, request_hash, path)
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_sync_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["batch_sync_recovery"] = {
        "enabled": True,
        "tools": sorted(_SYNC_TOOLS),
        "batch_membership_frozen_before_execution": True,
        "resumes_only_frozen_items": True,
        "item_child_wal": True,
        "item_exact_outcome_snapshot": True,
        "item_event_correlation": True,
        "cross_key_result_claiming": False,
        "child_prepared_without_exact_proof": "FAIL_CLOSED",
        "current_queue_reselection_on_retry": False,
        "proof": _BATCH_PROOF,
    }
    return contract


def _health_with_sync_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["batch_sync_recovery"] = {
        "status": "ENABLED",
        "tools": sorted(_SYNC_TOOLS),
        "frozen_batch_membership": True,
        "unproven_child_prepared_reexecution": False,
    }
    return health


_v61._prepare_resource_snapshot = _prepare_resource_snapshot
_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.update(_SYNC_TOOLS)
_v61._server.TOOL_HANDLERS[_PENDING_TOOL] = lambda arguments: _sync_mcp_handler(_PENDING_TOOL, arguments)
_v61._server.TOOL_HANDLERS["sync_pending_bundles"] = lambda arguments: _sync_mcp_handler("sync_pending_bundles", arguments)
_v61._server.TOOL_HANDLERS["sync_pending_research_bundles"] = lambda arguments: _sync_mcp_handler("sync_pending_research_bundles", arguments)
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_sync_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_sync_recovery


def main() -> int:
    return _migration.main()


if __name__ == "__main__":
    raise SystemExit(main())
