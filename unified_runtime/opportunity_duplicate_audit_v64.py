"""Read-only V6.4 duplicate opportunity-create event diagnostic.

The SessionStore hash chain and mutation WAL are authorities, not this
projection diagnostic. NEVER use this result to delete, reorder, append,
rewrite or automatically reconcile a production event.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from .v63_projection import _validated_create_snapshot


def _identity_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def diagnose_opportunity_create_events(
    durable_events: list[dict[str, Any]],
    *,
    include_private_event_metadata: bool = False,
) -> dict[str, Any]:
    """Classify valid duplicate creates without mutating input or event store.

    All creates (including duplicates) pass strict proof and profile-pin
    verification before comparison. Two equal snapshots on DIFFERENT mutation
    correlations remain conflicts pending independent WAL reconciliation.
    An exact repetition on the same correlation is only a recovery candidate:
    real chain, journal and WAL proofs are still external prerequisites.
    """
    if not isinstance(durable_events, list):
        raise TypeError("durable_events must be a list")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_events: list[dict[str, Any]] = []
    counted = 0
    for index, event in enumerate(durable_events):
        if not isinstance(event, dict) or event.get("event_type") != "V63_PRODUCT_OPPORTUNITY_CREATED":
            continue
        counted += 1
        try:
            row = _validated_create_snapshot(event)
        except (KeyError, TypeError, RuntimeError, ValueError) as exc:
            invalid_events.append({
                "input_index": index,
                "error_type": type(exc).__name__,
                "proof_status": "INVALID",
                "detail_code": str(exc).split(":", 1)[0][:100],
            })
            continue
        group_key = str(row["opportunity_id"])
        grouped[group_key].append({
            "input_index": index,
            "seq": event.get("seq"),
            "correlation_id": str(event.get("correlation_id") or ""),
            "request_sha256": str(event.get("request_sha256") or "").lower(),
            "snapshot_sha256": str(event.get("result_snapshot_sha256") or "").lower(),
            "investigation_id": str(event.get("investigation_id") or ""),
            "account_id": str(row["account_id"]),
            "product_profile_id": str(row["product_profile_id"]),
            "snapshot": event["result_snapshot"],
        })

    collisions: list[dict[str, Any]] = []
    counts = {
        "exact_replay_candidates": 0,
        "distinct_correlation_conflicts": 0,
        "conflicting_create_groups": 0,
    }
    for opportunity_id, records in sorted(grouped.items()):
        if len(records) < 2:
            continue
        first = records[0]
        same_correlation = all(x["correlation_id"] == first["correlation_id"] for x in records)
        same_request = all(x["request_sha256"] == first["request_sha256"] for x in records)
        same_hash = all(x["snapshot_sha256"] == first["snapshot_sha256"] for x in records)
        same_snapshot = all(x["snapshot"] == first["snapshot"] for x in records)
        same_inv = all(x["investigation_id"] == first["investigation_id"] for x in records)
        same_owner = all(x["account_id"] == first["account_id"] for x in records)
        same_profile = all(x["product_profile_id"] == first["product_profile_id"] for x in records)
        if all((same_correlation, same_request, same_hash, same_snapshot, same_inv, same_owner, same_profile)):
            label = "EXACT_CORRELATION_REPLAY_CANDIDATE"
            counts["exact_replay_candidates"] += 1
        elif not same_correlation and all((same_request, same_hash, same_snapshot, same_inv, same_owner, same_profile)):
            label = "DIFFERENT_CORRELATION_SAME_REQUEST_CONFLICT"
            counts["distinct_correlation_conflicts"] += 1
        else:
            label = "CONFLICTING_CREATE_EVENTS"
            counts["conflicting_create_groups"] += 1
        collision = {
            "opportunity_id_sha256": _identity_fingerprint(opportunity_id),
            "create_event_count": len(records),
            "classification": label,
            "snapshot_equal": same_snapshot and same_hash,
            "request_equal": same_request,
            "correlation_equal": same_correlation,
            "investigation_equal": same_inv,
            "account_equal": same_owner,
            "profile_equal": same_profile,
            "input_indices": [x["input_index"] for x in records],
        }
        if include_private_event_metadata:
            collision["private_event_metadata"] = [
                {
                    k: x[k] for k in (
                        "seq", "correlation_id", "request_sha256",
                        "snapshot_sha256", "investigation_id", "account_id",
                        "product_profile_id"
                    )
                }
                for x in records
            ]
        collisions.append(collision)

    if invalid_events:
        status = "INVALID_EVENT_PROOF"
    elif any(x["classification"] != "EXACT_CORRELATION_REPLAY_CANDIDATE" for x in collisions):
        status = "CONFLICT"
    elif collisions:
        status = "REPLAY_CANDIDATES_NEED_INDEPENDENT_WAL_PROOF"
    else:
        status = "NO_DUPLICATE_CREATE_EVENTS"

    return {
        "schema": "cbi.v64-opportunity-duplicate-readonly-diagnostic.v1",
        "status": status,
        "create_event_count": counted,
        "distinct_opportunity_id_count": len(grouped),
        "duplicate_opportunity_groups": len(collisions),
        "counts": counts,
        "invalid_event_count": len(invalid_events),
        "invalid_events": invalid_events,
        "collisions": collisions,
        "input_event_chain_verified": False,
        "mutation_wal_correlated_independently": False,
        "safe_to_autorepair": False,
        "production_write_performed": False,
        "event_history_rewritten": False,
        "recovery_acceptance_achieved": False,
    }
