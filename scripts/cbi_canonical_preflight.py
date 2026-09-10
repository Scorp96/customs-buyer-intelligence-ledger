#!/usr/bin/env python3
"""Byte-read-only Canonical Account preflight for CBI v6.1.

This diagnostic intentionally does not construct ``UnifiedRuntime`` and does not
call the production MCP adapter.  Both of those surfaces are allowed to create
runtime directories/locks or mutation-WAL intents even when a caller only wants
to resolve an existing Account.

Instead, this command:

* reuses the Git-controlled customs normalization from ``scripts/cbi.py``;
* reads the canonical account hash-chain without creating lock files;
* reads existing Investigation headers through the canonical registry contract;
* reuses the production ``CountryAwareCanonicalRegistry.resolve`` semantics;
* snapshots the exact files it reads before/after and fails closed if they
  changed during the check;
* never creates, merges or mutates an Account.

It is a pre-commit diagnostic, not a substitute for the WAL-guarded production
``resolve_or_create_account`` mutation used by ``cbi audit-file --commit``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = Path(__file__).resolve().parent
for path in (PLUGIN_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cbi import (  # noqa: E402
    _load_json_file,
    candidate_from_customs,
    normalize_customs_record,
    production_session_root,
)
from unified_runtime import CountryAwareCanonicalRegistry, ValidationError  # noqa: E402
from unified_runtime.resilience import ACCOUNT_ID_RE, digest  # noqa: E402


class ReadOnlyHashChainLog:
    """Hash-chain reader with no lock-file or directory side effects."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            1,
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"{self.path.name}: corrupt JSONL at line {line_number}"
                ) from exc
            if event.get("seq") != line_number or event.get("prev_hash") != previous:
                raise ValidationError(
                    f"{self.path.name}: hash chain broken at line {line_number}"
                )
            claimed = event.get("event_hash")
            unsigned = {
                key: value for key, value in event.items() if key != "event_hash"
            }
            if claimed != digest(unsigned):
                raise ValidationError(
                    f"{self.path.name}: event hash mismatch at line {line_number}"
                )
            previous = str(claimed)
            events.append(event)
        return events


class ByteReadOnlyCanonicalRegistry(CountryAwareCanonicalRegistry):
    """Production resolver semantics without constructor or lock side effects."""

    def __init__(self, canonical_root: Path, session_root: Path) -> None:
        # Do not call CanonicalRegistry.__init__: it mkdirs the canonical root
        # and HashChainLog constructor mkdirs its parent.
        self.root = canonical_root
        self.session_root = session_root
        self.log = ReadOnlyHashChainLog(canonical_root / "accounts.jsonl")


def emit(value: object) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return 0


def canonical_root_for_session(session_root: Path) -> Path:
    configured = str(os.environ.get("CBI_CANONICAL_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return session_root / ".runtime" / "canonical"


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_set_snapshot(
    session_root: Path,
    canonical_root: Path,
) -> dict[str, dict[str, Any]]:
    """Snapshot exactly the persistent files this resolver may read."""

    candidates: set[Path] = {canonical_root / "accounts.jsonl"}
    if session_root.is_dir():
        candidates.update(session_root.glob("INV-*.jsonl"))

    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(candidates, key=lambda item: str(item).casefold()):
        if not path.is_file():
            continue
        stat = path.stat()
        snapshot[str(path.resolve())] = {
            "size": stat.st_size,
            "sha256": _sha256_file(path),
        }
    return snapshot


def _requested_account_id(value: str) -> str:
    requested = str(value or "").strip()
    if requested and not ACCOUNT_ID_RE.fullmatch(requested):
        raise ValueError("requested_account_id: invalid")
    return requested


def _recommendation(resolution: dict[str, Any], requested_account_id: str) -> str:
    status = str(resolution.get("status") or "")
    if status == "MATCHED":
        return "EXISTING_RUNTIME_ACCOUNT_MATCHED"
    if status == "AMBIGUOUS_MATCH":
        return "BLOCK_COMMIT_IDENTITY_REVIEW_REQUIRED"
    if status == "NOT_FOUND" and requested_account_id:
        return "REQUESTED_ID_NOT_IN_RUNTIME_RECONCILE_BEFORE_COMMIT"
    if status == "NOT_FOUND":
        return "NO_RUNTIME_MATCH_CHECK_CRM_BEFORE_CREATE"
    return "BLOCK_COMMIT_UNEXPECTED_RESOLUTION"


def canonical_preflight(
    session_root: str | None,
    record: dict[str, Any],
    *,
    requested_account_id: str = "",
) -> dict[str, Any]:
    if not session_root:
        raise ValueError(
            "canonical preflight requires an explicit/discoverable V6 session root; "
            "pass --session-root or set CBI_SESSION_ROOT"
        )

    requested = _requested_account_id(requested_account_id)
    sessions = Path(session_root).expanduser().resolve()
    canonical_root = canonical_root_for_session(sessions)
    candidate = candidate_from_customs(record)

    before = _read_set_snapshot(sessions, canonical_root)
    registry = ByteReadOnlyCanonicalRegistry(canonical_root, sessions)
    resolution = registry.resolve(
        candidate,
        requested_account_id=requested,
    )
    after = _read_set_snapshot(sessions, canonical_root)

    read_set_unchanged = before == after
    if not read_set_unchanged:
        return {
            "schema": "cbi.canonical-preflight.v1",
            "status": "CONCURRENT_STATE_CHANGE",
            "runtime_mutation_performed": False,
            "wal_mutation_performed": False,
            "persistent_write_performed": False,
            "read_set_unchanged": False,
            "candidate": candidate,
            "buyer_country_resolution": record["_buyer_country_resolution"],
            "requested_account_id": requested,
            "recommendation": "RETRY_READ_ONLY_PREFLIGHT_BEFORE_COMMIT",
            "boundary": (
                "Canonical/session files changed while the read-only preflight "
                "was executing. The result is withheld because concurrent state "
                "cannot be safely treated as one snapshot."
            ),
        }

    return {
        "schema": "cbi.canonical-preflight.v1",
        "status": str(resolution.get("status") or "UNKNOWN"),
        "runtime_mutation_performed": False,
        "wal_mutation_performed": False,
        "persistent_write_performed": False,
        "read_set_unchanged": True,
        "candidate": candidate,
        "buyer_country_resolution": record["_buyer_country_resolution"],
        "requested_account_id": requested,
        "canonical_resolution": resolution,
        "registry_path": str(canonical_root / "accounts.jsonl"),
        "session_root": str(sessions),
        "canonical_registry_file_exists": (canonical_root / "accounts.jsonl").is_file(),
        "session_header_count": len(list(sessions.glob("INV-*.jsonl")))
        if sessions.is_dir()
        else 0,
        "recommendation": _recommendation(resolution, requested),
        "boundary": (
            "This is a byte-read-only identity preflight. It does not create, "
            "merge or mutate a Canonical Account and does not write MCP WAL. "
            "NOT_FOUND means only that the Runtime registry/session headers did "
            "not resolve the candidate; it does not prove that an external CRM "
            "or workbook has no existing customer record."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cbi-canonical-preflight",
        description="Byte-read-only CBI v6.1 Canonical Account preflight",
    )
    parser.add_argument(
        "--session-root",
        default=production_session_root(),
        help=(
            "Runtime sessions root. On Windows defaults to the standard V6 "
            "production sessions root; CBI_SESSION_ROOT overrides it."
        ),
    )
    parser.add_argument(
        "--requested-account-id",
        default="",
        help=(
            "Optional exact known Account ID (for example an already reviewed "
            "CRM/Canonical C-number). This command never creates it."
        ),
    )
    parser.add_argument("input_file")
    args = parser.parse_args()

    try:
        record = normalize_customs_record(_load_json_file(args.input_file))
        return emit(
            canonical_preflight(
                args.session_root,
                record,
                requested_account_id=args.requested_account_id,
            )
        )
    except (ValueError, ValidationError) as exc:
        emit(
            {
                "schema": "cbi.canonical-preflight-error.v1",
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "runtime_mutation_performed": False,
                "wal_mutation_performed": False,
                "persistent_write_performed": False,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
