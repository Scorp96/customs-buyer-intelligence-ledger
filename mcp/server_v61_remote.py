#!/usr/bin/env python3
"""Cloud/always-on entrypoint for the accepted CBI v6.1 production Runtime.

This entrypoint deliberately reuses the exact production backup/recovery handler
stack. Only the transport changes from child-process stdio to stateless HTTP.
The durable session root must be explicit so a cloud process can never fall back
to a developer-machine default location.
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

# Import only after the explicit-root guard. The production module creates the
# UnifiedRuntime at import time and therefore must observe CBI_SESSION_ROOT.
from mcp import server_v61_backup_recovery as _production  # noqa: E402
from mcp.remote_transport import main as _remote_transport_main  # noqa: E402


_RUNTIME = _production._RUNTIME
_DISPATCH = _production._v61._server.handle


def _health() -> dict[str, Any]:
    observed = Path(_RUNTIME.store.root).expanduser().resolve()
    if observed != _EXPECTED_ROOT:
        raise RuntimeError("production Runtime is bound to an unexpected durable root")
    return {
        "status": "ok",
        "service": "customs-buyer-intelligence",
        "transport": "streamable-http-stateless",
        "durable_root_bound": True,
        "backup_recovery_enabled": True,
    }


def main() -> int:
    # Delegate CLI parsing to remote_transport.main so --host/--port are not
    # decorative: Docker/operator command-line arguments override env defaults.
    return _remote_transport_main(_DISPATCH, health=_health)


if __name__ == "__main__":
    raise SystemExit(main())
