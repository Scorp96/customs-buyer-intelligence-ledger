#!/usr/bin/env python3
"""Render-specific bootstrap gate for CBI v6.1.

A brand-new Render persistent disk is intentionally *not* treated as a new empty
production Runtime. Until a validated migration bundle has been imported into
CBI_RENDER_LIVE_ROOT, this process exposes only a minimal health endpoint and
returns 503 for MCP traffic. After import, a restart binds the accepted production
remote server to the imported durable state.
"""

from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _live_root() -> Path:
    raw = str(os.environ.get("CBI_RENDER_LIVE_ROOT") or "/var/lib/cbi/live").strip()
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise RuntimeError("CBI_RENDER_LIVE_ROOT must be absolute")
    return root.resolve()


def _port() -> int:
    raw = os.environ.get("CBI_REMOTE_PORT") or os.environ.get("PORT") or "8787"
    value = int(raw)
    if value < 1 or value > 65535:
        raise RuntimeError("bootstrap port must be between 1 and 65535")
    return value


def _state(root: Path) -> str:
    if not root.exists():
        return "bootstrap"
    if not root.is_dir():
        return "invalid"
    entries = list(root.iterdir())
    if not entries:
        return "bootstrap"
    manifest = root / "export-manifest.json"
    sessions = root / "sessions"
    if manifest.is_file() and sessions.is_dir():
        return "live"
    return "invalid"


class BootstrapHandler(BaseHTTPRequestHandler):
    server_version = "CBIRenderBootstrap/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        super().log_message(format, *args)

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self._path() in {"/healthz", "/readyz"}:
            self._json(
                HTTPStatus.OK,
                {
                    "status": "bootstrap_required",
                    "service": "customs-buyer-intelligence",
                    "durable_state_loaded": False,
                    "mcp_enabled": False,
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self._path() == "/mcp":
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32004,
                        "message": "CBI durable state has not been imported; MCP is disabled",
                    },
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"status": "not_found"})


def _serve_bootstrap() -> int:
    host = str(os.environ.get("CBI_REMOTE_HOST") or "0.0.0.0")
    server = ThreadingHTTPServer((host, _port()), BootstrapHandler)
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main() -> int:
    live = _live_root()
    state = _state(live)
    if state == "invalid":
        raise RuntimeError(
            f"Render live root exists but is not a complete imported CBI bundle: {live}"
        )
    if state == "bootstrap":
        return _serve_bootstrap()

    expected_sessions = (live / "sessions").resolve()
    expected_backups = (live / "backups-v61").resolve()
    configured_sessions = Path(
        str(os.environ.get("CBI_SESSION_ROOT") or expected_sessions)
    ).expanduser().resolve()
    configured_backups = Path(
        str(os.environ.get("CBI_BACKUP_ROOT") or expected_backups)
    ).expanduser().resolve()
    if configured_sessions != expected_sessions:
        raise RuntimeError("CBI_SESSION_ROOT does not match imported Render live root")
    if configured_backups != expected_backups:
        raise RuntimeError("CBI_BACKUP_ROOT does not match imported Render live root")
    os.environ["CBI_SESSION_ROOT"] = str(expected_sessions)
    os.environ["CBI_BACKUP_ROOT"] = str(expected_backups)

    from mcp.server_v61_remote import main as production_remote_main

    return production_remote_main()


if __name__ == "__main__":
    raise SystemExit(main())
