"""Isolated post-COMMITTED immutable WAL shadow: never read an active WAL to verify.

Requires a trusted Host producer to capture a terminal WAL only AFTER the
writer has released mutation locks. Snapshots are create-once; the Host
must store the expected SHA256 in an independently protected authority.
This module is NOT wired into Render or a live mutation writer.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

from .wal_safe_reader_v64 import read_consistent_wal_bytes

_MAX_BYTES = 2_000_000

def _validate_filename(name: str) -> None:
    if (
        not isinstance(name, str)
        or not name.startswith("append_execution_receipt-")
        or not name.endswith(".json")
        or len(name) != len("append_execution_receipt-") + 64 + len(".json")
        or any(c not in "0123456789abcdef" for c in name[len("append_execution_receipt-"):-5])
    ):
        raise ValueError("Unexpected WAL snapshot identity")

def create_immutable_terminal_wal_snapshot(
    *,
    terminal_wal_path: Path,
    snapshot_root: Path,
    expected_request_sha256: str,
) -> str:
    """Host-only create-once operation AFTER COMMITTED; returns raw SHA256 pin.

    The Host is responsible for authenticating the transaction and
    atomically protecting the returned digest outside this directory.
    Failure must leave the Source Family assessment unproven.
    """
    terminal_wal_path = Path(terminal_wal_path)
    snapshot_root = Path(snapshot_root)
    _validate_filename(terminal_wal_path.name)
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise OSError("Snapshot root not independently controlled")
    payload = read_consistent_wal_bytes(terminal_wal_path, max_bytes=_MAX_BYTES)
    row = json.loads(payload.decode("utf-8"))
    if (
        not isinstance(row, dict)
        or row.get("schema") != "cbi.mutation-wal.v6.1"
        or row.get("status") != "COMMITTED"
        or row.get("tool") != "append_execution_receipt"
        or row.get("request_sha256") != expected_request_sha256
        or not isinstance(row.get("result"), dict)
    ):
        raise ValueError("WAL was not a matched terminal COMMITTED receipt")
    digest_hex = hashlib.sha256(payload).hexdigest()
    path = snapshot_root / terminal_wal_path.name
    # O_EXCL: snapshot file is never replaced, even for retries.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd,"wb",closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # Retain partial file for inspection; do NOT delete or overwrite a
        # potentially disputed prior evidence artifact.
        raise
    return digest_hex

def read_immutable_wal_snapshot(
    *,
    snapshot_root: Path,
    filename: str,
    externally_pinned_sha256: str,
) -> bytes:
    """Read only a Host-created immutable copy, not the mutable live WAL."""
    _validate_filename(filename)
    if (
        not isinstance(externally_pinned_sha256,str)
        or len(externally_pinned_sha256)!=64
        or any(c not in "0123456789abcdef" for c in externally_pinned_sha256)
    ):
        raise ValueError("Snapshot pin must come from trusted protected Host")
    root=Path(snapshot_root)
    if root.is_symlink() or not root.is_dir():
        raise OSError("Untrusted snapshot root")
    path=root/filename
    if path.is_symlink() or not path.is_file():
        raise OSError("Missing or replaced snapshot")
    before=path.stat()
    if not 0 < before.st_size <= _MAX_BYTES:
        raise OSError("Invalid snapshot size")
    data=path.read_bytes()
    after=path.stat()
    if (len(data)!=before.st_size or before.st_ino!=after.st_ino
        or before.st_mtime_ns!=after.st_mtime_ns or before.st_size!=after.st_size):
        raise OSError("Immutable snapshot changed during read")
    if hashlib.sha256(data).hexdigest()!=externally_pinned_sha256:
        raise ValueError("Immutable snapshot does not match Host-side pin")
    return data
