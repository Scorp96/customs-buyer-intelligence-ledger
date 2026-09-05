#!/usr/bin/env python3
"""Cloud/always-on entrypoint for the accepted CBI v6.1 production Runtime.

This entrypoint deliberately reuses the exact production backup/recovery handler
stack. Only the transport changes from child-process stdio to stateless HTTP.
The durable session root must be explicit so a cloud process can never fall back
to a developer-machine default location.

On ephemeral hosts the optional S3-compatible v6.3 recovery manager binds both
sessions and mutation WAL into one CAS-protected generation. A post-handler
checkpoint mirrors the handler side effect together with its PREPARED WAL before
the adapter can take a crash-injected cold exit; the ordinary post-call sync then
persists the terminal WAL receipt. CAS conflicts and checkpoint failures fail
closed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_DEPLOYMENT_IDENTITY_SCHEMA = "cbi.remote-deployment-identity.v6.3"
_PROCESS_STARTED_AT = datetime.now(timezone.utc)


def _env_flag(name: str) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if raw in {"", "0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise RuntimeError(f"{name} must be a boolean flag")


def _resolve_deployment_git_sha(*, pin_required: bool) -> str | None:
    raw = str(os.environ.get("RENDER_GIT_COMMIT") or "").strip()
    if _GIT_SHA_RE.fullmatch(raw):
        return raw.lower()
    if pin_required:
        raise RuntimeError("DEPLOYMENT_GIT_SHA_INVALID_OR_MISSING")
    return None


def _safe_object_store_mode() -> str:
    raw = str(os.environ.get("CBI_OBJECT_STORE_MODE") or "none").strip().lower()
    if raw in {"", "none", "off", "disabled"}:
        return "none"
    if raw in {"s3", "r2"}:
        return raw
    # ``from_env`` performs the authoritative startup rejection. Never echo an
    # arbitrary environment value into health.
    return "invalid"


def _require_explicit_durable_root() -> Path:
    configured = str(os.environ.get("CBI_SESSION_ROOT") or "").strip()
    if not configured:
        raise RuntimeError("CBI_SESSION_ROOT is required for remote production startup")
    root = Path(configured).expanduser()
    if not root.is_absolute():
        raise RuntimeError("CBI_SESSION_ROOT must be an absolute path for remote production startup")
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise RuntimeError("CBI_SESSION_ROOT is not a directory")
    probe = root / ".remote-write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError("CBI_SESSION_ROOT must be writable") from exc
    return root.resolve()


_ACCEPTANCE_PIN_REQUIRED = _env_flag("CBI_V63_ACCEPTANCE_PIN_DEPLOYMENT_SHA")
_DEPLOYMENT_GIT_SHA = _resolve_deployment_git_sha(pin_required=_ACCEPTANCE_PIN_REQUIRED)
_EXPECTED_ROOT = _require_explicit_durable_root()
_LIVE_ROOT = _EXPECTED_ROOT.parent

# Import only after the explicit-root and deployment-identity guards. The
# production module creates the UnifiedRuntime at import time and therefore must
# observe CBI_SESSION_ROOT; acceptance pin failures must occur before it starts.
from mcp import server_v61_backup_recovery as _production  # noqa: E402
from mcp.c279_single_session_export_v64 import build_export_callback  # noqa: E402
from mcp.chatgpt_oauth_transport import main as _remote_transport_main  # noqa: E402
from mcp.object_store_recovery_v63 import (  # noqa: E402
    RecoveryObjectStoreStateManagerV63,
)
from mcp.remote_durability_checkpoint_v63 import (  # noqa: E402
    install_remote_durability_checkpoint,
)


_RUNTIME = _production._RUNTIME
_BASE_DISPATCH = _production._v61._server.handle
_DIAGNOSTIC_STATIC_BEARER = str(os.environ.get("CBI_REMOTE_BEARER_TOKEN") or "")
_DIAGNOSTIC_EXPORT = build_export_callback(
    _RUNTIME.store.root,
    os.environ,
    process_started_at=_PROCESS_STARTED_AT,
)
if len(_DIAGNOSTIC_STATIC_BEARER) < 32:
    _DIAGNOSTIC_EXPORT = None
_PERSISTENCE = RecoveryObjectStoreStateManagerV63.from_env()
if _PERSISTENCE is not None:
    _PERSISTENCE.attach_existing(_LIVE_ROOT)


def _sync_after_handler() -> None:
    """Persist side effect + PREPARED WAL before mutation control can cold-exit."""

    if _PERSISTENCE is not None:
        _PERSISTENCE.sync_if_changed(_LIVE_ROOT)


def _sync_after_tool_call() -> None:
    """Persist terminal WAL state after a normal or exception-returning tool call."""

    if _PERSISTENCE is not None:
        _PERSISTENCE.sync_if_changed(_LIVE_ROOT)


if _PERSISTENCE is not None:
    install_remote_durability_checkpoint(_production._v61, _sync_after_handler)


def _dispatch(method: str, params: dict[str, Any]) -> Any:
    """Dispatch one MCP method and persist any resulting durable state change.

    Read-only calls remain fingerprint no-ops. Mutations receive an earlier
    post-handler checkpoint from ``install_remote_durability_checkpoint`` so a
    crash after the handler cannot strand the only recovery evidence on an
    ephemeral instance. This post-call sync remains necessary to mirror the
    terminal COMMITTED/COMMITTED_ERROR receipt after ordinary completion.
    """
    if method != "tools/call":
        return _BASE_DISPATCH(method, params)
    try:
        result = _BASE_DISPATCH(method, params)
    except Exception:
        _sync_after_tool_call()
        raise
    _sync_after_tool_call()
    return result


def _restore_lineage() -> tuple[int | None, str | None]:
    manifest_path = _LIVE_ROOT / "export-manifest.json"
    try:
        row = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(row, dict):
        return None, None
    raw_generation = row.get("restored_generation")
    generation = (
        raw_generation
        if isinstance(raw_generation, int) and not isinstance(raw_generation, bool) and raw_generation >= 0
        else None
    )
    schema = str(row.get("schema") or "").strip()
    safe_sources = {
        "cbi.object-store-state.v1": "object_state_v1",
        "cbi.object-store-state.v2": "object_state_v2",
        "cbi.cloud-runtime-export.v1": "migration_v1",
    }
    return generation, safe_sources.get(schema)


def _object_state_schema(persistence_health: dict[str, Any]) -> str | None:
    recovery_schema = str(persistence_health.get("recovery_state_schema") or "").strip()
    if recovery_schema == "cbi.object-store-state.v2":
        return recovery_schema
    archive_format = str(persistence_health.get("archive_format") or "").strip()
    if archive_format == "object_state_v1":
        return "cbi.object-store-state.v1"
    return None


def _deployment_identity(persistence_health: dict[str, Any]) -> dict[str, Any]:
    restore_generation, restore_source = _restore_lineage()
    generation = persistence_health.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        generation = None
    return {
        "schema": _DEPLOYMENT_IDENTITY_SCHEMA,
        "git_sha": _DEPLOYMENT_GIT_SHA,
        "git_sha_source": "RENDER_GIT_COMMIT" if _DEPLOYMENT_GIT_SHA else None,
        "acceptance_pin_required": _ACCEPTANCE_PIN_REQUIRED,
        "remote_entrypoint": "mcp/server_v61_remote.py",
        "runtime_entrypoint": "mcp/server_v61_backup_recovery.py",
        "object_store_mode": _safe_object_store_mode(),
        "object_state_schema": _object_state_schema(persistence_health),
        "object_state_generation": generation,
        "restore_generation": restore_generation,
        "restore_source": restore_source,
    }


def _health() -> dict[str, Any]:
    observed = Path(_RUNTIME.store.root).expanduser().resolve()
    if observed != _EXPECTED_ROOT:
        raise RuntimeError("production Runtime is bound to an unexpected durable root")
    persistence_health = _PERSISTENCE.health() if _PERSISTENCE is not None else {}
    health = {
        "status": "ok",
        "service": "customs-buyer-intelligence",
        "transport": "streamable-http-stateless",
        "durable_root_bound": True,
        "backup_recovery_enabled": True,
        "object_store_persistence_enabled": _PERSISTENCE is not None,
        "remote_post_handler_checkpoint_enabled": _PERSISTENCE is not None,
        "deployment_identity": _deployment_identity(persistence_health),
    }
    if _PERSISTENCE is not None:
        health["object_store_persistence"] = persistence_health
        if persistence_health.get("last_error"):
            health["status"] = "degraded"
    return health


def main() -> int:
    # Delegate CLI parsing to the ChatGPT-aware remote transport so --host/--port
    # remain operator overrides while auth can accept static admin bearer and
    # explicitly allowlisted GitHub OAuth identities.
    return _remote_transport_main(
        _dispatch,
        health=_health,
        diagnostic_export=_DIAGNOSTIC_EXPORT,
        diagnostic_static_bearer=_DIAGNOSTIC_STATIC_BEARER,
    )


if __name__ == "__main__":
    raise SystemExit(main())
