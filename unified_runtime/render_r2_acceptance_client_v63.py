from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_INITIALIZE_PROTOCOL_VERSION = "2025-06-18"
DEPLOYMENT_IDENTITY_SCHEMA = "cbi.remote-deployment-identity.v6.3"
REQUIRED_V63_MUTATIONS = (
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
)
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class RenderR2AcceptanceClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderR2AcceptanceClientConfig:
    base_url: str
    bearer_token: str = field(repr=False)
    expected_git_sha: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        raw_url = str(self.base_url or "").strip().rstrip("/")
        parsed = urllib.parse.urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RenderR2AcceptanceClientError("BASE_URL_MUST_BE_ABSOLUTE_HTTP_OR_HTTPS")
        if parsed.query or parsed.fragment:
            raise RenderR2AcceptanceClientError("BASE_URL_MUST_NOT_CONTAIN_QUERY_OR_FRAGMENT")
        token = str(self.bearer_token or "")
        if len(token) < 32:
            raise RenderR2AcceptanceClientError("BEARER_TOKEN_TOO_SHORT")
        sha = str(self.expected_git_sha or "").strip().lower()
        if not _GIT_SHA_RE.fullmatch(sha):
            raise RenderR2AcceptanceClientError("EXPECTED_GIT_SHA_INVALID")
        timeout = float(self.timeout_seconds)
        if timeout <= 0:
            raise RenderR2AcceptanceClientError("TIMEOUT_MUST_BE_POSITIVE")
        object.__setattr__(self, "base_url", raw_url)
        object.__setattr__(self, "expected_git_sha", sha)
        object.__setattr__(self, "timeout_seconds", timeout)


def _sensitive_key(key: str) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    exact = {
        "idempotency_key",
        "authorization",
        "bearer_token",
        "access_key",
        "access_key_id",
        "secret_access_key",
        "secret_key",
        "client_secret",
        "api_token",
        "oauth_token",
    }
    if normalized in exact:
        return True
    return any(
        marker in normalized
        for marker in (
            "idempotency_key",
            "bearer_token",
            "secret_access_key",
            "access_key_id",
            "authorization",
        )
    )


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if _sensitive_key(key):
                continue
            sanitized[key] = _sanitize(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


class RenderR2AcceptanceClient:
    def __init__(self, config: RenderR2AcceptanceClientConfig):
        if not isinstance(config, RenderR2AcceptanceClientConfig):
            raise TypeError("config must be RenderR2AcceptanceClientConfig")
        self.config = config
        self._next_request_id = 1
        self._deployment_pinned = False
        self._pinned_identity: dict[str, Any] | None = None

    def _url(self, path: str) -> str:
        return self.config.base_url + path

    def _decode_json_response(self, response: Any) -> Any:
        raw = response.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RenderR2AcceptanceClientError("REMOTE_RESPONSE_NOT_VALID_JSON") from exc

    def _open_json(self, request: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return self._decode_json_response(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                safe = _sanitize(payload)
                detail = json.dumps(safe, ensure_ascii=True, sort_keys=True)[:500]
            except Exception:
                detail = f"HTTP {exc.code}"
            raise RenderR2AcceptanceClientError(
                f"REMOTE_HTTP_ERROR:{int(exc.code)}:{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RenderR2AcceptanceClientError("REMOTE_CONNECTION_FAILED") from exc

    def _pin_health(self, health: dict[str, Any]) -> None:
        if str(health.get("status") or "").strip().lower() != "ok":
            raise RenderR2AcceptanceClientError("REMOTE_HEALTH_NOT_OK")
        identity = health.get("deployment_identity")
        if not isinstance(identity, dict):
            raise RenderR2AcceptanceClientError("DEPLOYMENT_IDENTITY_MISSING")
        if identity.get("schema") != DEPLOYMENT_IDENTITY_SCHEMA:
            raise RenderR2AcceptanceClientError("DEPLOYMENT_IDENTITY_SCHEMA_MISMATCH")
        observed = str(identity.get("git_sha") or "").strip().lower()
        if observed != self.config.expected_git_sha:
            raise RenderR2AcceptanceClientError("DEPLOYMENT_GIT_SHA_MISMATCH")
        if identity.get("git_sha_source") != "RENDER_GIT_COMMIT":
            raise RenderR2AcceptanceClientError("DEPLOYMENT_GIT_SHA_SOURCE_UNTRUSTED")
        if identity.get("acceptance_pin_required") is not True:
            raise RenderR2AcceptanceClientError("REMOTE_ACCEPTANCE_SHA_PIN_NOT_REQUIRED")
        if identity.get("object_store_mode") != "r2":
            raise RenderR2AcceptanceClientError("REMOTE_OBJECT_STORE_MODE_NOT_R2")
        self._pinned_identity = _sanitize(identity)
        self._deployment_pinned = True

    def read_health(self) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url("/healthz"),
            method="GET",
            headers={"Accept": "application/json"},
        )
        payload = self._open_json(request)
        if not isinstance(payload, dict):
            raise RenderR2AcceptanceClientError("REMOTE_HEALTH_NOT_OBJECT")
        self._pin_health(payload)
        return _sanitize(payload)

    def _ensure_deployment_pinned(self) -> None:
        if not self._deployment_pinned:
            self.read_health()

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_deployment_pinned()
        request_id = self._next_request_id
        self._next_request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": str(method),
                "params": dict(params or {}),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url("/mcp"),
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
            },
        )
        payload = self._open_json(request)
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise RenderR2AcceptanceClientError("REMOTE_JSONRPC_RESPONSE_INVALID")
        if payload.get("id") != request_id:
            raise RenderR2AcceptanceClientError("REMOTE_JSONRPC_ID_MISMATCH")
        if isinstance(payload.get("error"), dict):
            safe_error = _sanitize(payload["error"])
            detail = json.dumps(safe_error, ensure_ascii=True, sort_keys=True)[:500]
            raise RenderR2AcceptanceClientError(f"REMOTE_JSONRPC_ERROR:{detail}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RenderR2AcceptanceClientError("REMOTE_JSONRPC_RESULT_NOT_OBJECT")
        return _sanitize(result)

    def discover(self) -> dict[str, Any]:
        return self._rpc("server/discover", {})

    def initialize(self) -> dict[str, Any]:
        return self._rpc(
            "initialize",
            {
                "protocolVersion": LEGACY_INITIALIZE_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cbi-v63-render-r2-acceptance", "version": "1"},
            },
        )

    def list_tool_names(self) -> list[str]:
        result = self._rpc("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise RenderR2AcceptanceClientError("REMOTE_TOOLS_LIST_MISSING")
        names = sorted(
            {
                str(item.get("name") or "").strip()
                for item in tools
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
        )
        return names

    def required_v63_mutation_surface(self) -> dict[str, Any]:
        observed = self.list_tool_names()
        missing = sorted(set(REQUIRED_V63_MUTATIONS) - set(observed))
        if missing:
            raise RenderR2AcceptanceClientError(
                "REQUIRED_V63_MUTATION_SURFACE_MISSING:" + ",".join(missing)
            )
        identity = self._pinned_identity or {}
        return {
            "required_tools": list(REQUIRED_V63_MUTATIONS),
            "observed_tools": observed,
            "deployment_git_sha": identity.get("git_sha"),
            "protocol_version": MODERN_PROTOCOL_VERSION,
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._rpc(
            "tools/call",
            {"name": str(name), "arguments": dict(arguments)},
        )
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise RenderR2AcceptanceClientError("REMOTE_TOOL_STRUCTURED_CONTENT_MISSING")
        return _sanitize(structured)
