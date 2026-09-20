from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode

from mcp import remote_transport
from mcp.chatgpt_oauth_transport import (
    ChatGPTOAuthRequestHandler,
    ChatGPTRemoteAuthConfig,
    _OAUTH_TOKEN_PREFIX,
)


class _FakeGithubTokenResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "access_token": "gho_upstream_access",
                "expires_in": 28800,
                "refresh_token": "ghr_upstream_refresh",
                "refresh_token_expires_in": 15897600,
                "scope": "read:user",
                "token_type": "bearer",
            }
        ).encode("utf-8")


class ChatGPTOAuthHttpFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = mock.patch.dict(
            os.environ,
            {
                "CBI_REMOTE_BEARER_TOKEN": "k" * 48,
                "CBI_REMOTE_PUBLIC_BASE_URL": "https://cbi.example",
            },
            clear=False,
        )
        self.env.start()
        auth = ChatGPTRemoteAuthConfig(
            mode="bearer",
            bearer_token="k" * 48,
            github_allowed_logins=("Scorp96",),
        )
        app = remote_transport.RemoteMcpApplication(
            lambda method, params: {},
            auth=auth,
        )
        server = remote_transport._ReusableThreadingHTTPServer(
            ("127.0.0.1", 0),
            ChatGPTOAuthRequestHandler,
        )
        server.app = app
        server.public_base = "https://cbi.example"
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.host, self.port = server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.env.stop()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            return response.status, payload
        finally:
            conn.close()

    def test_oauth_metadata_advertises_exact_resource_and_pkce(self) -> None:
        status, payload = self._request("GET", "/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(200, status)
        self.assertEqual("https://cbi.example/mcp", payload["resource"])
        self.assertEqual(["S256"], payload["code_challenge_methods_supported"])

    def test_token_endpoint_requires_exact_resource(self) -> None:
        base = {
            "grant_type": "authorization_code",
            "client_id": "github-client",
            "client_secret": "github-secret",
            "code": "example-code",
            "code_verifier": "verifier",
        }
        body = urlencode(base)
        status, payload = self._request(
            "POST",
            "/oauth/token",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", payload["error"])

        body = urlencode({**base, "resource": "https://other.example/mcp"})
        status, payload = self._request(
            "POST",
            "/oauth/token",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", payload["error"])

    def test_successful_exchange_returns_resource_bound_cbi_tokens(self) -> None:
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": "github-client",
                "client_secret": "github-secret",
                "code": "example-code",
                "code_verifier": "verifier",
                "resource": "https://cbi.example/mcp",
            }
        )
        with mock.patch(
            "mcp.chatgpt_oauth_transport.urllib.request.urlopen",
            return_value=_FakeGithubTokenResponse(),
        ), mock.patch(
            "mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify",
            return_value="Scorp96",
        ):
            status, payload = self._request(
                "POST",
                "/oauth/token",
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        self.assertEqual(200, status)
        self.assertTrue(payload["access_token"].startswith(f"{_OAUTH_TOKEN_PREFIX}."))
        self.assertTrue(payload["refresh_token"].startswith(f"{_OAUTH_TOKEN_PREFIX}."))
        self.assertNotIn("gho_upstream_access", payload["access_token"])
        self.assertNotIn("ghr_upstream_refresh", payload["refresh_token"])
        self.assertEqual(28800, payload["expires_in"])
        self.assertEqual(15897600, payload["refresh_token_expires_in"])


if __name__ == "__main__":
    unittest.main()
