#!/usr/bin/env python3
"""Strict correlated fallback for Sync child information-record recovery.

The full batch implementation remains byte-identical in
``server_v61_sync_recovery_base``.  This wrapper adds exactly one missing proof
path discovered by cold CI: a pending-sync child can crash after
``append_information_record`` has durably appended its event but before the
pending sidecar/child-WAL terminal receipt is written.

Recovery first delegates to the existing mutation-family chain.  Only when that
chain cannot recover does this wrapper accept one exact
INFORMATION_RECORD_APPENDED event whose sequence is after the child PREPARED
state version and whose mutation correlation, tool, information identity,
content hash and stable request fields all match.  Missing or ambiguous proof
remains fail-closed; no side effect is re-executed.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_sync_recovery_base as _base  # noqa: E402


_v61 = _base._v61
_RUNTIME = _base._RUNTIME
_BASE_RECOVER_TARGET_RESULT = _base._recover_target_result
_INFORMATION_CHILD_PROOF = "CORRELATED_INFORMATION_EVENT_AFTER_CHILD_PREPARED"
_STABLE_INFORMATION_FIELDS = (
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


def _correlated_information_result(
    arguments: dict[str, Any],
    stored: dict[str, Any],
    path: Path,
    correlation: dict[str, str],
) -> dict[str, Any] | None:
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    raw = arguments.get("record")
    correlation_id = str(correlation.get("correlation_id") or "").strip()
    if not investigation_id or not isinstance(raw, dict) or not correlation_id:
        return None
    information_id = str(raw.get("information_id") or "").strip()
    content_sha256 = str(raw.get("content_sha256") or "").strip().lower()
    if not information_id or not content_sha256:
        return None

    try:
        before = int(stored.get("state_version_before") or 0)
        events = _RUNTIME.store.read(investigation_id)
    except Exception:
        return None

    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in events:
        event_seq = int(event.get("seq") or 0)
        if event_seq <= before or event.get("event_type") != "INFORMATION_RECORD_APPENDED":
            continue
        event_correlation = event.get("mutation_correlation")
        payload = event.get("payload")
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(event_correlation, dict) or not isinstance(record, dict):
            continue
        if (
            str(event_correlation.get("correlation_id") or "") != correlation_id
            or str(event_correlation.get("tool") or "") != "append_information_record"
            or str(record.get("information_id") or "") != information_id
            or str(record.get("content_sha256") or "").lower() != content_sha256
        ):
            continue
        if any(
            field in raw and str(record.get(field) or "") != str(raw.get(field) or "")
            for field in _STABLE_INFORMATION_FIELDS
        ):
            continue
        matches.append((event, record))

    if len(matches) != 1:
        return None

    event, record = matches[0]
    event_seq = int(event["seq"])
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
        "effective_outreach_eligible": bool(record.get("outreach_eligible_effective")),
        "usage_warnings": list(record.get("usage_warnings") or []),
        "policy": "PRESERVE_HISTORY_APPEND_NEW_INFORMATION_CLASSIFY_USE_SEPARATELY",
    }
    request_hash = str(stored.get("request_sha256") or "")
    committed = {
        **copy.deepcopy(raw_result),
        "mutation_meta": _v61._reconciled_meta(
            "append_information_record",
            stored,
            request_hash,
            event_seq,
            _INFORMATION_CHILD_PROOF,
        ),
    }
    _v61._commit_receipt(path, stored, committed, event_seq)
    return raw_result


def _recover_target_result(
    item_tool: str,
    arguments: dict[str, Any],
    stored: dict[str, Any],
    path: Path,
    correlation: dict[str, str],
) -> dict[str, Any] | None:
    recovered = _BASE_RECOVER_TARGET_RESULT(
        item_tool,
        arguments,
        stored,
        path,
        correlation,
    )
    if recovered is not None:
        return recovered
    if item_tool == "append_information_record":
        return _correlated_information_result(arguments, stored, path, correlation)
    return None


# The base module's batch functions resolve this global at call time.  Replace
# only the proof resolver; selection, child WAL, sidecar persistence, locking,
# fail-closed behavior and public handlers remain unchanged.
_base._recover_target_result = _recover_target_result


def main() -> int:
    return _base.main()


if __name__ == "__main__":
    raise SystemExit(main())
