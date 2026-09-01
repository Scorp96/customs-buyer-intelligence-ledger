#!/usr/bin/env python3
"""Create a validated, immutable CBI cloud-migration bundle.

The export never copies a live mutable tree directly. It first creates a normal
ProductionBackupRecoveryManager snapshot, validates it, restores that snapshot
into an isolated session root without replaying later live writes, hashes the
restored payload, then archives the isolated payload for transfer to the cloud.

A quiescence guard snapshots the durable source again before and after archive
creation. Any durable change during the export window deletes the archive and
fails closed. Snapshot warnings are never bypassed. The operator must also keep
the Windows Runtime quiescent after a successful export until cloud cutover is
complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _default_source_root() -> Path:
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not local:
        raise SystemExit("--source-root is required when LOCALAPPDATA is unavailable")
    return Path(local) / "XingHuai" / "CustomsBuyerIntelligenceV6"


def _snapshot_manifest(backup_root: Path, snapshot_id: str) -> dict[str, Any]:
    path = backup_root / snapshot_id / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"snapshot manifest unreadable: {snapshot_id}") from exc
    if not isinstance(value, dict) or value.get("snapshot_id") != snapshot_id:
        raise SystemExit(f"snapshot manifest invalid: {snapshot_id}")
    return value


def _durable_fingerprint(manifest: dict[str, Any]) -> str:
    material = {
        "files": manifest.get("files") or {},
        "chains": manifest.get("chains") or {},
        "warnings": manifest.get("warnings") or [],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_same_source_state(
    first: dict[str, Any],
    later: dict[str, Any],
    *,
    phase: str,
) -> str:
    first_digest = _durable_fingerprint(first)
    later_digest = _durable_fingerprint(later)
    if first_digest != later_digest:
        raise SystemExit(
            "durable source changed during cloud export "
            f"({phase}); keep the Windows Runtime quiescent and retry"
        )
    return later_digest


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export validated CBI v6 durable state for cloud migration")
    p.add_argument("--source-root", type=Path, default=None, help="V6 root containing sessions/")
    p.add_argument("--output", type=Path, default=None, help="Output .tar.gz path")
    return p


def main() -> int:
    args = _parser().parse_args()
    source_root = (args.source_root or _default_source_root()).expanduser().resolve()
    session_root = source_root / "sessions"
    if not session_root.is_dir():
        raise SystemExit(f"session root not found: {session_root}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output.expanduser().resolve()
        if args.output
        else (Path.cwd() / f"CBI_Cloud_Runtime_Export_{stamp}.tar.gz").resolve()
    )
    if output.exists():
        raise SystemExit(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    initial_manifest: dict[str, Any] | None = None
    post_archive_snapshot_id = ""
    source_fingerprint = ""
    try:
        with tempfile.TemporaryDirectory(prefix="cbi-cloud-export-") as tmp_name:
            tmp = Path(tmp_name).resolve()
            backup_root = tmp / "validated-snapshots"
            bundle_root = tmp / "cbi-cloud-runtime"
            restored_session_root = bundle_root / "sessions"

            # These must be set before importing the production MCP stack because it
            # constructs UnifiedRuntime and ProductionBackupRecoveryManager at import.
            os.environ["CBI_SESSION_ROOT"] = str(session_root)
            os.environ["CBI_BACKUP_ROOT"] = str(backup_root)

            from mcp import server_v61_backup_recovery as production  # noqa: WPS433
            from unified_runtime import BUILD_ID, RUNTIME_VERSION  # noqa: WPS433

            observed = Path(production._RUNTIME.store.root).expanduser().resolve()
            if observed != session_root:
                raise SystemExit(
                    f"production Runtime root mismatch: expected {session_root}, observed {observed}"
                )

            snapshot = production._BACKUP.create_snapshot(["CLOUD_MIGRATION_EXPORT"])
            warnings = list(snapshot.get("warnings") or [])
            if warnings:
                raise SystemExit(
                    "snapshot has warnings; cloud export is fail-closed: "
                    + json.dumps(warnings, ensure_ascii=False)
                )
            initial_manifest = _snapshot_manifest(backup_root, str(snapshot["snapshot_id"]))
            source_fingerprint = _durable_fingerprint(initial_manifest)

            restore = production._BACKUP.restore_latest_valid_snapshot(
                restored_session_root,
                snapshot_id=str(snapshot["snapshot_id"]),
                replay_live_tail=False,
            )
            if not restore.get("hash_chains_valid") or not restore.get("activation_ready"):
                raise SystemExit("isolated snapshot restore is not activation-ready")

            # Detect writes that happened while the isolated restore was prepared.
            pre_archive = production._BACKUP.create_snapshot(["CLOUD_MIGRATION_EXPORT_PRE_ARCHIVE_CHECK"])
            pre_manifest = _snapshot_manifest(backup_root, str(pre_archive["snapshot_id"]))
            if list(pre_manifest.get("warnings") or []):
                raise SystemExit("pre-archive quiescence snapshot contains warnings")
            _assert_same_source_state(initial_manifest, pre_manifest, phase="pre-archive check")

            payload_hashes: dict[str, str] = {}
            for path in sorted(bundle_root.rglob("*")):
                if path.is_file():
                    payload_hashes[path.relative_to(bundle_root).as_posix()] = _sha256(path)

            manifest: dict[str, Any] = {
                "schema": "cbi.cloud-runtime-export.v1",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "runtime_version": RUNTIME_VERSION,
                "build_id": BUILD_ID,
                "git_head": _git_head(),
                "source_session_root": str(session_root),
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_created_at": snapshot.get("created_at"),
                "snapshot_file_count": snapshot.get("file_count"),
                "snapshot_session_count": snapshot.get("session_count"),
                "snapshot_warnings": warnings,
                "source_durable_fingerprint_sha256": source_fingerprint,
                "pre_archive_quiescence_check": True,
                "operator_must_keep_source_quiescent_after_export": True,
                "restored_session_root_layout": "sessions/ with .runtime/canonical, .runtime/pending, .runtime/host-pending-v6",
                "hash_chains_valid": True,
                "activation_ready": True,
                "payload_files": payload_hashes,
            }
            manifest_path = bundle_root / "export-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as tf:
                tf.add(bundle_root, arcname="cbi-cloud-runtime", recursive=True)

            # Detect writes that happened while the archive itself was being made.
            post_archive = production._BACKUP.create_snapshot(["CLOUD_MIGRATION_EXPORT_POST_ARCHIVE_CHECK"])
            post_archive_snapshot_id = str(post_archive["snapshot_id"])
            post_manifest = _snapshot_manifest(backup_root, post_archive_snapshot_id)
            if list(post_manifest.get("warnings") or []):
                raise SystemExit("post-archive quiescence snapshot contains warnings")
            _assert_same_source_state(initial_manifest, post_manifest, phase="post-archive check")
    except BaseException:
        if output.exists():
            output.unlink()
        raise

    print(json.dumps({
        "status": "PASS",
        "output": str(output),
        "archive_sha256": _sha256(output),
        "source_session_root": str(session_root),
        "source_durable_fingerprint_sha256": source_fingerprint,
        "post_archive_quiescence_snapshot_id": post_archive_snapshot_id,
        "source_stable_through_export": True,
        "migration_bundle_contains_private_durable_state": True,
        "operator_cutover_rule": "Do not allow any further Windows durable writes after this successful export.",
        "instruction": "Transfer this archive directly to the controlled cloud host. Never commit it to GitHub.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
