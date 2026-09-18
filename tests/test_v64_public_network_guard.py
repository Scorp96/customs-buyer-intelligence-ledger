from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from unified_runtime.public_network_guard import (
    check_public_host,
    is_public_http_url,
    validate_public_http_url,
)


class PublicNetworkGuardTests(unittest.TestCase):
    def test_rejects_private_and_link_local_literals(self) -> None:
        for url in (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/",
            "http://[::1]/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_http_url(url)

    def test_rejects_local_internal_and_credentials(self) -> None:
        for url in (
            "http://localhost/",
            "http://service.internal/",
            "http://metadata.google.internal/",
            "https://user:pass@example.com/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_http_url(url)

    def test_dns_resolution_to_private_address_fails_closed(self) -> None:
        rows = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=rows):
            decision = check_public_host("example.com", resolve_dns=True)
            self.assertFalse(decision.allowed)
            self.assertIn("dns_non_public_ip", decision.reason or "")

    def test_dns_resolution_all_global_addresses_is_allowed(self) -> None:
        rows = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 0, 0, 0)),
        ]
        with patch("socket.getaddrinfo", return_value=rows):
            decision = check_public_host("example.com", resolve_dns=True)
        self.assertTrue(decision.allowed)
        self.assertEqual(
            set(decision.resolved_addresses),
            {"8.8.8.8", "2606:4700:4700::1111"},
        )

    def test_dns_failure_is_not_treated_as_public(self) -> None:
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("no dns")):
            allowed, reason = is_public_http_url(
                "https://does-not-resolve.invalid/",
                resolve_dns=True,
            )
        self.assertFalse(allowed)
        self.assertIn("dns_resolution_failed", reason or "")

    def test_non_http_schemes_are_rejected(self) -> None:
        for url in ("file:///tmp/test", "ftp://example.com/file", "data:text/plain,hello"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_http_url(url)


if __name__ == "__main__":
    unittest.main()
