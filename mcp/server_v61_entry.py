#!/usr/bin/env python3
"""Production v6.1 MCP entrypoint with mechanically proven start recovery.

The stable :mod:`mcp.server_v61` adapter owns the general write-ahead WAL.
This thin entry layer adds one mutation-family proof that is deliberately kept
separate from the already-regression-stable core: ``start_investigation``.

A PREPARED start is reconciled only when the durable session headers prove that
exactly one investigation carries the same native ``start_idempotency_key``.
The underlying runtime is then invoked only to reconstruct its response; its own
start-key lookup must return that exact investigation. Ambiguous or missing
proof remains fail-closed.
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
    # More than one pre-existing session with one start key is itself a durable
    # integrity violation; never choose one by recency or filename order.
    if len(before_ids) > 1:
        return None

    durable_matches = _matching_start_sessions(key)
    if len(durable_matches) != 1:
        return None
    investigation_id = durable_matches[0]["investigation_id"]

    # The original runtime has native durable start-key idempotency. Calling it
    # here is response reconstruction, not blind replay: it must resolve the
    # already-proven session and must not allocate another investigation.
    reconstructed = _v61._ORIGINAL_HANDLERS["start_investigation"](copy.deepcopy(args))
    if str(reconstructed.get("investigation_id") or "") != investigation_id:
        return None
    post_matches = _matching_start_sessions(key)
    if len(post_matches) != 1 or post_matches[0]["investigation_id"] != investigation_id:
        return None

    raw_result = copy.deepcopy(reconstructed)
    # Reconstruct the original call's resume bit from the PREPARED snapshot:
    # if this investigation existed before PREPARED, the crashed call resumed;
    # otherwise it created the durable session that is now being proven.
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
    return _BASE_RECONCILE_PREPARED(
        tool_name,
        args,
        stored,
        request_hash,
        path,
    )


# Patch the core adapter by reference. Its tool wrappers resolve these globals
# dynamically, so no duplicate mutation machinery is introduced here.
_v61._prepare_resource_snapshot = _prepare_resource_snapshot
_v61._reconcile_prepared = _reconcile_prepared
_v61._AUTOMATIC_RECONCILIATION_TOOLS.add("start_investigation")


def main() -> int:
    return _v61.main()


if __name__ == "__main__":
    raise SystemExit(main())
