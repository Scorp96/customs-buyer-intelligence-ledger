from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
}
_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
)


@dataclass(frozen=True)
class PublicNetworkDecision:
    allowed: bool
    reason: str | None
    host: str
    resolved_addresses: tuple[str, ...] = ()


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def check_public_host(host: str, *, resolve_dns: bool = True) -> PublicNetworkDecision:
    normalized = str(host or "").strip().rstrip(".").lower()
    if not normalized:
        return PublicNetworkDecision(False, "missing_host", normalized)

    if normalized in _BLOCKED_HOSTS or any(
        normalized.endswith(suffix) for suffix in _BLOCKED_SUFFIXES
    ):
        return PublicNetworkDecision(False, "blocked_hostname", normalized)

    literal = _literal_ip(normalized)
    if literal is not None:
        if not literal.is_global:
            return PublicNetworkDecision(
                False,
                "non_public_ip",
                normalized,
                (str(literal),),
            )
        return PublicNetworkDecision(True, None, normalized, (str(literal),))

    if not resolve_dns:
        return PublicNetworkDecision(True, None, normalized)

    try:
        rows = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        return PublicNetworkDecision(
            False,
            f"dns_resolution_failed:{type(exc).__name__}",
            normalized,
        )

    addresses: set[str] = set()
    for row in rows:
        sockaddr = row[4]
        if sockaddr:
            addresses.add(str(sockaddr[0]))
    if not addresses:
        return PublicNetworkDecision(False, "dns_resolution_empty", normalized)

    for address in sorted(addresses):
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return PublicNetworkDecision(
                False,
                "dns_resolution_invalid_ip",
                normalized,
                tuple(sorted(addresses)),
            )
        if not parsed.is_global:
            return PublicNetworkDecision(
                False,
                f"dns_non_public_ip:{address}",
                normalized,
                tuple(sorted(addresses)),
            )

    return PublicNetworkDecision(
        True,
        None,
        normalized,
        tuple(sorted(addresses)),
    )


def validate_public_http_url(
    url: str,
    *,
    resolve_dns: bool = True,
    allow_url_credentials: bool = False,
) -> str:
    value = str(url or "").strip()
    split = urlsplit(value)
    if split.scheme.lower() not in {"http", "https"}:
        raise ValueError("URL must use http or https")
    if not allow_url_credentials and (split.username or split.password):
        raise ValueError("URL must not contain URL credentials")
    decision = check_public_host(split.hostname or "", resolve_dns=resolve_dns)
    if not decision.allowed:
        raise ValueError(
            f"URL is not an allowed public-network target: {decision.reason}"
        )
    return value


def is_public_http_url(
    url: str,
    *,
    resolve_dns: bool = True,
) -> tuple[bool, str | None]:
    try:
        validate_public_http_url(url, resolve_dns=resolve_dns)
    except ValueError as exc:
        return False, str(exc)
    return True, None


__all__ = [
    "PublicNetworkDecision",
    "check_public_host",
    "is_public_http_url",
    "validate_public_http_url",
]
