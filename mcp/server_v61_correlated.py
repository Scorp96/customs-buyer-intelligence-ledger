#!/usr/bin/env python3
"""Production mutation-event correlation overlay for CBI v6.1.

Every production MCP mutation receives a deterministic correlation ID derived
from the tool name and validated idempotency key. While that mutation runs,
every append-only SessionStore and sidecar HashChainLog event records the same
correlation at the event-envelope level. Historical events and direct Runtime
calls remain unchanged.

The correlation object never contains the raw idempotency key. Historical
business payloads keep their existing compatibility semantics. Correlation does
not by itself authorize replay; it gives family-specific reconcilers exact
WAL-to-durable-event attribution under concurrency, including mutations whose
business IDs are random.
"""

from __future__ import annotations

import copy
import hashlib
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_recovery as _recovery  # noqa: E402
from unified_runtime import core as _core  # noqa: E402
from unified_runtime import resilience as _resilience  # noqa: E402


_v61 = _recovery._v61
_BASE_INVOKE_MUTATION = _v61._invoke_mutation
_BASE_ATOMIC_JSON_WRITE = _v61._atomic_json_write
_BASE_SESSION_EVENT = _core.SessionStore._event
_BASE_HASHCHAIN_APPEND = _resilience.HashChainLog.append
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]

_ACTIVE_MUTATION_CORRELATION: ContextVar[dict[str, str] | None] = ContextVar(
    "cbi_v61_active_mutation_correlation",
    default=None,
)


def _correlation(tool_name: str, arguments: dict[str, Any]) -> dict[str, str] | None:
    key = str(arguments.get("idempotency_key") or "").strip()
    if not key:
        return None
    correlation_id = "MUTCORR-" + hashlib.sha256(
        f"{tool_name}:{key}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema": "cbi.mutation-correlation.v6.1",
        "correlation_id": correlation_id,
        "tool": tool_name,
    }


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    row = copy.deepcopy(value)
    correlation = _ACTIVE_MUTATION_CORRELATION.get()
    if correlation and row.get("schema") == _v61._WAL_SCHEMA:
        row.setdefault("mutation_correlation_id", correlation["correlation_id"])
    _BASE_ATOMIC_JSON_WRITE(path, row)


def _session_event(
    seq: int,
    previous: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    event = _BASE_SESSION_EVENT(seq, previous, event_type, payload)
    correlation = _ACTIVE_MUTATION_CORRELATION.get()
    if correlation:
        event["mutation_correlation"] = copy.deepcopy(correlation)
        unsigned = {key: value for key, value in event.items() if key != "event_hash"}
        event["event_hash"] = _core.digest(unsigned)
    return event


def _hashchain_append(
    self: _resilience.HashChainLog,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    correlation = _ACTIVE_MUTATION_CORRELATION.get()
    if correlation is None:
        return _BASE_HASHCHAIN_APPEND(self, event_type, payload)
    with _resilience.exclusive_file_lock(self.lock_path):
        events = self._read_unlocked()
        event: dict[str, Any] = {
            "seq": len(events) + 1,
            "prev_hash": events[-1]["event_hash"] if events else "0" * 64,
            "event_type": event_type,
            "recorded_at": _resilience.iso_utc(),
            "payload": payload,
            "mutation_correlation": copy.deepcopy(correlation),
        }
        event["event_hash"] = _resilience.digest(event)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_resilience.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event


def _invoke_mutation(
    tool_name: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    correlation = _correlation(tool_name, arguments)
    if correlation is None:
        return _BASE_INVOKE_MUTATION(tool_name, handler, arguments)
    token = _ACTIVE_MUTATION_CORRELATION.set(correlation)
    try:
        return _BASE_INVOKE_MUTATION(tool_name, handler, arguments)
    finally:
        _ACTIVE_MUTATION_CORRELATION.reset(token)


def _contract_with_correlation(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["durable_event_correlation"] = {
        "schema": "cbi.mutation-correlation.v6.1",
        "enabled": True,
        "covers_session_store_events": True,
        "covers_sidecar_hash_chain_events": True,
        "correlation_contains_raw_idempotency_key": False,
        "historical_business_payloads_rewritten": False,
        "correlation_alone_authorizes_replay": False,
        "purpose": "Exact WAL-to-durable-event attribution under concurrent production mutations.",
    }
    return contract


def _health_with_correlation(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["mutation_event_correlation"] = {
        "status": "ENABLED",
        "schema": "cbi.mutation-correlation.v6.1",
        "correlation_contains_raw_idempotency_key": False,
    }
    return health


# Patch event emitters before any production mutation executes through this
# entrypoint. Existing on-disk events remain valid because correlation is an
# optional event-envelope field included in the normal hash calculation.
_core.SessionStore._event = staticmethod(_session_event)
_resilience.HashChainLog.append = _hashchain_append
_v61._atomic_json_write = _atomic_json_write
_v61._invoke_mutation = _invoke_mutation
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_correlation
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_correlation


def main() -> int:
    return _recovery.main()


if __name__ == "__main__":
    raise SystemExit(main())
