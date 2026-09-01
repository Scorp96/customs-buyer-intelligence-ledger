from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from mcp import remote_transport as base
from mcp.github_oauth import (
    GitHubOAuthForbidden,
    GitHubOAuthInvalid,
    GitHubOAuthUnavailable,
    GitHubOAuthVerifier,
)


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
        if mode in {"bearer", "mixed"} and len(token) < 32:
            raise RuntimeError(
                "CBI_REMOTE_BEARER_TOKEN must contain at least 32 characters when static bearer auth is enabled"
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

        # Preserve the existing private admin bearer exactly. When a GitHub
        # allowlist is configured, a non-matching bearer can additionally be a
        # ChatGPT-acquired GitHub OAuth token. The fallback remains fail-closed
        # to the explicit GitHub login allowlist.
        if self.mode in {"bearer", "mixed"} and hmac.compare_digest(supplied, self.bearer_token):
            return
        if self.mode == "bearer" and not self.github_allowed_logins:
            raise base.RemoteTransportError("Invalid bearer credential", http_status=401, rpc_code=-32001)

        verifier = GitHubOAuthVerifier(
            allowed_logins=self.github_allowed_logins,
            api_url=self.github_api_url,
        )
        try:
            verifier.verify(supplied)
        except GitHubOAuthInvalid as exc:
            raise base.RemoteTransportError(str(exc), http_status=401, rpc_code=-32001) from exc
        except GitHubOAuthForbidden as exc:
            raise base.RemoteTransportError(str(exc), http_status=403, rpc_code=-32001) from exc
        except GitHubOAuthUnavailable as exc:
            raise base.RemoteTransportError(str(exc), http_status=503, rpc_code=-32003) from exc


def serve(
    dispatch: Callable[[str, dict[str, Any]], Any],
    *,
    health: Callable[[], dict[str, Any]] | None = None,
    host: str | None = None,
    port: int | None = None,
) -> int:
    auth = ChatGPTRemoteAuthConfig.from_env()
    bind_host = host or str(os.environ.get("CBI_REMOTE_HOST") or "127.0.0.1")
    bind_port = base._resolved_port(port)
    max_body = int(os.environ.get("CBI_REMOTE_MAX_BODY_BYTES") or base.DEFAULT_MAX_BODY_BYTES)
    app = base.RemoteMcpApplication(dispatch, auth=auth, health=health, max_body_bytes=max_body)
    server = base._ReusableThreadingHTTPServer((bind_host, bind_port), base.RemoteMcpRequestHandler)
    server.app = app  # type: ignore[attr-defined]
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
