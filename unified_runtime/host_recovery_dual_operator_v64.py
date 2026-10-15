"""Isolated dual-operator authorization for partial Host WAL archive recovery.

NOT a production permission system. Two externally authenticated decisions,
pre-pinned request/task/session/snapshot identity and a durable CAS redemption
provider are required. No local filesystem token counter and no MCP caller
metadata can grant recovery. This wrapper is an optional *additional* gate
around resume_authorized_partial_archive; production is not wired.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable

from .core import digest

_RECOVERY_PURPOSE = "CBI_PARTIAL_HOST_WAL_ARCHIVE_RECOVERY_V1"
_SCOPED_FIELDS = (
    "expected_snapshot_sha256",
    "expected_pin_sha256",
    "expected_request_sha256",
    "expected_event_hash",
    "expected_task_digest",
    "expected_account_id",
    "expected_investigation_id",
    "expected_session_tail_hash",
    "expected_last_seq",
)

def _timestamp(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else None

def make_dual_operator_recovery_authorization(
    *,
    trusted_pinned_recovery: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None,
    trusted_operator_one: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None,
    trusted_operator_two: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None,
    verify_authenticated_decision: Callable[[dict[str, Any], str], bool] | None,
    redeem_durable_scoped_lease: Callable[[str, str, int], dict[str, Any] | None] | None,
    trusted_utc_now: Callable[[], datetime] | None,
    max_recovery_attempts: int = 3,
) -> Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None]:
    """Return an authorizer for the existing isolated recovery API.

    The pin provider, both operator records, signature/identity verifier, and
    atomic replay lease provider MUST be separately protected Host services.
    The durable provider must atomically increment a counter for the exact
    digest+recovery intent and must not roll counters back on process crash.
    """
    def authorization(event: dict[str, Any], args: dict[str, Any],
                      task: dict[str, Any]) -> dict[str, Any] | None:
        if (
            not all(callable(x) for x in (
                trusted_pinned_recovery, trusted_operator_one,
                trusted_operator_two, verify_authenticated_decision,
                redeem_durable_scoped_lease, trusted_utc_now))
            or type(max_recovery_attempts) is not int
            or not 1 <= max_recovery_attempts <= 3
            or not isinstance(event, dict)
            or not isinstance(args, dict)
            or not isinstance(task, dict)
        ):
            return None
        try:
            now = trusted_utc_now()
            if not isinstance(now, datetime) or now.tzinfo is None:
                return None
            now = now.astimezone(timezone.utc)
            pin = trusted_pinned_recovery(event, args, task)
            if not isinstance(pin, dict) or pin.get("approved") is not True:
                return None
            scope = {"purpose": _RECOVERY_PURPOSE}
            for field in _SCOPED_FIELDS:
                value = pin.get(field)
                if value is None or isinstance(value, bool):
                    return None
                scope[field] = value
            if (
                any(type(scope[k]) is not str or len(scope[k]) != 64
                    or any(ch not in "0123456789abcdef" for ch in scope[k])
                    for k in (
                        "expected_snapshot_sha256", "expected_pin_sha256",
                        "expected_request_sha256", "expected_event_hash",
                        "expected_task_digest", "expected_session_tail_hash"))
                or type(scope["expected_last_seq"]) is not int
                or scope["expected_last_seq"] <= 0
                or scope["expected_event_hash"] != event.get("event_hash")
                or scope["expected_task_digest"] != digest(task)
                or scope["expected_investigation_id"] != args.get("investigation_id")
                or scope["expected_account_id"] != (args.get("attempt") or {}).get("owner_id")
            ):
                return None
            scope_hash = digest(scope)
            entries = [
                trusted_operator_one(event, args, task),
                trusted_operator_two(event, args, task),
            ]
            roles = ("RECOVERY_OPERATOR", "INDEPENDENT_REVIEWER")
            subjects: list[str] = []
            decision_ids: list[str] = []
            credential_ids: list[str] = []
            for decision, role in zip(entries, roles):
                if not isinstance(decision, dict):
                    return None
                if (
                    decision.get("decision") != "APPROVED"
                    or decision.get("role") != role
                    or decision.get("purpose") != _RECOVERY_PURPOSE
                    or decision.get("scope_digest") != scope_hash
                    or not isinstance(decision.get("subject_id"), str)
                    or not decision["subject_id"]
                    or not isinstance(decision.get("decision_id"), str)
                    or not decision["decision_id"]
                    or not isinstance(decision.get("credential_id"), str)
                    or not decision["credential_id"]
                ):
                    return None
                start = _timestamp(decision.get("issued_at"))
                expiry = _timestamp(decision.get("expires_at"))
                if (
                    start is None or expiry is None
                    or not start <= now < expiry
                    or (expiry - start).total_seconds() > 900
                    or (expiry - start).total_seconds() <= 0
                    or verify_authenticated_decision(copy.deepcopy(decision), role) is not True
                ):
                    return None
                subjects.append(decision["subject_id"])
                decision_ids.append(decision["decision_id"])
                credential_ids.append(decision["credential_id"])
            if (
                len(set(subjects)) != 2
                or len(set(decision_ids)) != 2
                or len(set(credential_ids)) != 2
            ):
                return None
            lease_digest = digest({
                "scope": scope_hash,
                "operator_decisions": sorted(decision_ids),
                "credentials": sorted(credential_ids),
            })
            # Atomic Host CAS: the independent, protected authority assigns a
            # monotonic redemption count; claimant cannot supply this field.
            result = redeem_durable_scoped_lease(
                lease_digest, scope_hash, max_recovery_attempts
            )
            if not isinstance(result, dict):
                return None
            if (
                result.get("allowed") is not True
                or result.get("lease_digest") != lease_digest
                or result.get("scope_digest") != scope_hash
                or type(result.get("redemption_count")) is not int
                or not 1 <= result["redemption_count"] <= max_recovery_attempts
            ):
                return None
            return copy.deepcopy(pin)
        except Exception:
            return None
    return authorization
