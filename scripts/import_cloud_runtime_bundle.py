#!/usr/bin/env python3
"""Import a validated CBI cloud-runtime bundle into a new durable data root.

The importer is fail-closed: the transferred archive must match the exact
SHA-256 emitted by the trusted Windows exporter; no path traversal, duplicate
members, links, devices, overwrite of a non-empty target, missing/extra payload
files, or hash mismatches are allowed. After atomic activation it imports the
real production MCP stack against the new session root so hash-chain/runtime
health is checked before deployment proceeds. A validated CLOUD_IMPORT_BASELINE
snapshot is then created inside the cloud backup root before service startup.
There is no production health-check bypass.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_ARCHIVE_MEMBERS = 200_000
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError("--expected-sha256 must be exactly 64 hexadecimal characters")
    return normalized


def _safe_relative(name: str) -> PurePosixPath:
    value = PurePosixPath(name)
    if value.is_absolute() or not value.parts or any(part in {"", ".", ".."} for part in value.parts):
        raise ValueError(f"unsafe archive member: {name}")
    if value.parts[0] != "cbi-cloud-runtime":
        raise ValueError(f"unexpected archive root: {name}")
    return value


def _extract_safely(archive: Path, staging: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        if not members:
            raise ValueError("cloud runtime archive is empty")
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("cloud runtime archive contains too many members")
        total_size = sum(max(0, int(member.size)) for member in members)
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("cloud runtime archive exceeds uncompressed size limit")
        seen: set[str] = set()
        for member in members:
            relative = _safe_relative(member.name)
            canonical_name = relative.as_posix()
            if canonical_name in seen:
                raise ValueError(f"duplicate archive member forbidden: {member.name}")
            seen.add(canonical_name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"archive links/devices are forbidden: {member.name}")
            destination = staging.joinpath(*relative.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"unsupported archive member type: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = tf.extractfile(member)
            if source is None:
                raise ValueError(f"archive member unreadable: {member.name}")
            with source, destination.open("xb") as out:
                shutil.copyfileobj(source, out, length=1024 * 1024)
    return staging / "cbi-cloud-runtime"


def _verify_payload(root: Path) -> dict:
    manifest_path = root / "export-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid export-manifest.json") from exc
    if manifest.get("schema") != "cbi.cloud-runtime-export.v1":
        raise ValueError("unexpected cloud export schema")
    if manifest.get("hash_chains_valid") is not True or manifest.get("activation_ready") is not True:
        raise ValueError("cloud export was not activation-ready")
    if manifest.get("pre_archive_quiescence_check") is not True:
        raise ValueError("cloud export lacks source quiescence proof")
    expected = manifest.get("payload_files")
    if not isinstance(expected, dict):
        raise ValueError("payload file hash manifest missing")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "export-manifest.json"
    }
    if actual_files != set(expected):
        missing = sorted(set(expected) - actual_files)
        extra = sorted(actual_files - set(expected))
        raise ValueError(f"payload inventory mismatch; missing={missing}; extra={extra}")
    for relative, expected_hash in expected.items():
        path = root / str(relative)
        if _sha256(path) != str(expected_hash):
            raise ValueError(f"payload hash mismatch: {relative}")
    sessions = root / "sessions"
    if not sessions.is_dir():
        raise ValueError("sessions/ missing from cloud runtime bundle")
    return manifest


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import a validated CBI cloud runtime bundle")
    p.add_argument("archive", type=Path)
    p.add_argument(
        "--expected-sha256",
        required=True,
        help="Exact archive SHA-256 printed by the trusted Windows export command",
    )
    p.add_argument("--target-root", type=Path, default=Path("/srv/cbi-data"))
    return p


def main() -> int:
    args = _parser().parse_args()
    archive = args.archive.expanduser().resolve()
    target = args.target_root.expanduser().resolve()
    if not archive.is_file():
        raise SystemExit(f"archive not found: {archive}")
    expected_archive_hash = _expected_sha256(args.expected_sha256)
    archive_hash = _sha256(archive)
    if not hmac.compare_digest(archive_hash, expected_archive_hash):
        raise SystemExit(
            f"archive SHA-256 mismatch: expected {expected_archive_hash}, observed {archive_hash}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise SystemExit(f"target must not exist or must be an empty directory: {target}")
        target.rmdir()

    staging_parent = Path(tempfile.mkdtemp(prefix=f".{target.name}.import-", dir=target.parent))
    activated = False
    baseline_snapshot: dict | None = None
    try:
        extracted = _extract_safely(archive, staging_parent)
        manifest = _verify_payload(extracted)
        os.replace(extracted, target)
        activated = True

        os.environ["CBI_SESSION_ROOT"] = str(target / "sessions")
        os.environ["CBI_BACKUP_ROOT"] = str(target / "backups-v61")
        # This imports the exact accepted production stack against the newly
        # activated cloud root. Any chain/runtime integrity failure aborts.
        from mcp import server_v61_backup_recovery as production  # noqa: WPS433

        observed = Path(production._RUNTIME.store.root).expanduser().resolve()
        if observed != (target / "sessions").resolve():
            raise RuntimeError("production Runtime did not bind imported cloud session root")
        health = production._TOOL_HANDLERS["get_runtime_health"]({})
        if not isinstance(health, dict):
            raise RuntimeError("production Runtime health did not return an object")

        baseline_snapshot = production._BACKUP.create_snapshot(["CLOUD_IMPORT_BASELINE"])
        if list(baseline_snapshot.get("warnings") or []):
            raise RuntimeError(
                "cloud import baseline snapshot contains warnings: "
                + json.dumps(baseline_snapshot.get("warnings"), ensure_ascii=False)
            )
        validation = production._BACKUP.validate_snapshot(str(baseline_snapshot["snapshot_id"]))
        if validation.get("valid") is not True:
            raise RuntimeError("cloud import baseline backup did not validate")

        print(json.dumps({
            "status": "PASS",
            "archive": str(archive),
            "archive_sha256": archive_hash,
            "archive_sha256_verified": True,
            "target_root": str(target),
            "session_root": str(target / "sessions"),
            "source_snapshot_id": manifest.get("snapshot_id"),
            "source_git_head": manifest.get("git_head"),
            "source_durable_fingerprint_sha256": manifest.get("source_durable_fingerprint_sha256"),
            "runtime_health_checked": True,
            "cloud_baseline_snapshot_id": baseline_snapshot.get("snapshot_id"),
            "cloud_baseline_snapshot_validated": True,
            "next": "chown the target to uid/gid 10001, then start deploy/cloud/docker-compose.yml",
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        if activated and target.exists():
            # Initial import has no pre-existing target. On a failed post-activate
            # health or baseline-backup check, remove only the just-imported target
            # instead of leaving a questionable durable root available to Docker.
            shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
