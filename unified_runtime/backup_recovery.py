from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from .resilience import canonical_json, digest


SNAPSHOT_SCHEMA = "cbi.backup-snapshot.v6.1"
RESTORE_SCHEMA = "cbi.backup-restore.v6.1"


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(
        path.suffix + f".{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    payload = (canonical_json(value) + "\n").encode("utf-8")
    descriptor = os.open(
        str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_chain(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        canonical_json(event) + "\n" for event in events
    ).encode("utf-8")
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_valid_chain_prefix(path: Path) -> tuple[list[dict[str, Any]], str]:
    if not path.is_file():
        return [], ""
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return events, f"corrupt JSONL at line {line_number}"
        claimed = event.get("event_hash")
        unsigned = {
            key: value for key, value in event.items() if key != "event_hash"
        }
        if event.get("seq") != line_number or event.get("prev_hash") != previous:
            return events, f"hash chain broken at line {line_number}"
        if claimed != digest(unsigned):
            return events, f"event hash mismatch at line {line_number}"
        previous = str(claimed)
        events.append(event)
    return events, ""


def _append_proven_tail(
    snapshot_events: list[dict[str, Any]],
    live_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if not snapshot_events:
        return live_events, "NEW_CHAIN_FROM_LIVE_VALID_PREFIX"
    if len(live_events) < len(snapshot_events):
        return snapshot_events, "LIVE_CHAIN_SHORTER_THAN_SNAPSHOT"
    snapshot_tail = snapshot_events[-1]
    live_at_snapshot_tail = live_events[len(snapshot_events) - 1]
    if (
        snapshot_tail.get("seq") != live_at_snapshot_tail.get("seq")
        or snapshot_tail.get("event_hash")
        != live_at_snapshot_tail.get("event_hash")
    ):
        return snapshot_events, "LIVE_CHAIN_DIVERGED_FROM_SNAPSHOT"
    if len(live_events) == len(snapshot_events):
        return snapshot_events, "NO_LIVE_TAIL"
    return [
        *snapshot_events,
        *live_events[len(snapshot_events) :],
    ], "REPLAYED_PROVEN_APPEND_ONLY_TAIL"


__all__ = [
    "RESTORE_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "_append_proven_tail",
    "_atomic_json",
    "_fsync_directory",
    "_read_valid_chain_prefix",
    "_sha256_file",
    "_write_chain",
]
