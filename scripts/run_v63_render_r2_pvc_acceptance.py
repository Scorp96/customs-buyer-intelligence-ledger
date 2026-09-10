#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.object_store_persistence import S3CompatibleClient, S3Config
from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63
from unified_runtime.exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness
from unified_runtime.exact_checkout_persistence_reader_v63 import ExactCheckoutPersistenceReader
from unified_runtime.render_r2_acceptance_client_v63 import (
    RenderR2AcceptanceClient,
    RenderR2AcceptanceClientConfig,
    RenderR2AcceptanceClientError,
)
from unified_runtime.render_r2_pvc_acceptance_v63 import (
    MUTATION_EVENT_TYPES,
    PERSISTENCE_PROBE_SCHEMA,
    run_v63_render_r2_pvc_acceptance,
    sanitize_pvc_acceptance_value,
)
from unified_runtime.render_r2_pvc_acceptance_validator_v63 import (
    validate_v63_render_r2_pvc_acceptance,
)


STATUS_ARTIFACT = "V63_RENDER_R2_PVC_ACCEPTANCE_STATUS.json"
RECEIPT_ARTIFACT = "V63_RENDER_R2_PVC_ACCEPTANCE.json"
VALIDATION_ARTIFACT = "V63_RENDER_R2_PVC_ACCEPTANCE_VALIDATION.json"
PRODUCTION_BASELINE = "ba3bffdae13cef186b20b50335c3207fb3390ec6"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_EXTERNAL_FIELDS = {
    "CBI_V63_RENDER_DEPLOY_HOOK_URL": "render_deploy_hook",
    "CBI_V63_RENDER_RESTART_HOOK_URL": "render_restart_hook",
    "CBI_V63_ACCEPTANCE_BASE_URL": "acceptance_base_url",
    "CBI_V63_ACCEPTANCE_BEARER_TOKEN": "acceptance_auth",
    "CBI_V63_R2_ENDPOINT": "r2_endpoint",
    "CBI_V63_R2_BUCKET": "r2_bucket",
    "CBI_V63_R2_ACCESS_KEY_ID": "r2_access",
    "CBI_V63_R2_SECRET_ACCESS_KEY": "r2_secret",
    "CBI_V63_R2_PREFIX": "r2_prefix",
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _safe_status(
    *,
    status: str,
    verified: bool,
    error_code: str | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": "cbi.render-r2-pvc-external-gate-status.v6.3",
        "status": status,
        "verified": bool(verified),
        "production_ready": False,
        "production_baseline_expected": PRODUCTION_BASELINE,
    }
    if error_code:
        row["error_code"] = str(error_code)
    if missing:
        row["missing_external_configuration"] = sorted(set(missing))
    return row


def _external_configuration() -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for env_name, safe_name in _EXTERNAL_FIELDS.items():
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            values[env_name] = value
        else:
            missing.append(safe_name)
    values["CBI_V63_R2_REGION"] = str(
        os.environ.get("CBI_V63_R2_REGION") or "auto"
    ).strip() or "auto"
    return values, missing


def _checkout_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    value = completed.stdout.strip().lower()
    if completed.returncode != 0 or _GIT_SHA_RE.fullmatch(value) is None:
        raise RuntimeError("CHECKOUT_GIT_SHA_UNAVAILABLE")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_quiescent_synthetic_migration_archive(
    live_root: Path,
    destination: Path,
) -> Path:
    source = Path(live_root).expanduser().resolve()
    root = destination / "cbi-cloud-runtime"
    root.mkdir(parents=True)
    for component in ("sessions", "mcp-idempotency-v61"):
        component_source = source / component
        if component_source.is_dir():
            shutil.copytree(component_source, root / component)
    if not (root / "sessions").is_dir():
        raise RuntimeError("SYNTHETIC_R2_SEED_SESSIONS_MISSING")

    payload = {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema": "cbi.cloud-runtime-export.v1",
        "hash_chains_valid": True,
        "activation_ready": True,
        "pre_archive_quiescence_check": True,
        "payload_files": payload,
        "source_durable_fingerprint_sha256": "0" * 64,
    }
    (root / "export-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    archive = destination / "migration.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        tf.add(root, arcname="cbi-cloud-runtime", recursive=True)
    return archive


def _ensure_disposable_r2_baseline(
    *,
    manager: RecoveryObjectStoreStateManagerV63,
    checkout_root: Path,
) -> dict[str, Any]:
    """Seed an empty isolated namespace once; never replace existing authority."""

    pointer = manager.read_pointer(required=False)
    if pointer is not None:
        return {
            "seeded": False,
            "generation": pointer.generation,
            "archive_format": pointer.archive_format,
        }

    with tempfile.TemporaryDirectory(prefix="cbi-v63-external-r2-seed-") as tmp_name:
        tmp = Path(tmp_name)
        live_root = tmp / "live"
        harness = ExactCheckoutMcpHarness(Path(checkout_root).resolve(), live_root)
        harness.start()
        try:
            started = harness.tool(
                2,
                "start_investigation",
                {
                    "account": {
                        "account_id": "C-V63-EXTERNAL-SEED",
                        "country": "Synthetic",
                        "name": "Synthetic v6.3 External Acceptance Seed",
                    },
                    "mode": "EXHAUSTIVE",
                    "history": {"events": []},
                    "network_policy": {"closure_strategy": "DECISION_SATURATION"},
                    "idempotency_key": "v63-external-seed-start-0001",
                },
            )
            if not str(started.get("investigation_id") or "").strip():
                raise RuntimeError("SYNTHETIC_R2_SEED_INVESTIGATION_MISSING")
        finally:
            harness.stop()

        migration_dir = tmp / "migration"
        migration_dir.mkdir()
        archive = _build_quiescent_synthetic_migration_archive(live_root, migration_dir)
        pointer = manager.seed_migration_archive(archive, _sha256_file(archive))

    return {
        "seeded": True,
        "generation": pointer.generation,
        "archive_format": pointer.archive_format,
    }


def _extract_deployment_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("id", "deploy_id", "deployId", "deployment_id", "deploymentId"):
            candidate = str(value.get(key) or "").strip()
            if candidate:
                return candidate
        for key in ("deploy", "deployment", "data"):
            candidate = _extract_deployment_id(value.get(key))
            if candidate:
                return candidate
    return ""


def _trigger_render_hook(url: str, label: str) -> str:
    request = urllib.request.Request(
        str(url),
        data=b"",
        method="POST",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            body = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise RuntimeError(f"{label}_TRIGGER_FAILED") from exc
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}_TRIGGER_RESPONSE_INVALID") from exc
    deployment_id = _extract_deployment_id(payload)
    if not deployment_id:
        raise RuntimeError(f"{label}_DEPLOYMENT_ID_MISSING")
    return deployment_id


def _poll_pinned_health(
    client: RenderR2AcceptanceClient,
    *,
    timeout_seconds: float,
    required_restore_generation: int | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    last_error = "REMOTE_HEALTH_NOT_READY"
    while time.monotonic() < deadline:
        try:
            health = client.read_health()
            identity = health.get("deployment_identity") if isinstance(health, dict) else None
            identity = identity if isinstance(identity, dict) else {}
            if required_restore_generation is not None:
                if identity.get("restore_generation") != required_restore_generation:
                    last_error = "REMOTE_RESTORE_GENERATION_NOT_READY"
                    time.sleep(3.0)
                    continue
                if identity.get("restore_source") != "object_state_v2":
                    last_error = "REMOTE_RESTORE_SOURCE_NOT_V2"
                    time.sleep(3.0)
                    continue
            return health
        except RenderR2AcceptanceClientError as exc:
            last_error = str(exc).split(":", 1)[0]
        time.sleep(3.0)
    raise RuntimeError(last_error)


class RenderR2ExternalReplacementController:
    def __init__(
        self,
        *,
        object_client: S3CompatibleClient,
        prefix: str,
        restart_hook_url: str,
        acceptance_client: RenderR2AcceptanceClient,
        initial_deployment_id: str,
        poll_timeout_seconds: float,
    ) -> None:
        self.object_client = object_client
        self.prefix = str(prefix).strip().strip("/")
        self.restart_hook_url = str(restart_hook_url)
        self.acceptance_client = acceptance_client
        self.current_deployment_id = str(initial_deployment_id)
        self.poll_timeout_seconds = float(poll_timeout_seconds)

    def _manager(self) -> RecoveryObjectStoreStateManagerV63:
        return RecoveryObjectStoreStateManagerV63(
            self.object_client,
            prefix=self.prefix,
        )

    def collect(self, investigation_id: str) -> dict[str, Any]:
        manager = self._manager()
        pointer = manager.read_pointer(required=True)
        assert pointer is not None
        with tempfile.TemporaryDirectory(prefix="cbi-v63-real-r2-proof-") as tmp_name:
            live_root = Path(tmp_name) / "live"
            if not manager.restore_into(live_root):
                raise RuntimeError("R2_CURRENT_STATE_MISSING")
            reader = ExactCheckoutPersistenceReader(live_root)
            events: dict[str, Any] = {}
            wal: dict[str, Any] = {}
            for tool in MUTATION_EVENT_TYPES:
                evidence = reader.normalize_mutation_evidence(investigation_id, tool)
                event_rows = list(evidence.get("events") or [])
                wal_rows = list(evidence.get("wal_records") or [])
                event = dict(event_rows[0]) if len(event_rows) == 1 else {}
                wal_row = dict(wal_rows[0]) if len(wal_rows) == 1 else {}
                events[tool] = {
                    "count": len(event_rows),
                    "event_type": event.get("event_type"),
                    "seq": event.get("seq"),
                    "correlation_id": event.get("correlation_id"),
                    "request_sha256": event.get("request_sha256"),
                    "result_snapshot": event.get("result_snapshot"),
                    "result_snapshot_sha256": event.get("result_snapshot_sha256"),
                }
                wal[tool] = {
                    "count": len(wal_rows),
                    "status": wal_row.get("status"),
                    "correlation_id": wal_row.get("correlation_id"),
                    "request_sha256": wal_row.get("request_sha256"),
                    "result": wal_row.get("result"),
                    "result_sha256": wal_row.get("result_sha256"),
                }
        return sanitize_pvc_acceptance_value(
            {
                "schema": PERSISTENCE_PROBE_SCHEMA,
                "generation": pointer.generation,
                "archive_format": pointer.archive_format,
                "events": events,
                "wal": wal,
            }
        )

    def replace_instance(self) -> dict[str, Any]:
        manager = self._manager()
        pointer = manager.read_pointer(required=True)
        assert pointer is not None
        source_generation = int(pointer.generation)
        before = self.current_deployment_id
        after = _trigger_render_hook(
            self.restart_hook_url,
            "RENDER_RESTART",
        )
        if after == before:
            raise RuntimeError("RENDER_RESTART_DEPLOYMENT_ID_NOT_CHANGED")
        health = _poll_pinned_health(
            self.acceptance_client,
            timeout_seconds=self.poll_timeout_seconds,
            required_restore_generation=source_generation,
        )
        identity = health.get("deployment_identity") if isinstance(health, dict) else None
        identity = identity if isinstance(identity, dict) else {}
        self.current_deployment_id = after
        return {
            "instance_before": before,
            "instance_after": after,
            "restored_generation": identity.get("restore_generation"),
            "restore_source": identity.get("restore_source"),
        }


def _run_external(
    *,
    expected_git_sha: str,
    output_dir: Path,
    configuration: dict[str, str],
    poll_timeout_seconds: float,
) -> int:
    expected = str(expected_git_sha or "").strip().lower()
    if _GIT_SHA_RE.fullmatch(expected) is None:
        raise RuntimeError("EXPECTED_GIT_SHA_INVALID")
    if _checkout_sha() != expected:
        raise RuntimeError("CHECKOUT_GIT_SHA_MISMATCH")

    prefix = configuration["CBI_V63_R2_PREFIX"].strip().strip("/")
    if not prefix or "production" in prefix.casefold():
        raise RuntimeError("R2_ACCEPTANCE_PREFIX_NOT_ISOLATED")

    object_client = S3CompatibleClient(
        S3Config(
            endpoint=configuration["CBI_V63_R2_ENDPOINT"],
            bucket=configuration["CBI_V63_R2_BUCKET"],
            access_key_id=configuration["CBI_V63_R2_ACCESS_KEY_ID"],
            secret_access_key=configuration["CBI_V63_R2_SECRET_ACCESS_KEY"],
            region=configuration["CBI_V63_R2_REGION"],
        )
    )
    seed_manager = RecoveryObjectStoreStateManagerV63(object_client, prefix=prefix)
    _ensure_disposable_r2_baseline(manager=seed_manager, checkout_root=ROOT)

    initial_deployment_id = _trigger_render_hook(
        configuration["CBI_V63_RENDER_DEPLOY_HOOK_URL"],
        "RENDER_DEPLOY",
    )
    client = RenderR2AcceptanceClient(
        RenderR2AcceptanceClientConfig(
            base_url=configuration["CBI_V63_ACCEPTANCE_BASE_URL"],
            bearer_token=configuration["CBI_V63_ACCEPTANCE_BEARER_TOKEN"],
            expected_git_sha=expected,
            timeout_seconds=30.0,
        )
    )
    _poll_pinned_health(client, timeout_seconds=poll_timeout_seconds)

    controller = RenderR2ExternalReplacementController(
        object_client=object_client,
        prefix=prefix,
        restart_hook_url=configuration["CBI_V63_RENDER_RESTART_HOOK_URL"],
        acceptance_client=client,
        initial_deployment_id=initial_deployment_id,
        poll_timeout_seconds=poll_timeout_seconds,
    )
    receipt = run_v63_render_r2_pvc_acceptance(client, controller)
    validation = validate_v63_render_r2_pvc_acceptance(receipt)
    _write_json(output_dir / RECEIPT_ARTIFACT, receipt)
    _write_json(output_dir / VALIDATION_ARTIFACT, validation)

    verified = validation.get("status") == "VERIFIED" and not validation.get("blockers")
    status = _safe_status(status="VERIFIED" if verified else "BLOCKED", verified=verified)
    _write_json(output_dir / STATUS_ARTIFACT, status)
    return 0 if verified else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute the isolated CBI v6.3 Render/R2/PVC external acceptance gate."
    )
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--poll-timeout-seconds", type=float, default=600.0)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    configuration, missing = _external_configuration()
    if missing:
        _write_json(
            output_dir / STATUS_ARTIFACT,
            _safe_status(
                status="BLOCKED_EXTERNAL",
                verified=False,
                error_code="EXTERNAL_CONFIGURATION_MISSING",
                missing=missing,
            ),
        )
        return 2

    try:
        return _run_external(
            expected_git_sha=args.expected_git_sha,
            output_dir=output_dir,
            configuration=configuration,
            poll_timeout_seconds=args.poll_timeout_seconds,
        )
    except Exception as exc:
        safe_code = re.sub(r"[^A-Z0-9_:-]", "_", str(exc).upper())[:160]
        _write_json(
            output_dir / STATUS_ARTIFACT,
            _safe_status(
                status="BLOCKED_EXTERNAL",
                verified=False,
                error_code=safe_code or "EXTERNAL_GATE_FAILED",
            ),
        )
        print(
            json.dumps(
                {
                    "status": "BLOCKED_EXTERNAL",
                    "production_ready": False,
                    "error_code": safe_code or "EXTERNAL_GATE_FAILED",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
