"""ISOLATED three-phase, create-only post-commit WAL archive.

PHASE 1: stage WAL bytes + fsync, with no final path.
PHASE 2: hard-link create-only to final path, never replace an earlier version.
PHASE 3: register and independently re-read a Host-controlled pin.

Crash or failure before phase 3 MUST NOT be treated as successful archival.
This module is not a live production writer or authority implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from .core import digest
from .wal_immutable_snapshot_v64 import _validate_filename, read_immutable_wal_snapshot
from .wal_safe_reader_v64 import read_consistent_wal_bytes

_MAX_BYTES = 2_000_000
_PhaseHook = Callable[[str], None]
_PinWriter = Callable[[str, str], bool]
_PinReader = Callable[[str], str | None]


def archive_postcommit_three_phase(
    *,
    terminal_wal_path: Path,
    snapshot_root: Path,
    expected_request_sha256: str,
    trusted_pin_writer: _PinWriter,
    trusted_pin_reader: _PinReader,
    phase_hook: _PhaseHook | None = None,
) -> str:
    """Publish only verified COMMITTED data and require independent pin proof.

    Caller must guarantee the terminal WAL writer already finished and
    released its lock. Host authenticates idempotency/request ownership
    separately. The pin writer/reader MUST come from an independently
    protected Host authority and never untrusted MCP arguments.
    """
    terminal = Path(terminal_wal_path)
    root = Path(snapshot_root)
    _validate_filename(terminal.name)
    if root.is_symlink() or not root.is_dir():
        raise OSError("Untrusted or missing snapshot root")
    if not callable(trusted_pin_writer) or not callable(trusted_pin_reader):
        raise ValueError("Host pin authority is required")
    if (
        not isinstance(expected_request_sha256, str)
        or len(expected_request_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_request_sha256)
    ):
        raise ValueError("Host request SHA256 pin required")
    data = read_consistent_wal_bytes(terminal, max_bytes=_MAX_BYTES)
    row = json.loads(data.decode("utf-8"))
    if (
        not isinstance(row, dict)
        or row.get("schema") != "cbi.mutation-wal.v6.1"
        or row.get("status") != "COMMITTED"
        or row.get("tool") != "append_execution_receipt"
        or row.get("request_sha256") != expected_request_sha256
        or not isinstance(row.get("result"), dict)
        or row.get("result_sha256") != digest(row["result"])
    ):
        raise ValueError("Incomplete, inconsistent or non-COMMITTED WAL")
    expected_digest = hashlib.sha256(data).hexdigest()
    final = root / terminal.name
    if final.is_symlink() or final.exists():
        raise FileExistsError("Snapshot already published; operator reconciliation required")

    # PREPARE: only a hidden staging name is visible until the full file
    # is durable. Do not clean up disputed artifacts automatically.
    fd, stage_name = tempfile.mkstemp(prefix=".pending-wal-", suffix=".staged", dir=root)
    stage = Path(stage_name)
    with os.fdopen(fd, "wb", closefd=True) as out:
        midpoint = max(1, len(data) // 2)
        out.write(data[:midpoint])
        out.flush()
        if phase_hook is not None:
            phase_hook("MID_WRITE")
        out.write(data[midpoint:])
        out.flush()
        os.fsync(out.fileno())
    if phase_hook is not None:
        phase_hook("STAGED")

    # PUBLISH: hard-link is an atomic, no-overwrite directory entry on
    # supported filesystems; final never names a partially written stage.
    # There is no fallback to unsafe os.replace(final).
    os.link(stage, final)
    stage.unlink()
    if phase_hook is not None:
        phase_hook("PUBLISHED")

    # PIN: the recording authority MUST be separate from snapshot_root.
    # Boolean ack by itself is not sufficient: check a fresh Host pin read.
    if trusted_pin_writer(terminal.name, expected_digest) is not True:
        raise OSError("Trusted Host pin registration not confirmed")
    pinned = trusted_pin_reader(terminal.name)
    if pinned != expected_digest:
        raise OSError("Independent Host pin readback mismatch")
    content = read_immutable_wal_snapshot(
        snapshot_root=root,
        filename=terminal.name,
        externally_pinned_sha256=pinned,
    )
    if content != data:
        raise OSError("Published snapshot differs from prepared bytes")
    if phase_hook is not None:
        phase_hook("PIN_PERSISTED")
    return expected_digest


def verify_three_phase_snapshot(
    *, snapshot_root: Path, filename: str, trusted_pin_reader: _PinReader
) -> bytes:
    """Never infer proof from existence, local bytes or claimant-supplied hash."""
    _validate_filename(filename)
    if not callable(trusted_pin_reader):
        raise OSError("Trusted pin lookup unavailable")
    pinned = trusted_pin_reader(filename)
    if not pinned:
        raise OSError("Snapshot not independently registered")
    return read_immutable_wal_snapshot(
        snapshot_root=snapshot_root, filename=filename,
        externally_pinned_sha256=pinned,
    )
