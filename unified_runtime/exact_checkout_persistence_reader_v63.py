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
