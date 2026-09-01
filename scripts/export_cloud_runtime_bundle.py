#!/usr/bin/env python3
"""Create a validated, immutable CBI cloud-migration bundle.

The export never copies a live mutable tree directly. It first creates a normal
ProductionBackupRecoveryManager snapshot, validates it, restores that snapshot
into an isolated session root without replaying later live writes, hashes the
restored payload, then archives the isolated payload for transfer to the cloud.
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


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export validated CBI v6 durable state for cloud migration")
    p.add_argument("--source-root", type=Path, default=None, help="V6 root containing sessions/")
    p.add_argument("--output", type=Path, default=None, help="Output .tar.gz path")
    p.add_argument("--allow-snapshot-warnings", action="store_true")
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
        if warnings and not args.allow_snapshot_warnings:
            raise SystemExit(
                "snapshot has warnings; refusing cloud export without --allow-snapshot-warnings: "
                + json.dumps(warnings, ensure_ascii=False)
            )

        restore = production._BACKUP.restore_latest_valid_snapshot(
            restored_session_root,
            snapshot_id=str(snapshot["snapshot_id"]),
            replay_live_tail=False,
        )
        if not restore.get("hash_chains_valid") or not restore.get("activation_ready"):
            raise SystemExit("isolated snapshot restore is not activation-ready")

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

    print(json.dumps({
        "status": "PASS",
        "output": str(output),
        "archive_sha256": _sha256(output),
        "source_session_root": str(session_root),
        "migration_bundle_contains_private_durable_state": True,
        "instruction": "Transfer this archive directly to the controlled cloud host. Never commit it to GitHub.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
