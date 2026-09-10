from __future__ import annotations

from typing import Any


_BASE = {
    "requires_exact_event_correlation": True,
    "requires_exact_result_snapshot": True,
    "prepared_auto_reexecutes_without_proof": False,
    "unproven_prepared_result": "MUTATION_RECONCILIATION_REQUIRED",
    "correlation_contains_raw_idempotency_key": False,
    "reexecutes_side_effect_during_recovery": False,
}

V63_WAL_BINDINGS: dict[str, dict[str, Any]] = {
    "append_candidate_discovery": {
        **_BASE,
        "requires_exact_result_snapshot": False,
        "event_type": "V63_CANDIDATE_DISCOVERED",
        "proof": "CORRELATED_V63_CANDIDATE_DISCOVERY_EVENT",
        "required_event_fields": [
            "candidate_id",
            "discovered_from_anchor_id",
            "branch_group",
            "branch",
            "company_name",
            "product_profile_id",
            "stage",
            "inherited_anchor_facts",
        ],
        "required_exact_values": {
            "stage": "DISCOVERED",
            "inherited_anchor_facts": False,
        },
    },
    "create_product_opportunity": {
        **_BASE,
        "event_type": "V63_PRODUCT_OPPORTUNITY_CREATED",
        "proof": "CORRELATED_V63_PRODUCT_OPPORTUNITY_CREATE_WITH_EXACT_RESULT_SNAPSHOT",
    },
    "promote_opportunity_anchor": {
        **_BASE,
        "requires_exact_result_snapshot": False,
        "event_type": "V63_OPPORTUNITY_ANCHOR_PROMOTED",
        "proof": "CORRELATED_V63_ANCHOR_PROMOTION_EVENT",
        "required_event_fields": [
            "opportunity_id",
            "anchor_id",
            "promotion_reason",
            "stage",
            "anchor_eligibility_snapshot",
            "cycle_dedup_snapshot",
        ],
        "required_exact_values": {
            "stage": "PROMOTED_ANCHOR",
            "anchor_eligibility_snapshot.anchor_eligible": True,
            "cycle_dedup_snapshot.cycle_dedup_complete": True,
        },
    },
}



def build_v63_wal_contract() -> dict[str, Any]:
    return {
        "schema": "cbi.mutation-wal-extension.v6.3",
        "binding_strategy": "EXTEND_EXISTING_PRODUCTION_WAL",
        "existing_wal_is_authority": True,
        "parallel_wal_allowed": False,
        "r2_durable_state_preserved": True,
        "prepared_state": "PREPARED",
        "terminal_states": ["COMMITTED", "COMMITTED_ERROR"],
        "prepared_auto_replay_without_proof": False,
        "bindings": {name: dict(binding) for name, binding in V63_WAL_BINDINGS.items()},
    }


def _sha256_like(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def _path_value(payload: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def validate_v63_durable_event_proof(binding: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if str(event.get("event_type") or "") != str(binding.get("event_type") or ""):
        blockers.append("EVENT_TYPE_MISMATCH")
    if not str(event.get("correlation_id") or "").strip():
        blockers.append("MISSING_CORRELATION_ID")
    if not _sha256_like(event.get("request_sha256")):
        blockers.append("INVALID_REQUEST_SHA256")
    if binding.get("requires_exact_result_snapshot"):
        if "result_snapshot" not in event:
            blockers.append("MISSING_RESULT_SNAPSHOT")
        if not _sha256_like(event.get("result_snapshot_sha256")):
            blockers.append("INVALID_RESULT_SNAPSHOT_SHA256")
    if bool(event.get("raw_idempotency_key_persisted")):
        blockers.append("RAW_IDEMPOTENCY_KEY_PERSISTED")

    for field in binding.get("required_event_fields", []):
        present, value = _path_value(event, str(field))
        if not present or value is None or value == "":
            blockers.append(f"MISSING_EVENT_FIELD:{field}")

    for path, expected in dict(binding.get("required_exact_values") or {}).items():
        present, value = _path_value(event, str(path))
        if not present or value != expected:
            blockers.append(f"EVENT_CONSTRAINT_FAILED:{path}")

    valid = not blockers
    if not valid:
        recovery_action = "MUTATION_RECONCILIATION_REQUIRED"
    elif binding.get("requires_exact_result_snapshot"):
        recovery_action = "RETURN_EXACT_STORED_RESULT"
    else:
        recovery_action = "RECONSTRUCT_FROM_CORRELATED_EVENT"
    return {
        "valid": valid,
        "blockers": blockers,
        "recovery_action": recovery_action,
        "reexecute_side_effect": False,
    }
