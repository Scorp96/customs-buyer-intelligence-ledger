from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Iterable

from .wal_contract_v63 import V63_WAL_BINDINGS, validate_v63_durable_event_proof


_CONTROL_FIELDS = {"idempotency_key", "expected_state_version"}


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def snapshot_sha256(snapshot: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(snapshot)).hexdigest()


def canonical_v63_request_material(arguments: dict[str, Any]) -> dict[str, Any]:
    material = copy.deepcopy(dict(arguments or {}))
    for field in _CONTROL_FIELDS:
        material.pop(field, None)
    return material


def canonical_v63_request_sha256(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(canonical_v63_request_material(arguments))).hexdigest()


def canonical_v63_wal_request_sha256(tool_name: str, arguments: dict[str, Any]) -> str:
    tool = str(tool_name or "").strip()
    if not tool:
        raise ValueError("tool_name is required")
    material = canonical_v63_request_material(arguments)
    return hashlib.sha256(_canonical_json_bytes({"tool": tool, "arguments": material})).hexdigest()


def _fail(*blockers: str, expected_request_sha256: str | None = None) -> dict[str, Any]:
    return {
        "status": "MUTATION_RECONCILIATION_REQUIRED",
        "blockers": list(dict.fromkeys(str(v) for v in blockers if v)),
        "expected_request_sha256": expected_request_sha256,
        "recovery_action": "MUTATION_RECONCILIATION_REQUIRED",
        "reexecute_side_effect": False,
        "result": None,
    }


def _candidate_result(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "DISCOVERED",
        "candidate_id": event["candidate_id"],
        "discovered_from_anchor_id": event["discovered_from_anchor_id"],
        "branch_group": event["branch_group"],
        "branch": event["branch"],
        "company_name": event["company_name"],
        "product_profile_id": event["product_profile_id"],
        "stage": event["stage"],
        "inherited_anchor_facts": event["inherited_anchor_facts"],
    }


def _anchor_result(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PROMOTED",
        "opportunity_id": event["opportunity_id"],
        "anchor_id": event["anchor_id"],
        "promotion_reason": event["promotion_reason"],
        "stage": event["stage"],
        "anchor_eligibility_snapshot": copy.deepcopy(event["anchor_eligibility_snapshot"]),
        "cycle_dedup_snapshot": copy.deepcopy(event["cycle_dedup_snapshot"]),
    }


def recover_prepared_v63_mutation(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    expected_correlation_id: str,
    durable_events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    binding = V63_WAL_BINDINGS.get(str(tool_name))
    if binding is None:
        return _fail("UNKNOWN_V63_DURABLE_MUTATION")

    correlation = str(expected_correlation_id or "").strip()
    if not correlation:
        return _fail("MISSING_EXPECTED_CORRELATION_ID")

    expected_hash = canonical_v63_wal_request_sha256(tool_name, arguments)
    exact: list[dict[str, Any]] = []
    for raw in durable_events:
        event = dict(raw or {})
        if str(event.get("event_type") or "") != str(binding.get("event_type") or ""):
            continue
        if str(event.get("correlation_id") or "") != correlation:
            continue
        if str(event.get("request_sha256") or "").lower() != expected_hash.lower():
            continue
        exact.append(event)

    if not exact:
        return _fail("NO_EXACT_DURABLE_PROOF", expected_request_sha256=expected_hash)
    if len(exact) != 1:
        return _fail("AMBIGUOUS_EXACT_DURABLE_PROOF", expected_request_sha256=expected_hash)

    event = exact[0]
    proof = validate_v63_durable_event_proof(binding, event)
    if not proof["valid"]:
        return _fail(*proof["blockers"], expected_request_sha256=expected_hash)

    action = str(proof["recovery_action"])
    if binding.get("requires_exact_result_snapshot"):
        snapshot = copy.deepcopy(event.get("result_snapshot"))
        expected_snapshot_hash = str(event.get("result_snapshot_sha256") or "").lower()
        actual_snapshot_hash = snapshot_sha256(snapshot).lower()
        if actual_snapshot_hash != expected_snapshot_hash:
            return _fail("RESULT_SNAPSHOT_HASH_MISMATCH", expected_request_sha256=expected_hash)
        result = snapshot
    elif tool_name == "append_candidate_discovery":
        result = _candidate_result(event)
    elif tool_name == "promote_opportunity_anchor":
        result = _anchor_result(event)
    else:
        return _fail("UNSUPPORTED_EVENT_RECONSTRUCTION", expected_request_sha256=expected_hash)

    return {
        "status": "RECOVERED",
        "blockers": [],
        "expected_request_sha256": expected_hash,
        "correlation_id": correlation,
        "proof": str(binding.get("proof") or ""),
        "event_seq": int(event.get("seq") or event.get("_event_seq") or 0),
        "recovery_action": action,
        "reexecute_side_effect": False,
        "result": result,
    }
