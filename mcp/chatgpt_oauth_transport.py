from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Callable, Mapping

from mcp import remote_transport as base
from mcp.github_oauth import (
    GitHubOAuthForbidden,
    GitHubOAuthInvalid,
    GitHubOAuthUnavailable,
    GitHubOAuthVerifier,
)


_VERIFIER_LOCK = threading.RLock()
_VERIFIERS: dict[tuple[tuple[str, ...], str], GitHubOAuthVerifier] = {}
_OAUTH_SCOPES = ("read:user", "offline_access")
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_STATE_TTL_SECONDS = 10 * 60
_OAUTH_TOKEN_PREFIX = "cbi_oauth_v1"
_DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 8 * 60 * 60


def chatgpt_oauth_security_schemes() -> list[dict[str, Any]]:
    """Return a fresh MCP tool-level OAuth declaration for ChatGPT clients."""

    return [{"type": "oauth2", "scopes": list(_OAUTH_SCOPES)}]


def decorate_tools_list_for_chatgpt(value: Any) -> Any:
    """Add tool-level OAuth metadata on the remote ChatGPT transport only.

    The compatibility stdio/tunnel descriptor stays conservative because older
    relays can reject richer descriptor fields. The direct remote transport,
    however, should advertise OAuth explicitly on every tool and mirror the
    declaration in _meta.securitySchemes for older ChatGPT clients.
    """

    if not isinstance(value, dict) or not isinstance(value.get("tools"), list):
        return value
    result = dict(value)
    tools: list[Any] = []
    for raw_tool in value["tools"]:
        if not isinstance(raw_tool, dict):
            tools.append(raw_tool)
            continue
        tool = dict(raw_tool)
        tool["securitySchemes"] = chatgpt_oauth_security_schemes()
        raw_meta = raw_tool.get("_meta")
        meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
        meta["securitySchemes"] = chatgpt_oauth_security_schemes()
        tool["_meta"] = meta
        tools.append(tool)
    result["tools"] = tools
    return result


def _shared_github_verifier(logins: tuple[str, ...], api_url: str) -> GitHubOAuthVerifier:
    normalized = tuple(sorted({value.strip().lower() for value in logins if value.strip()}))
    key = (normalized, api_url)
    with _VERIFIER_LOCK:
        verifier = _VERIFIERS.get(key)
        if verifier is None:
            verifier = GitHubOAuthVerifier(allowed_logins=normalized, api_url=api_url)
            _VERIFIERS[key] = verifier
        return verifier


def _public_base_url() -> str:
    raw = str(
        os.environ.get("CBI_REMOTE_PUBLIC_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "https://cbi-v61-preview.onrender.com"
    ).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise RuntimeError("CBI_REMOTE_PUBLIC_BASE_URL must be an absolute HTTP(S) origin")
    return raw


def _expected_resource(public_base: str) -> str:
    return f"{public_base}/mcp"


def _validated_resource(raw: str, public_base: str) -> str:
    value = str(raw or "").strip()
    expected = _expected_resource(public_base)
    if value != expected:
        raise ValueError(f"resource must equal {expected}")
    return expected


def _protected_resource_metadata(public_base: str) -> dict[str, Any]:
    return {
        "resource": _expected_resource(public_base),
        "authorization_servers": [public_base],
        "scopes_supported": list(_OAUTH_SCOPES),
        "bearer_methods_supported": ["header"],
        "code_challenge_methods_supported": ["S256"],
        "resource_name": "Customs Buyer Intelligence v6.1",
    }


def _authorization_server_metadata(public_base: str) -> dict[str, Any]:
    return {
        "issuer": public_base,
        "authorization_endpoint": f"{public_base}/oauth/authorize",
        "token_endpoint": f"{public_base}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "scopes_supported": list(_OAUTH_SCOPES),
        "authorization_response_iss_parameter_supported": True,
    }


def _oauth_state_key() -> bytes:
    value = str(os.environ.get("CBI_REMOTE_BEARER_TOKEN") or "").encode("utf-8")
    if len(value) < 32:
        raise RuntimeError("CBI_REMOTE_BEARER_TOKEN must be set for OAuth state signing")
    return value


def _pack_resource_token(
    *,
    kind: str,
    github_token: str,
    resource: str,
    expires_in: int,
    now: int | None = None,
) -> str:
    if kind not in {"access", "refresh"}:
        raise ValueError("unsupported OAuth token kind")
    token = str(github_token or "").strip()
    if not token:
        raise ValueError("GitHub OAuth token is missing")
    ttl = int(expires_in)
    if ttl <= 0:
        raise ValueError("OAuth token expiry must be positive")
    issued = int(time.time() if now is None else now)
    payload = {
        "v": 1,
        "kind": kind,
        "resource": str(resource),
        "github_token": token,
        "iat": issued,
        "exp": issued + ttl,
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_oauth_state_key(), b"cbi-oauth-token-v1\x00" + raw, hashlib.sha256).digest()
    return f"{_OAUTH_TOKEN_PREFIX}.{_b64url_encode(raw)}.{_b64url_encode(signature)}"


def _unpack_resource_token(
    token: str,
    *,
    kind: str,
    resource: str,
    now: int | None = None,
) -> str:
    supplied = str(token or "").strip()
    try:
        prefix, raw_part, sig_part = supplied.split(".", 2)
        if prefix != _OAUTH_TOKEN_PREFIX:
            raise ValueError("invalid OAuth token prefix")
        raw = _b64url_decode(raw_part)
        signature = _b64url_decode(sig_part)
    except Exception as exc:
        raise ValueError("invalid CBI OAuth token") from exc
    expected = hmac.new(_oauth_state_key(), b"cbi-oauth-token-v1\x00" + raw, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid CBI OAuth token signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid CBI OAuth token payload") from exc
    if int(payload.get("v") or 0) != 1:
        raise ValueError("unsupported CBI OAuth token version")
    if str(payload.get("kind") or "") != kind:
        raise ValueError("CBI OAuth token kind mismatch")
    if str(payload.get("resource") or "") != resource:
        raise ValueError("CBI OAuth token resource mismatch")
    issued = int(payload.get("iat") or 0)
    expires = int(payload.get("exp") or 0)
    current = int(time.time() if now is None else now)
    if issued <= 0 or expires <= issued or current < issued or current >= expires:
        raise ValueError("expired CBI OAuth token")
    github_token = str(payload.get("github_token") or "").strip()
    if not github_token:
        raise ValueError("CBI OAuth token is missing GitHub credential")
    return github_token


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


def _pack_oauth_state(
    *,
    client_state: str,
    redirect_uri: str,
    resource: str,
    now: int | None = None,
) -> str:
    payload = {
        "state": client_state,
        "redirect_uri": redirect_uri,
        "resource": resource,
        "iat": int(time.time() if now is None else now),
        "nonce": secrets.token_urlsafe(18),
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_oauth_state_key(), raw, hashlib.sha256).digest()
    return f"{_b64url_encode(raw)}.{_b64url_encode(signature)}"


def _unpack_oauth_state(token: str, *, now: int | None = None) -> dict[str, Any]:
    try:
        raw_part, sig_part = token.split(".", 1)
        raw = _b64url_decode(raw_part)
        supplied = _b64url_decode(sig_part)
    except Exception as exc:
        raise ValueError("invalid OAuth state") from exc
    expected = hmac.new(_oauth_state_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("invalid OAuth state signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid OAuth state payload") from exc
    issued = int(payload.get("iat") or 0)
    current = int(time.time() if now is None else now)
    if issued <= 0 or current < issued or current - issued > _STATE_TTL_SECONDS:
        raise ValueError("expired OAuth state")
    redirect_uri = str(payload.get("redirect_uri") or "")
    if not _is_chatgpt_redirect_uri(redirect_uri):
        raise ValueError("OAuth redirect URI is not allowed")
    if not str(payload.get("state") or ""):
        raise ValueError("OAuth client state is missing")
    if not str(payload.get("resource") or ""):
        raise ValueError("OAuth resource is missing")
    return payload


def _is_chatgpt_redirect_uri(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(value)
    except Exception:
        return False
    path_allowed = (
        parsed.path.startswith("/connector/oauth/")
        or parsed.path == "/connector_platform_oauth_redirect"
    )
    return (
        parsed.scheme == "https"
        and parsed.hostname == "chatgpt.com"
        and path_allowed
        and not parsed.fragment
    )


def _validated_scope(raw: str) -> str:
    requested = [value for value in raw.replace(",", " ").split() if value]
    if not requested:
        requested = list(_OAUTH_SCOPES)
    unsupported = sorted(set(requested) - set(_OAUTH_SCOPES))
    if unsupported:
        raise ValueError(f"unsupported OAuth scope(s): {', '.join(unsupported)}")
    ordered = [scope for scope in _OAUTH_SCOPES if scope in requested]
    return " ".join(ordered)


@dataclass(frozen=True)
class ChatGPTRemoteAuthConfig:
    mode: str
    bearer_token: str = ""
    allowed_origins: tuple[str, ...] = ()
    github_allowed_logins: tuple[str, ...] = ()
    github_api_url: str = "https://api.github.com/user"

    @classmethod
    def from_env(cls) -> "ChatGPTRemoteAuthConfig":
        mode = str(os.environ.get("CBI_REMOTE_AUTH_MODE") or "bearer").strip().lower()
        if mode not in {"bearer", "none", "mixed", "github_oauth"}:
            raise RuntimeError("CBI_REMOTE_AUTH_MODE must be bearer, mixed, github_oauth, or none")

        token = str(os.environ.get("CBI_REMOTE_BEARER_TOKEN") or "").strip()
        if mode in {"bearer", "mixed", "github_oauth"} and len(token) < 32:
            raise RuntimeError(
                "CBI_REMOTE_BEARER_TOKEN must contain at least 32 characters for static bearer or OAuth signing"
            )

        origins = tuple(
            value.strip()
            for value in str(os.environ.get("CBI_REMOTE_ALLOWED_ORIGINS") or "").split(",")
            if value.strip()
        )
        logins = tuple(
            value.strip()
            for value in str(os.environ.get("CBI_REMOTE_GITHUB_ALLOWED_LOGINS") or "").split(",")
            if value.strip()
        )
        if mode in {"mixed", "github_oauth"} and not logins:
            raise RuntimeError(
                "CBI_REMOTE_GITHUB_ALLOWED_LOGINS is required when GitHub OAuth auth is enabled"
            )
        api_url = str(os.environ.get("CBI_REMOTE_GITHUB_API_URL") or "https://api.github.com/user").strip()
        return cls(
            mode=mode,
            bearer_token=token,
            allowed_origins=origins,
            github_allowed_logins=logins,
            github_api_url=api_url,
        )

    def _verify_github_token(self, token: str) -> str:
        verifier = _shared_github_verifier(self.github_allowed_logins, self.github_api_url)
        try:
            return verifier.verify(token)
        except GitHubOAuthInvalid as exc:
            raise base.RemoteTransportError(str(exc), http_status=401, rpc_code=-32001) from exc
        except GitHubOAuthForbidden as exc:
            raise base.RemoteTransportError(str(exc), http_status=403, rpc_code=-32001) from exc
        except GitHubOAuthUnavailable as exc:
            raise base.RemoteTransportError(str(exc), http_status=503, rpc_code=-32003) from exc

    def authorize(self, headers: Mapping[str, str]) -> None:
        origin = str(headers.get("Origin") or headers.get("origin") or "").strip()
        if origin and self.allowed_origins and origin not in self.allowed_origins:
            raise base.RemoteTransportError("Origin not allowed", http_status=403, rpc_code=-32001)
        if self.mode == "none":
            return

        authorization = str(headers.get("Authorization") or headers.get("authorization") or "")
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise base.RemoteTransportError("Bearer authentication required", http_status=401, rpc_code=-32001)
        supplied = authorization[len(prefix):].strip()
        if not supplied:
            raise base.RemoteTransportError("Bearer authentication required", http_status=401, rpc_code=-32001)

        # Preserve the existing private admin bearer exactly. OAuth access
        # tokens are resource-bound CBI wrappers around the upstream GitHub
        # credential. Raw GitHub OAuth tokens remain accepted as a compatibility
        # fallback only for an explicitly configured GitHub allowlist.
        if self.mode in {"bearer", "mixed"} and hmac.compare_digest(supplied, self.bearer_token):
            return
        if self.mode == "bearer" and not self.github_allowed_logins:
            raise base.RemoteTransportError("Invalid bearer credential", http_status=401, rpc_code=-32001)

        github_token = supplied
        if supplied.startswith(f"{_OAUTH_TOKEN_PREFIX}."):
            try:
                github_token = _unpack_resource_token(
                    supplied,
                    kind="access",
                    resource=_expected_resource(_public_base_url()),
                )
            except ValueError as exc:
                raise base.RemoteTransportError(str(exc), http_status=401, rpc_code=-32001) from exc
        self._verify_github_token(github_token)


class ChatGPTOAuthRequestHandler(base.RemoteMcpRequestHandler):
    @property
    def public_base(self) -> str:
        return self.server.public_base  # type: ignore[attr-defined]

    def _send_json(
        self,
        status: int,
        value: Any,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        headers = dict(extra_headers or {})
        if int(status) == HTTPStatus.UNAUTHORIZED and headers.get("WWW-Authenticate") == "Bearer":
            metadata_url = f"{self.public_base}/.well-known/oauth-protected-resource/mcp"
            headers["WWW-Authenticate"] = (
                f'Bearer resource_metadata="{metadata_url}", scope="{" ".join(_OAUTH_SCOPES)}"'
            )
        super()._send_json(status, value, extra_headers=headers)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _query(self) -> dict[str, str]:
        parsed = urllib.parse.urlsplit(self.path)
        return {key: values[-1] for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if path in {
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        }:
            self._send_json(HTTPStatus.OK, _protected_resource_metadata(self.public_base))
            return
        if path == "/.well-known/oauth-authorization-server":
            self._send_json(HTTPStatus.OK, _authorization_server_metadata(self.public_base))
            return
        if path == "/oauth/authorize":
            try:
                query = self._query()
                if query.get("response_type") != "code":
                    raise ValueError("response_type must be code")
                client_id = str(query.get("client_id") or "").strip()
                redirect_uri = str(query.get("redirect_uri") or "").strip()
                client_state = str(query.get("state") or "").strip()
                if not client_id:
                    raise ValueError("client_id is required")
                if not _is_chatgpt_redirect_uri(redirect_uri):
                    raise ValueError("redirect_uri must be a ChatGPT connector OAuth callback")
                if not client_state:
                    raise ValueError("state is required")
                scope = _validated_scope(str(query.get("scope") or ""))
                resource = _validated_resource(str(query.get("resource") or ""), self.public_base)
                challenge = str(query.get("code_challenge") or "").strip()
                challenge_method = str(query.get("code_challenge_method") or "").strip()
                if challenge and challenge_method != "S256":
                    raise ValueError("PKCE code_challenge_method must be S256")
                if challenge_method and not challenge:
                    raise ValueError("code_challenge is required when code_challenge_method is present")

                proxy_state = _pack_oauth_state(
                    client_state=client_state,
                    redirect_uri=redirect_uri,
                    resource=resource,
                )
                github_query = {
                    "client_id": client_id,
                    "redirect_uri": f"{self.public_base}/oauth/callback",
                    "scope": scope,
                    "state": proxy_state,
                }
                if challenge:
                    github_query["code_challenge"] = challenge
                    github_query["code_challenge_method"] = "S256"
                if str(query.get("prompt") or "") == "select_account":
                    github_query["prompt"] = "select_account"
                self._redirect(f"{_GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(github_query)}")
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "error_description": str(exc)})
            return
        if path == "/oauth/callback":
            try:
                query = self._query()
                payload = _unpack_oauth_state(str(query.get("state") or ""))
                _validated_resource(str(payload.get("resource") or ""), self.public_base)
                response = {
                    "state": str(payload["state"]),
                    "iss": self.public_base,
                }
                if query.get("error"):
                    response["error"] = str(query.get("error") or "access_denied")
                    if query.get("error_description"):
                        response["error_description"] = str(query.get("error_description") or "")
                else:
                    code = str(query.get("code") or "").strip()
                    if not code:
                        raise ValueError("GitHub authorization code is missing")
                    response["code"] = code
                separator = "&" if "?" in str(payload["redirect_uri"]) else "?"
                self._redirect(
                    f"{payload['redirect_uri']}{separator}{urllib.parse.urlencode(response)}"
                )
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "error_description": str(exc)})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self._path() != "/oauth/token":
            super().do_POST()
            return
        try:
            length = int(str(self.headers.get("Content-Length") or "0"))
            if length <= 0 or length > 65536:
                raise ValueError("invalid token request body size")
            content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/x-www-form-urlencoded":
                raise ValueError("token endpoint requires application/x-www-form-urlencoded")
            raw = self.rfile.read(length).decode("utf-8")
            values = {
                key: rows[-1]
                for key, rows in urllib.parse.parse_qs(raw, keep_blank_values=True).items()
            }
            grant_type = str(values.get("grant_type") or "authorization_code")
            if grant_type not in {"authorization_code", "refresh_token"}:
                raise ValueError("unsupported grant_type")
            resource = _validated_resource(str(values.get("resource") or ""), self.public_base)
            allowed = {
                "client_id",
                "client_secret",
                "code",
                "code_verifier",
                "grant_type",
            }
            upstream = {key: value for key, value in values.items() if key in allowed and value != ""}
            upstream["grant_type"] = grant_type
            if not upstream.get("client_id") or not upstream.get("client_secret"):
                raise ValueError("client_id and client_secret are required")
            if grant_type == "authorization_code":
                if not upstream.get("code"):
                    raise ValueError("authorization code is required")
                upstream["redirect_uri"] = f"{self.public_base}/oauth/callback"
            else:
                wrapped_refresh = str(values.get("refresh_token") or "").strip()
                if not wrapped_refresh:
                    raise ValueError("refresh_token is required")
                upstream["refresh_token"] = _unpack_resource_token(
                    wrapped_refresh,
                    kind="refresh",
                    resource=resource,
                )

            request = urllib.request.Request(
                _GITHUB_TOKEN_URL,
                data=urllib.parse.urlencode(upstream).encode("utf-8"),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "CBI-v6.1-ChatGPT-OAuth",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    status = int(response.status)
                    body = response.read()
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                body = exc.read()
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = {"error": "server_error", "error_description": "GitHub token endpoint returned invalid JSON"}
                status = HTTPStatus.BAD_GATEWAY

            if 200 <= status < 300 and isinstance(payload, dict) and payload.get("access_token"):
                access_token = str(payload.get("access_token") or "").strip()
                auth = self.app._auth  # type: ignore[attr-defined]
                if not isinstance(auth, ChatGPTRemoteAuthConfig):
                    raise RuntimeError("unexpected remote auth configuration")
                auth._verify_github_token(access_token)
                access_ttl = int(payload.get("expires_in") or _DEFAULT_ACCESS_TOKEN_TTL_SECONDS)
                wrapped: dict[str, Any] = dict(payload)
                wrapped["access_token"] = _pack_resource_token(
                    kind="access",
                    github_token=access_token,
                    resource=resource,
                    expires_in=access_ttl,
                )
                wrapped["expires_in"] = access_ttl
                upstream_refresh = str(payload.get("refresh_token") or "").strip()
                if upstream_refresh:
                    refresh_ttl = int(payload.get("refresh_token_expires_in") or 180 * 24 * 60 * 60)
                    wrapped["refresh_token"] = _pack_resource_token(
                        kind="refresh",
                        github_token=upstream_refresh,
                        resource=resource,
                        expires_in=refresh_ttl,
                    )
                    wrapped["refresh_token_expires_in"] = refresh_ttl
                payload = wrapped
            self._send_json(status, payload)
        except base.RemoteTransportError as exc:
            oauth_error = "temporarily_unavailable" if exc.http_status == 503 else "invalid_grant"
            self._send_json(
                exc.http_status,
                {"error": oauth_error, "error_description": str(exc)},
            )
        except (UnicodeDecodeError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "error_description": str(exc)},
            )


def serve(
    dispatch: Callable[[str, dict[str, Any]], Any],
    *,
    health: Callable[[], dict[str, Any]] | None = None,
    host: str | None = None,
    port: int | None = None,
) -> int:
    auth = ChatGPTRemoteAuthConfig.from_env()
    public_base = _public_base_url()
    bind_host = host or str(os.environ.get("CBI_REMOTE_HOST") or "127.0.0.1")
    bind_port = base._resolved_port(port)
    max_body = int(os.environ.get("CBI_REMOTE_MAX_BODY_BYTES") or base.DEFAULT_MAX_BODY_BYTES)
    app = base.RemoteMcpApplication(dispatch, auth=auth, health=health, max_body_bytes=max_body)
    server = base._ReusableThreadingHTTPServer((bind_host, bind_port), ChatGPTOAuthRequestHandler)
    server.app = app  # type: ignore[attr-defined]
    server.public_base = public_base  # type: ignore[attr-defined]
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(
    dispatch: Callable[[str, dict[str, Any]], Any],
    health: Callable[[], dict[str, Any]] | None = None,
) -> int:
    args = base._parser().parse_args()
    return serve(dispatch, health=health, host=args.host, port=args.port)
