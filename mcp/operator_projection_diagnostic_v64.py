"""Opt-in sanitized read-only diagnostic of one authoritative CBI session.

No raw session export and no automatic portfolio repair. This function is
independent of the disabled private EXACT_SESSION_CAPTURE facility and returns
only aggregate anomaly categories; it does not make private evidence public.
"""
from __future__ import annotations

import os
import re
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Any

from unified_runtime.opportunity_duplicate_audit_v64 import diagnose_opportunity_create_events

_SESSION_ID = re.compile(r"^INV-[A-Za-z0-9._:-]{1,150}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_LIMIT_EVENTS = 50000


def inspect_authoritative_projection(
    runtime: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed unless explicitly enabled server-side for an operator window.

    Do not pass URLs, session file paths, arbitrary stores, or raw event objects
    from the tool request. Runtime is the authenticated bound server instance.
    """
    if os.getenv("CBI_V64_OPERATOR_PROJECTION_DIAGNOSTIC_ENABLED") != "1":
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_DISABLED")
    if not isinstance(arguments, dict):
        raise ValueError("CBI_V64_PROJECTION_DIAGNOSTIC_ARGUMENTS_INVALID")
    allowed = {
        "investigation_id", "expected_last_safe_seq",
        "expected_last_safe_event_hash", "acknowledge_private_state",
    }
    if set(arguments) - allowed:
        raise ValueError("CBI_V64_PROJECTION_DIAGNOSTIC_UNKNOWN_ARGUMENTS")
    if arguments.get("acknowledge_private_state") is not True:
        raise ValueError("CBI_V64_PROJECTION_DIAGNOSTIC_ACK_REQUIRED")
    investigation_id = str(arguments.get("investigation_id") or "")
    if not _SESSION_ID.fullmatch(investigation_id):
        raise ValueError("CBI_V64_PROJECTION_DIAGNOSTIC_SESSION_INVALID")
    # This is an operator-only server capability. The ordinary MCP bearer
    # session and the request's acknowledgement are not authorization to
    # enumerate private production investigations. A server-side per-session
    # allowlist and expiry are required, even when ENABLED=1.
    expected_identity = os.getenv("CBI_V64_OPERATOR_DIAG_SESSION_SHA256", "").lower()
    expiry = os.getenv("CBI_V64_OPERATOR_DIAG_EXPIRES_AT", "")
    if not _SHA256.fullmatch(expected_identity):
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_ALLOWLIST_MISSING")
    actual_identity = hashlib.sha256(investigation_id.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_identity, expected_identity):
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_SESSION_NOT_ALLOWED")
    try:
        expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_EXPIRY_INVALID") from exc
    if expires_at.tzinfo is None:
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_EXPIRY_INVALID")
    now = datetime.now(timezone.utc)
    remaining = expires_at.astimezone(timezone.utc) - now
    if not (timedelta(0) < remaining <= timedelta(minutes=15)):
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_WINDOW_CLOSED")

    wanted_seq = arguments.get("expected_last_safe_seq")
    if type(wanted_seq) is not int or wanted_seq < 1:
        raise ValueError("CBI_V64_PROJECTION_DIAGNOSTIC_SEQ_REQUIRED")
    wanted_hash = str(arguments.get("expected_last_safe_event_hash") or "").lower()
    if not _SHA256.fullmatch(wanted_hash):
        raise ValueError("CBI_V64_PROJECTION_DIAGNOSTIC_TAIL_HASH_REQUIRED")

    store = getattr(runtime, "store", None)
    reader = getattr(store, "read", None)
    normalizer = getattr(runtime, "_normalize_v63_opportunity_event", None)
    if not callable(reader) or not callable(normalizer):
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_RUNTIME_BINDING_MISSING")

    events = reader(investigation_id)
    if not isinstance(events, list) or not events or len(events) > _LIMIT_EVENTS:
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_CHAIN_UNAVAILABLE_OR_LIMIT")
    tail = events[-1]
    if not isinstance(tail, dict):
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_CHAIN_TAIL_INVALID")
    actual_seq, actual_hash = tail.get("seq"), str(tail.get("event_hash") or "").lower()
    if actual_seq != wanted_seq or actual_hash != wanted_hash:
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_EXPECTATION_MISMATCH")

    normalized = []
    for event in events:
        if not isinstance(event, dict):
            raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_EVENT_INVALID")
        row = normalizer(investigation_id, event)
        if row is not None:
            normalized.append(row)
    details = diagnose_opportunity_create_events(normalized)

    # Read the authoritative tail once more to exclude a concurrent append
    # between inspection and the returned receipt. Fail closed on a race.
    after = reader(investigation_id)
    if (
        not isinstance(after, list) or len(after) != len(events)
        or not after or not isinstance(after[-1], dict)
        or after[-1].get("seq") != wanted_seq
        or str(after[-1].get("event_hash") or "").lower() != wanted_hash
    ):
        raise RuntimeError("CBI_V64_PROJECTION_DIAGNOSTIC_CHAIN_CHANGED")

    # Do not expose account IDs, event payload, raw WAL request/correlation
    # values or deterministic identity hashes in an MCP result.
    safe_collisions = [
        {
            "create_event_count": row["create_event_count"],
            "classification": row["classification"],
            "snapshot_equal": row["snapshot_equal"],
            "request_equal": row["request_equal"],
            "correlation_equal": row["correlation_equal"],
            "investigation_equal": row["investigation_equal"],
            "account_equal": row["account_equal"],
            "profile_equal": row["profile_equal"],
        }
        for row in details["collisions"]
    ]
    return {
        "schema": "cbi.v64-operator-projection-health.v1",
        "status": details["status"],
        "read_only": True,
        "production_write_performed": False,
        "chain_read_succeeded": True,
        "chain_expectations_matched": True,
        "authoritative_wal_independently_reconciled": False,
        "safe_to_autorepair": False,
        "create_event_count": details["create_event_count"],
        "distinct_opportunity_id_count": details["distinct_opportunity_id_count"],
        "duplicate_opportunity_groups": details["duplicate_opportunity_groups"],
        "invalid_event_count": details["invalid_event_count"],
        "counts": details["counts"],
        "invalid_event_codes": sorted({x["detail_code"] for x in details["invalid_events"]}),
        "collisions": safe_collisions,
        "source_event_count": len(events),
        "source_last_safe_seq": wanted_seq,
        "raw_events_exported": False,
        "raw_identifiers_exposed": False,
        "operator_window_expiry_enforced": True,
        "exact_session_allowlist_enforced": True,
        "private_session_state_exported": False,
        "recovery_acceptance_achieved": False,
    }
