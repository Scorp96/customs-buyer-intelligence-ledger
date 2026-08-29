#!/usr/bin/env python3
"""Exact research-bundle compiler crash recovery over Peer/Pivot recovery.

A successful new bundle compile persists a final V6_RESEARCH_BUNDLE_COMPILED
summary after all observation events.  The summary contains the exact public
result material.  Recovery accepts only the single summary event emitted by the
same mutation correlation after the WAL PREPARED state and whose input digest
matches the retried request.

No final summary, ambiguous correlation, historical uncorrelated rows, and
pre-existing bundle replay paths remain fail-closed.  Recovery never re-runs
the compiler and therefore never appends a second observation or summary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_peer_pivot_recovery as _peer_pivot  # noqa: E402


_v61 = _peer_pivot._v61
_RUNTIME = _v61._server.RUNTIME
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_BASE_CONTRACT_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_contract"]
_BASE_HEALTH_HANDLER = _v61._server.TOOL_HANDLERS["get_runtime_health"]

_BUNDLE_PROOF = "CORRELATED_FINAL_RESEARCH_BUNDLE_SUMMARY"


def _expected_material(args: dict[str, Any]) -> tuple[str, str, str] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    bundle = args.get("bundle")
    if not investigation_id or not isinstance(bundle, dict):
        return None
    observations = bundle.get("observations")
    if not isinstance(observations, list):
        return None
    try:
        encoded = json.dumps(
            {"investigation_id": investigation_id, "observations": observations},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    input_sha256 = hashlib.sha256(encoded).hexdigest()
    bundle_id = str(bundle.get("bundle_id") or f"BUNDLE-{input_sha256[:16]}").strip()
    if not bundle_id:
        return None
    return investigation_id, input_sha256, bundle_id


def _matching_summary(
    investigation_id: str,
    input_sha256: str,
    bundle_id: str,
    stored: dict[str, Any],
) -> dict[str, Any] | None:
    correlation_id = str(stored.get("mutation_correlation_id") or "").strip()
    if not correlation_id:
        return None
    try:
        before = int(stored.get("state_version_before") or 0)
        events = _RUNTIME.store.read(investigation_id)
    except Exception:
        return None
    matches: list[dict[str, Any]] = []
    for event in events:
        if int(event.get("seq") or 0) <= before:
            continue
        if event.get("event_type") != "V6_RESEARCH_BUNDLE_COMPILED":
            continue
        correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        if not isinstance(correlation, dict) or not isinstance(payload, dict):
            continue
        if (
            str(correlation.get("correlation_id") or "") == correlation_id
            and str(correlation.get("tool") or "") == "compile_and_append_research_bundle"
            and str(payload.get("schema") or "") == "cbi.research-bundle-result.v6.1"
            and str(payload.get("investigation_id") or "") == investigation_id
            and str(payload.get("input_sha256") or "") == input_sha256
            and str(payload.get("bundle_id") or "") == bundle_id
            and isinstance(payload.get("outcomes"), list)
            and isinstance(payload.get("accepted_observation_ids"), list)
            and str(payload.get("status") or "") in {"ACCEPTED", "PARTIAL_SUCCESS", "REJECTED"}
        ):
            matches.append(event)
    return matches[0] if len(matches) == 1 else None


def _reconcile_bundle(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    expected = _expected_material(args)
    if expected is None:
        return None
    investigation_id, input_sha256, bundle_id = expected
    event = _matching_summary(
        investigation_id,
        input_sha256,
        bundle_id,
        stored,
    )
    if event is None:
        return None
    payload = copy.deepcopy(event["payload"])
    result = {
        **payload,
        "idempotent_replay": False,
        "mutation_meta": _v61._reconciled_meta(
            "compile_and_append_research_bundle",
            stored,
            request_hash,
            int(event["seq"]),
            _BUNDLE_PROOF,
        ),
    }
    _v61._commit_receipt(path, stored, result, int(event["seq"]))
    return result


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "compile_and_append_research_bundle":
        reconciled = _reconcile_bundle(args, stored, request_hash, path)
        if reconciled is not None:
            return reconciled
    return _BASE_RECONCILE_PREPARED(tool_name, args, stored, request_hash, path)


def _contract_with_bundle_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(_BASE_CONTRACT_HANDLER(arguments))
    wal = contract.setdefault("production_adapter_mutation_wal", {})
    wal["research_bundle_recovery"] = {
        "enabled": True,
        "proof": _BUNDLE_PROOF,
        "requires_exact_event_correlation": True,
        "requires_final_bundle_summary": True,
        "reexecutes_compiler": False,
        "preexisting_bundle_replay_after_crash": "FAIL_CLOSED",
        "missing_or_ambiguous_summary": "FAIL_CLOSED",
    }
    return contract


def _health_with_bundle_recovery(arguments: dict[str, Any]) -> dict[str, Any]:
    health = copy.deepcopy(_BASE_HEALTH_HANDLER(arguments))
    health["research_bundle_recovery"] = {
        "status": "ENABLED",
        "requires_final_correlated_summary": True,
        "reexecutes_compiler": False,
    }
    return health


_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("compile_and_append_research_bundle")
_v61._server.TOOL_HANDLERS["get_runtime_contract"] = _contract_with_bundle_recovery
_v61._server.TOOL_HANDLERS["get_runtime_health"] = _health_with_bundle_recovery


def main() -> int:
    return _peer_pivot.main()


if __name__ == "__main__":
    raise SystemExit(main())
