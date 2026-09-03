from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core import digest


_INVESTIGATION_ID_RE = re.compile(r"INV-[0-9TZ-]+-[0-9a-f]{12}")


def _without_raw_idempotency_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_raw_idempotency_keys(item)
            for key, item in value.items()
            if str(key).casefold() != "idempotency_key"
        }
    if isinstance(value, list):
        return [_without_raw_idempotency_keys(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_without_raw_idempotency_keys(item) for item in value)
    return value


class ExactCheckoutPersistenceReader:
    def __init__(self, persistence_root: Path):
        self.persistence_root = Path(persistence_root).resolve()
        self.session_root = self.persistence_root / "sessions"
        self.wal_root = self.persistence_root / "mcp-idempotency-v61"

    def read_session_events(self, investigation_id: str) -> list[dict[str, Any]]:
        if not isinstance(investigation_id, str) or not _INVESTIGATION_ID_RE.fullmatch(
            investigation_id
        ):
            raise RuntimeError("INVESTIGATION_ID_INVALID")
        path = self.session_root / f"{investigation_id}.jsonl"
        if not path.is_file():
            raise RuntimeError("SESSION_LOG_NOT_FOUND")

        events: list[dict[str, Any]] = []
        previous = "0" * 64
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("SESSION_LOG_UNREADABLE") from exc

        for line_number, line in enumerate(lines, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"SESSION_LOG_CORRUPT line={line_number}"
                ) from exc
            if not isinstance(event, dict):
                raise RuntimeError(f"SESSION_LOG_EVENT_INVALID line={line_number}")
            if event.get("seq") != line_number or event.get("prev_hash") != previous:
                raise RuntimeError(f"SESSION_CHAIN_BROKEN line={line_number}")
            claimed = event.get("event_hash")
            unsigned = {key: value for key, value in event.items() if key != "event_hash"}
            actual = digest(unsigned)
            if claimed != actual:
                raise RuntimeError(f"SESSION_EVENT_HASH_MISMATCH line={line_number}")
            previous = str(claimed)
            events.append(event)

        if not events or events[0].get("event_type") != "INVESTIGATION_STARTED":
            raise RuntimeError("SESSION_HEADER_MISSING")
        return events

    def read_wal_records(self) -> list[dict[str, Any]]:
        if not self.wal_root.exists():
            return []
        if not self.wal_root.is_dir():
            raise RuntimeError("WAL_ROOT_INVALID")

        rows: list[dict[str, Any]] = []
        for path in sorted(self.wal_root.glob("*.json"), key=lambda item: item.name):
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8", errors="strict"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"WAL_RECORD_UNREADABLE:{path.name}") from exc
            if not isinstance(raw, dict):
                raise RuntimeError(f"WAL_RECORD_INVALID:{path.name}")
            sanitized = _without_raw_idempotency_keys(raw)
            if not isinstance(sanitized, dict):
                raise RuntimeError(f"WAL_RECORD_INVALID:{path.name}")
            rows.append(sanitized)
        return rows

    def normalize_mutation_evidence(
        self,
        investigation_id: str,
        tool_name: str,
    ) -> dict[str, Any]:
        tool = str(tool_name or "").strip()
        if not tool:
            raise RuntimeError("TOOL_NAME_INVALID")

        event_rows: list[dict[str, Any]] = []
        for event in self.read_session_events(investigation_id):
            correlation = event.get("mutation_correlation")
            if not isinstance(correlation, dict) or correlation.get("tool") != tool:
                continue
            payload = event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            event_rows.append(
                {
                    "seq": event.get("seq"),
                    "event_type": event.get("event_type"),
                    "correlation_id": correlation.get("correlation_id"),
                    "request_sha256": payload.get("request_sha256"),
                    "result_snapshot": _without_raw_idempotency_keys(
                        payload.get("result_snapshot")
                    ),
                    "result_snapshot_sha256": payload.get(
                        "result_snapshot_sha256"
                    ),
                }
            )

        wal_rows: list[dict[str, Any]] = []
        for row in self.read_wal_records():
            if row.get("tool") != tool:
                continue
            result = row.get("result")
            wal_rows.append(
                {
                    "status": row.get("status"),
                    "correlation_id": row.get("mutation_correlation_id"),
                    "request_sha256": row.get("request_sha256"),
                    "state_version_before": row.get("state_version_before"),
                    "state_version_after": row.get("state_version_after"),
                    "result": _without_raw_idempotency_keys(result),
                    "result_sha256": row.get("result_sha256"),
                }
            )

        return {
            "tool": tool,
            "event_count": len(event_rows),
            "wal_record_count": len(wal_rows),
            "events": event_rows,
            "wal_records": wal_rows,
            "raw_idempotency_key_exposed": False,
        }
