#!/usr/bin/env python3
"""Cloud/always-on entrypoint for the accepted CBI v6.1 production Runtime.

This entrypoint deliberately reuses the exact production backup/recovery handler
stack. Only the transport changes from child-process stdio to stateless HTTP.
The durable session root must be explicit so a cloud process can never fall back
to a developer-machine default location.

On ephemeral hosts an optional S3-compatible state manager attaches to the
restored object-store generation. Every MCP tool call then performs a cheap
sessions fingerprint check; a changed durable state is archived and committed
through a conditional current-pointer update. CAS conflicts fail closed.
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
from mcp.object_store_persistence import ObjectStoreStateManager  # noqa: E402


_RUNTIME = _production._RUNTIME
_BASE_DISPATCH = _production._v61._server.handle
_PERSISTENCE = ObjectStoreStateManager.from_env()
if _PERSISTENCE is not None:
    _PERSISTENCE.attach_existing(_LIVE_ROOT)


def _sync_after_tool_call() -> None:
    if _PERSISTENCE is not None:
        _PERSISTENCE.sync_if_changed(_LIVE_ROOT)


def _dispatch(method: str, params: dict[str, Any]) -> Any:
    """Dispatch one MCP method and persist any resulting durable state change.

    We inspect after every tools/call rather than maintaining a second hard-coded
    mutating-tool list here. Fingerprinting makes read-only calls a no-op, and
    this automatically covers future durable tools. If the underlying handler
    raises after writing WAL/partial recovery state, we still attempt to mirror
    that changed durable tree before re-raising.
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
