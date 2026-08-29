#!/usr/bin/env python3
"""Production v6.1 MCP entrypoint with mechanically proven crash recovery.

The stable :mod:`mcp.server_v61` adapter owns the general write-ahead WAL.
This thin entry layer adds mutation-family proofs that are deliberately kept
separate from the already-regression-stable core.

A PREPARED mutation is reconciled only when durable state can identify the
original side effect unambiguously. Missing or ambiguous proof remains
fail-closed; this module never turns uncertainty into a replay.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61 as _v61  # noqa: E402


_BASE_PREPARE_RESOURCE_SNAPSHOT = _v61._prepare_resource_snapshot
_BASE_RECONCILE_PREPARED = _v61._reconcile_prepared
_START_PROOF = "START_IDEMPOTENCY_KEY_AND_SESSION_HEADER"
_INFORMATION_PROOF = "INFORMATION_ID_CONTENT_HASH_AND_EVENT_SEQ"


def _matching_start_sessions(idempotency_key: str) -> list[dict[str, Any]]:
    key = str(idempotency_key or "").strip()
    if not key:
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(_v61._server.RUNTIME.store.root.glob("INV-*.jsonl")):
        try:
            events = _v61._server.RUNTIME.store.read(path.stem)
        except Exception:
            continue
        if not events:
            continue
        payload = events[0].get("payload")
        if not isinstance(payload, dict):
            continue
        if str(payload.get("start_idempotency_key") or "") != key:
            continue
        rows.append({
            "investigation_id": str(payload.get("investigation_id") or path.stem),
            "account_id": str((payload.get("account") or {}).get("account_id") or ""),
            "mode": str(payload.get("mode") or ""),
            "event_count": len(events),
        })
    return rows


def _prepare_resource_snapshot(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "start_investigation":
        key = str(args.get("idempotency_key") or "").strip()
        before = _matching_start_sessions(key)
        return {
            "kind": "START_INVESTIGATION",
            "start_idempotency_key": key,
            "matching_investigation_ids_before": [
                row["investigation_id"] for row in before
            ],
        }
    return _BASE_PREPARE_RESOURCE_SNAPSHOT(tool_name, args)


def _reconcile_start_investigation(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    snapshot = stored.get("resource_snapshot_before")
    if not isinstance(snapshot, dict) or snapshot.get("kind") != "START_INVESTIGATION":
        return None

    key = str(stored.get("idempotency_key") or "").strip()
    if not key or str(args.get("idempotency_key") or "").strip() != key:
        return None
    if str(snapshot.get("start_idempotency_key") or "") != key:
        return None

    before_ids_raw = snapshot.get("matching_investigation_ids_before")
    if not isinstance(before_ids_raw, list):
        return None
    before_ids = {str(value) for value in before_ids_raw if str(value)}
    if len(before_ids) > 1:
        return None

    durable_matches = _matching_start_sessions(key)
    if len(durable_matches) != 1:
        return None
    investigation_id = durable_matches[0]["investigation_id"]

    reconstructed = _v61._ORIGINAL_HANDLERS["start_investigation"](copy.deepcopy(args))
    if str(reconstructed.get("investigation_id") or "") != investigation_id:
        return None
    post_matches = _matching_start_sessions(key)
    if len(post_matches) != 1 or post_matches[0]["investigation_id"] != investigation_id:
        return None

    raw_result = copy.deepcopy(reconstructed)
    if "resumed_existing" in raw_result:
        raw_result["resumed_existing"] = investigation_id in before_ids

    result = {
        **raw_result,
        "mutation_meta": _v61._reconciled_meta(
            "start_investigation",
            stored,
            request_hash,
            0,
            _START_PROOF,
        ),
    }
    _v61._commit_receipt(path, stored, result, 0)
    return result


def _information_events(
    investigation_id: str,
    information_id: str,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    try:
        events = _v61._server.RUNTIME.store.read(investigation_id)
    except Exception:
        return [], []
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in events:
        if event.get("event_type") != "INFORMATION_RECORD_APPENDED":
            continue
        payload = event.get("payload")
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            continue
        if str(record.get("information_id") or "") == information_id:
            matches.append((event, record))
    return events, matches


def _reconcile_information_record(
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    investigation_id = str(args.get("investigation_id") or "").strip()
    raw = args.get("record")
    if not investigation_id or not isinstance(raw, dict):
        return None
    information_id = str(raw.get("information_id") or "").strip()
    content_sha256 = str(raw.get("content_sha256") or "").strip().lower()
    if not information_id or not content_sha256:
        return None

    events, matches = _information_events(investigation_id, information_id)
    if len(matches) != 1:
        return None
    event, record = matches[0]
    event_seq = int(event.get("seq") or 0)
    before = int(stored.get("state_version_before") or 0)
    if event_seq <= before:
        return None
    if str(record.get("content_sha256") or "").lower() != content_sha256:
        return None

    # Bind the event to the caller's durable request using fields that the
    # runtime persists without derivation. The WAL request hash already proves
    # the retry itself is byte-semantically the same request.
    stable_fields = (
        "information_id",
        "investigation_id",
        "related_account_id",
        "subject_owner_id",
        "claim_key",
        "source_reference_type",
        "source_locator",
        "observed_at",
        "content_sha256",
    )
    for field in stable_fields:
        if field in raw and str(record.get(field) or "") != str(raw.get(field) or ""):
            return None

    information_records: dict[str, dict[str, Any]] = {}
    for row in events:
        if int(row.get("seq") or 0) > event_seq:
            break
        if row.get("event_type") != "INFORMATION_RECORD_APPENDED":
            continue
        payload = row.get("payload")
        item = payload.get("record") if isinstance(payload, dict) else None
        if isinstance(item, dict) and item.get("information_id"):
            information_records[str(item["information_id"])] = item

    historical_count = sum(
        item.get("temporal_status") == "HISTORICAL"
        or item.get("information_type") == "HISTORICAL"
        for item in information_records.values()
    )
    raw_result = {
        "accepted": True,
        "information_id": information_id,
        "append_only": True,
        "historical_records_preserved": historical_count,
        "total_information_records": len(information_records),
        "effective_outreach_eligible": bool(
            record.get("outreach_eligible_effective")
        ),
        "usage_warnings": list(record.get("usage_warnings") or []),
        "policy": "PRESERVE_HISTORY_APPEND_NEW_INFORMATION_CLASSIFY_USE_SEPARATELY",
    }
    result = {
        **raw_result,
        "mutation_meta": _v61._reconciled_meta(
            "append_information_record",
            stored,
            request_hash,
            event_seq,
            _INFORMATION_PROOF,
        ),
    }
    _v61._commit_receipt(path, stored, result, event_seq)
    return result


def _reconcile_prepared(
    tool_name: str,
    args: dict[str, Any],
    stored: dict[str, Any],
    request_hash: str,
    path: Path,
) -> dict[str, Any] | None:
    if tool_name == "start_investigation":
        return _reconcile_start_investigation(
            args,
            stored,
            request_hash,
            path,
        )
    if tool_name == "append_information_record":
        return _reconcile_information_record(
            args,
            stored,
            request_hash,
            path,
        )
    return _BASE_RECONCILE_PREPARED(
        tool_name,
        args,
        stored,
        request_hash,
        path,
    )


_v61._prepare_resource_snapshot = _prepare_resource_snapshot
_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.update({
    "start_investigation",
    "append_information_record",
})


def main() -> int:
    return _v61.main()


if __name__ == "__main__":
    raise SystemExit(main())
