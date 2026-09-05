#!/usr/bin/env python3
"""Dependency-free stateless HTTP transport for the production CBI MCP server.

The durable Runtime remains stateful on disk, but MCP transport sessions are not
required. This module supports both the current 2026-07-28 stateless lifecycle
(`server/discover`) and legacy initialize-capable clients on one `/mcp` endpoint.

It intentionally does not implement unsolicited server-to-client messages,
resource subscriptions, sampling, roots, or long-lived HTTP sessions. The CBI
server does not depend on those features; every tool invocation is a normal
request/response operation against append-only durable state.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")
SUPPORTED_PROTOCOL_VERSIONS = (MODERN_PROTOCOL_VERSION, *LEGACY_PROTOCOL_VERSIONS)
DEFAULT_MAX_BODY_BYTES = 8 * 1024 * 1024

JsonHandler = Callable[[str, dict[str, Any]], Any]
HealthHandler = Callable[[], dict[str, Any]]


class RemoteTransportError(Exception):
    """Transport-layer request rejection with an HTTP status and JSON-RPC code."""

    def __init__(self, message: str, *, http_status: int = 400, rpc_code: int = -32600):
        super().__init__(message)
        self.http_status = int(http_status)
        self.rpc_code = int(rpc_code)


def require_static_bearer(headers: Mapping[str, str], expected_token: str) -> None:
    """Authorize only the exact private static bearer; never OAuth-fallback."""
    authorization = str(headers.get("Authorization") or headers.get("authorization") or "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise RemoteTransportError(
            "Bearer authentication required", http_status=401, rpc_code=-32001
        )
    supplied = authorization[len(prefix):].strip()
    if not supplied:
        raise RemoteTransportError(
            "Bearer authentication required", http_status=401, rpc_code=-32001
        )
    expected = str(expected_token or "")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise RemoteTransportError(
            "Invalid bearer credential", http_status=401, rpc_code=-32001
        )


@dataclass(frozen=True)
class RemoteAuthConfig:
    mode: str
    bearer_token: str = ""
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "RemoteAuthConfig":
        mode = str(os.environ.get("CBI_REMOTE_AUTH_MODE") or "bearer").strip().lower()
        if mode not in {"bearer", "none"}:
            raise RuntimeError("CBI_REMOTE_AUTH_MODE must be bearer or none")
        token = str(os.environ.get("CBI_REMOTE_BEARER_TOKEN") or "").strip()
        if mode == "bearer" and len(token) < 32:
            raise RuntimeError(
                "CBI_REMOTE_BEARER_TOKEN must contain at least 32 characters when bearer auth is enabled"
            )
        origins = tuple(
            value.strip()
            for value in str(os.environ.get("CBI_REMOTE_ALLOWED_ORIGINS") or "").split(",")
            if value.strip()
        )
        return cls(mode=mode, bearer_token=token, allowed_origins=origins)

    def authorize(self, headers: Mapping[str, str]) -> None:
        origin = str(headers.get("Origin") or headers.get("origin") or "").strip()
        if origin and self.allowed_origins and origin not in self.allowed_origins:
            raise RemoteTransportError("Origin not allowed", http_status=403, rpc_code=-32001)
        if self.mode == "none":
            return
        authorization = str(headers.get("Authorization") or headers.get("authorization") or "")
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise RemoteTransportError("Bearer authentication required", http_status=401, rpc_code=-32001)
        supplied = authorization[len(prefix):].strip()
        if not supplied or not hmac.compare_digest(supplied, self.bearer_token):
            raise RemoteTransportError("Invalid bearer credential", http_status=401, rpc_code=-32001)


class RemoteMcpApplication:
    """Stateless HTTP facade over the existing dependency-free CBI dispatcher."""

    def __init__(
        self,
        dispatch: JsonHandler,
        *,
        auth: RemoteAuthConfig,
        health: HealthHandler | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ):
        self._dispatch = dispatch
        self._auth = auth
        self._health = health or (lambda: {"status": "ok"})
        self._max_body_bytes = max(1024, int(max_body_bytes))
        self._dispatch_lock = threading.RLock()

    @property
    def max_body_bytes(self) -> int:
        return self._max_body_bytes

    def health(self) -> dict[str, Any]:
        value = self._health()
        if not isinstance(value, dict):
            return {"status": "error"}
        return value

    @staticmethod
    def _error_payload(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": int(code), "message": str(message)}}

    @staticmethod
    def _response_payload(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _method_header(headers: Mapping[str, str]) -> str:
        return str(headers.get("Mcp-Method") or headers.get("mcp-method") or "").strip()

    @staticmethod
    def _name_header(headers: Mapping[str, str]) -> str:
        return str(headers.get("Mcp-Name") or headers.get("mcp-name") or "").strip()

    @staticmethod
    def _protocol_header(headers: Mapping[str, str]) -> str:
        return str(headers.get("MCP-Protocol-Version") or headers.get("mcp-protocol-version") or "").strip()

    def _validate_protocol_headers(self, request: dict[str, Any], headers: Mapping[str, str]) -> None:
        protocol = self._protocol_header(headers)
        if protocol and protocol not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RemoteTransportError(
                f"Unsupported MCP protocol version: {protocol}", http_status=400, rpc_code=-32022
            )
        method = str(request.get("method") or "")
        method_header = self._method_header(headers)
        if method_header and method_header != method:
            raise RemoteTransportError("Mcp-Method header/body mismatch", rpc_code=-32600)
        name_header = self._name_header(headers)
        if name_header and method == "tools/call":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            if str(params.get("name") or "") != name_header:
                raise RemoteTransportError("Mcp-Name header/body mismatch", rpc_code=-32600)

    def _discover(self) -> dict[str, Any]:
        legacy = self._dispatch(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "cbi-remote-discovery", "version": "1"},
            },
        )
        capabilities = dict(legacy.get("capabilities") or {}) if isinstance(legacy, dict) else {}
        server_info = dict(legacy.get("serverInfo") or {}) if isinstance(legacy, dict) else {}
        instructions = str(legacy.get("instructions") or "") if isinstance(legacy, dict) else ""
        return {
            "resultType": "complete",
            "supportedVersions": [MODERN_PROTOCOL_VERSION],
            "capabilities": capabilities,
            "_meta": {"io.modelcontextprotocol/serverInfo": server_info},
            "instructions": instructions,
            "ttlMs": 300000,
            "cacheScope": "private",
        }

    def dispatch_jsonrpc(self, request: Any, headers: Mapping[str, str]) -> tuple[int, dict[str, Any] | None]:
        self._auth.authorize(headers)
        if not isinstance(request, dict):
            raise RemoteTransportError("JSON-RPC object required", rpc_code=-32600)
        if request.get("jsonrpc") != "2.0":
            raise RemoteTransportError("jsonrpc must equal 2.0", rpc_code=-32600)
        self._validate_protocol_headers(request, headers)
        method = str(request.get("method") or "").strip()
        if not method:
            raise RemoteTransportError("method required", rpc_code=-32600)
        request_id = request.get("id")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        if "id" not in request:
            return HTTPStatus.ACCEPTED, None
        try:
            with self._dispatch_lock:
                result = self._discover() if method == "server/discover" else self._dispatch(method, params)
            return HTTPStatus.OK, self._response_payload(request_id, result)
        except RemoteTransportError:
            raise
        except Exception as exc:
            return HTTPStatus.OK, self._error_payload(request_id, -32602, str(exc))


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class RemoteMcpRequestHandler(BaseHTTPRequestHandler):
    server_version = "CBIRemoteMCP/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> RemoteMcpApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        super().log_message(format, *args)

    def _send_json(self, status: int, value: Any, *, extra_headers: Mapping[str, str] | None = None) -> None:
        body = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for key, val in extra_headers.items():
                self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(int(status))
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _path(self) -> str:
        return urlsplit(self.path).path

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if path in {"/healthz", "/readyz"}:
            try:
                self._send_json(HTTPStatus.OK, self.app.health())
            except Exception:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "error"})
            return
        if path == "/mcp":
            self._send_empty(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        self._send_empty(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        self._send_empty(HTTPStatus.METHOD_NOT_ALLOWED if self._path() == "/mcp" else HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self._path() != "/mcp":
            self._send_empty(HTTPStatus.NOT_FOUND)
            return
        try:
            length_text = str(self.headers.get("Content-Length") or "0")
            length = int(length_text)
            if length <= 0:
                raise RemoteTransportError("Request body required", http_status=400)
            if length > self.app.max_body_bytes:
                raise RemoteTransportError("Request body too large", http_status=413)
            content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise RemoteTransportError("Content-Type must be application/json", http_status=415)
            raw = self.rfile.read(length)
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RemoteTransportError("Invalid UTF-8 JSON body", rpc_code=-32700) from exc
            status, payload = self.app.dispatch_jsonrpc(request, self.headers)
            if payload is None:
                self._send_empty(status)
            else:
                response_headers: dict[str, str] = {}
                protocol = self.app._protocol_header(self.headers)
                if protocol:
                    response_headers["MCP-Protocol-Version"] = protocol
                self._send_json(status, payload, extra_headers=response_headers)
        except RemoteTransportError as exc:
            request_id = None
            try:
                request_id = request.get("id") if isinstance(request, dict) else None  # type: ignore[name-defined]
            except Exception:
                request_id = None
            self._send_json(
                exc.http_status,
                RemoteMcpApplication._error_payload(request_id, exc.rpc_code, str(exc)),
                extra_headers={"WWW-Authenticate": "Bearer"} if exc.http_status == 401 else None,
            )
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                RemoteMcpApplication._error_payload(None, -32603, "Internal server error"),
            )


def _resolved_port(port: int | None = None) -> int:
    """Resolve explicit CLI port, CBI override, platform PORT, then local default."""
    raw = port or os.environ.get("CBI_REMOTE_PORT") or os.environ.get("PORT") or "8787"
    value = int(raw)
    if value < 1 or value > 65535:
        raise RuntimeError("remote MCP port must be between 1 and 65535")
    return value


def serve(
    dispatch: JsonHandler,
    *,
    health: HealthHandler | None = None,
    host: str | None = None,
    port: int | None = None,
) -> int:
    auth = RemoteAuthConfig.from_env()
    bind_host = host or str(os.environ.get("CBI_REMOTE_HOST") or "127.0.0.1")
    bind_port = _resolved_port(port)
    max_body = int(os.environ.get("CBI_REMOTE_MAX_BODY_BYTES") or DEFAULT_MAX_BODY_BYTES)
    app = RemoteMcpApplication(dispatch, auth=auth, health=health, max_body_bytes=max_body)
    server = _ReusableThreadingHTTPServer((bind_host, bind_port), RemoteMcpRequestHandler)
    server.app = app  # type: ignore[attr-defined]
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a dependency-free stateless MCP HTTP endpoint")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser


def main(dispatch: JsonHandler, health: HealthHandler | None = None) -> int:
    args = _parser().parse_args()
    return serve(dispatch, health=health, host=args.host, port=args.port)
