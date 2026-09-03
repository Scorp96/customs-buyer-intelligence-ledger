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

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


_EXPECTED_ROOT = _require_explicit_durable_root()
_LIVE_ROOT = _EXPECTED_ROOT.parent

# Import only after the explicit-root guard. The production module creates the
# UnifiedRuntime at import time and therefore must observe CBI_SESSION_ROOT.
from mcp import server_v61_backup_recovery as _production  # noqa: E402
from mcp.chatgpt_oauth_transport import main as _remote_transport_main  # noqa: E402
from mcp.object_store_recovery_v63 import (  # noqa: E402
    RecoveryObjectStoreStateManagerV63,
)
from mcp.remote_durability_checkpoint_v63 import (  # noqa: E402
    install_remote_durability_checkpoint,
)


_RUNTIME = _production._RUNTIME
_BASE_DISPATCH = _production._v61._server.handle
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


def _health() -> dict[str, Any]:
    observed = Path(_RUNTIME.store.root).expanduser().resolve()
    if observed != _EXPECTED_ROOT:
        raise RuntimeError("production Runtime is bound to an unexpected durable root")
    health = {
        "status": "ok",
        "service": "customs-buyer-intelligence",
        "transport": "streamable-http-stateless",
        "durable_root_bound": True,
        "backup_recovery_enabled": True,
        "object_store_persistence_enabled": _PERSISTENCE is not None,
        "remote_post_handler_checkpoint_enabled": _PERSISTENCE is not None,
    }
    if _PERSISTENCE is not None:
        persistence_health = _PERSISTENCE.health()
        health["object_store_persistence"] = persistence_health
        if persistence_health.get("last_error"):
            health["status"] = "degraded"
    return health


def main() -> int:
    # Delegate CLI parsing to the ChatGPT-aware remote transport so --host/--port
    # remain operator overrides while auth can accept static admin bearer and
    # explicitly allowlisted GitHub OAuth identities.
    return _remote_transport_main(_dispatch, health=_health)


if __name__ == "__main__":
    raise SystemExit(main())
