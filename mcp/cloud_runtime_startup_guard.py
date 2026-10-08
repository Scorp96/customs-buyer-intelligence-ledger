"""Fail-closed production-only controls for hosted CBI MCP startup.

Render sets RENDER=true at runtime. Paid persistent-disk deployments can
omit CBI_REQUIRE_EPHEMERAL_DURABILITY; the free ephemeral Blueprint sets it
explicitly. Do not inspect or expose secret values, only presence.
"""
from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlsplit

_R2_REQUIRED_FIELDS = (
    "CBI_OBJECT_STORE_ENDPOINT",
    "CBI_OBJECT_STORE_BUCKET",
    "CBI_OBJECT_STORE_ACCESS_KEY_ID",
    "CBI_OBJECT_STORE_SECRET_ACCESS_KEY",
)


def require_remote_environment_safety(env: Mapping[str, str] | None = None) -> None:
    """Reject unauthenticated hosted MCP and ephemeral state without R2/S3."""
    values = os.environ if env is None else env
    on_render = str(values.get("RENDER") or "").strip().lower() == "true"
    if not on_render:
        return

    auth_mode = str(values.get("CBI_REMOTE_AUTH_MODE") or "bearer").strip().lower()
    if auth_mode not in {"bearer", "mixed", "github_oauth"}:
        raise RuntimeError("RENDER_PUBLIC_MCP_AUTH_REQUIRED")

    # Local development may use HTTP loopback; a Render-hosted, public OAuth
    # issuer must never advertise a plaintext authority/credential endpoint.
    base_url = str(
        values.get("CBI_REMOTE_PUBLIC_BASE_URL")
        or values.get("RENDER_EXTERNAL_URL")
        or "https://cbi-v61-preview.onrender.com"
    ).strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("RENDER_PUBLIC_OAUTH_ORIGIN_HTTPS_REQUIRED")

    required = str(values.get("CBI_REQUIRE_EPHEMERAL_DURABILITY") or "").strip().lower()
    if required not in {"", "0", "1", "false", "true", "no", "yes", "off", "on"}:
        raise RuntimeError("CBI_REQUIRE_EPHEMERAL_DURABILITY_INVALID")
    if required not in {"1", "true", "yes", "on"}:
        return

    mode = str(values.get("CBI_OBJECT_STORE_MODE") or "").strip().lower()
    if mode not in {"r2", "s3"}:
        raise RuntimeError("RENDER_EPHEMERAL_OBJECT_STORE_REQUIRED")
    if not all(str(values.get(field) or "").strip() for field in _R2_REQUIRED_FIELDS):
        # Deliberately omit names and values from logs, public health or errors.
        raise RuntimeError("RENDER_EPHEMERAL_OBJECT_STORE_CONFIG_INCOMPLETE")


__all__ = ["require_remote_environment_safety"]
