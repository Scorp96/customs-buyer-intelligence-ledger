from __future__ import annotations

import os
import unittest
from unittest import mock

from mcp import remote_transport
from mcp.chatgpt_oauth_transport import ChatGPTRemoteAuthConfig
from mcp.github_oauth import GitHubOAuthForbidden, GitHubOAuthInvalid


class ChatGPTOAuthTransportTests(unittest.TestCase):
    def test_mixed_mode_preserves_static_admin_bearer(self) -> None:
        token = "a" * 48
        auth = ChatGPTRemoteAuthConfig(
            mode="mixed",
            bearer_token=token,
            github_allowed_logins=("Scorp96",),
        )
        with mock.patch("mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify") as verify:
            auth.authorize({"Authorization": f"Bearer {token}"})
            verify.assert_not_called()

    def test_mixed_mode_accepts_allowlisted_github_oauth(self) -> None:
        auth = ChatGPTRemoteAuthConfig(
            mode="mixed",
            bearer_token="a" * 48,
            github_allowed_logins=("Scorp96",),
        )
        with mock.patch(
            "mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify",
            return_value="Scorp96",
        ) as verify:
            auth.authorize({"Authorization": "Bearer gho_test_oauth_token"})
            verify.assert_called_once_with("gho_test_oauth_token")

    def test_github_oauth_wrong_identity_is_forbidden(self) -> None:
        auth = ChatGPTRemoteAuthConfig(
            mode="github_oauth",
            github_allowed_logins=("Scorp96",),
        )
        with mock.patch(
            "mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify",
            side_effect=GitHubOAuthForbidden("not allowed"),
        ):
            with self.assertRaises(remote_transport.RemoteTransportError) as ctx:
                auth.authorize({"Authorization": "Bearer gho_other"})
        self.assertEqual(403, ctx.exception.http_status)

    def test_invalid_github_token_is_unauthorized(self) -> None:
        auth = ChatGPTRemoteAuthConfig(
            mode="github_oauth",
            github_allowed_logins=("Scorp96",),
        )
        with mock.patch(
            "mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify",
            side_effect=GitHubOAuthInvalid("invalid"),
        ):
            with self.assertRaises(remote_transport.RemoteTransportError) as ctx:
                auth.authorize({"Authorization": "Bearer bad"})
        self.assertEqual(401, ctx.exception.http_status)

    def test_from_env_requires_allowlist_for_github_modes(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CBI_REMOTE_AUTH_MODE": "mixed",
                "CBI_REMOTE_BEARER_TOKEN": "a" * 48,
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ChatGPTRemoteAuthConfig.from_env()

    def test_from_env_accepts_render_mixed_configuration(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CBI_REMOTE_AUTH_MODE": "mixed",
                "CBI_REMOTE_BEARER_TOKEN": "a" * 48,
                "CBI_REMOTE_GITHUB_ALLOWED_LOGINS": "Scorp96",
            },
            clear=True,
        ):
            auth = ChatGPTRemoteAuthConfig.from_env()
        self.assertEqual("mixed", auth.mode)
        self.assertEqual(("Scorp96",), auth.github_allowed_logins)


if __name__ == "__main__":
    unittest.main()
