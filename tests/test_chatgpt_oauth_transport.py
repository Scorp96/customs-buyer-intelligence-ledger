from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest import mock

from mcp import chatgpt_oauth_transport, remote_transport
from mcp.chatgpt_oauth_transport import (
    ChatGPTRemoteAuthConfig,
    _authorization_server_metadata,
    _is_chatgpt_redirect_uri,
    _pack_oauth_state,
    _protected_resource_metadata,
    _public_base_url,
    _unpack_oauth_state,
    _validated_scope,
)
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

    def test_bearer_mode_accepts_allowlisted_github_oauth_fallback(self) -> None:
        auth = ChatGPTRemoteAuthConfig(
            mode="bearer",
            bearer_token="a" * 48,
            github_allowed_logins=("Scorp96",),
        )
        with mock.patch(
            "mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify",
            return_value="Scorp96",
        ) as verify:
            auth.authorize({"Authorization": "Bearer gho_test_oauth_token"})
            verify.assert_called_once_with("gho_test_oauth_token")

    def test_bearer_mode_without_github_allowlist_rejects_fallback(self) -> None:
        auth = ChatGPTRemoteAuthConfig(mode="bearer", bearer_token="a" * 48)
        with mock.patch("mcp.chatgpt_oauth_transport.GitHubOAuthVerifier.verify") as verify:
            with self.assertRaises(remote_transport.RemoteTransportError) as ctx:
                auth.authorize({"Authorization": "Bearer gho_test_oauth_token"})
        self.assertEqual(401, ctx.exception.http_status)
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

    def test_from_env_requires_allowlist_for_explicit_github_modes(self) -> None:
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

    def test_from_env_accepts_render_bearer_with_github_allowlist(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CBI_REMOTE_AUTH_MODE": "bearer",
                "CBI_REMOTE_BEARER_TOKEN": "a" * 48,
                "CBI_REMOTE_GITHUB_ALLOWED_LOGINS": "Scorp96",
            },
            clear=True,
        ):
            auth = ChatGPTRemoteAuthConfig.from_env()
        self.assertEqual("bearer", auth.mode)
        self.assertEqual(("Scorp96",), auth.github_allowed_logins)

    def test_mcp_oauth_metadata_is_complete_for_chatgpt(self) -> None:
        base_url = "https://cbi.example"
        protected = _protected_resource_metadata(base_url)
        authorization = _authorization_server_metadata(base_url)
        self.assertEqual("https://cbi.example/mcp", protected["resource"])
        self.assertEqual([base_url], protected["authorization_servers"])
        self.assertEqual(["read:user", "offline_access"], protected["scopes_supported"])
        self.assertEqual(base_url, authorization["issuer"])
        self.assertEqual("https://cbi.example/oauth/authorize", authorization["authorization_endpoint"])
        self.assertEqual("https://cbi.example/oauth/token", authorization["token_endpoint"])
        self.assertIn("refresh_token", authorization["grant_types_supported"])
        self.assertEqual(["S256"], authorization["code_challenge_methods_supported"])
        self.assertEqual(["client_secret_post"], authorization["token_endpoint_auth_methods_supported"])
        self.assertTrue(authorization["authorization_response_iss_parameter_supported"])

    def test_oauth_state_binds_chatgpt_redirect_and_expires(self) -> None:
        with mock.patch.dict(os.environ, {"CBI_REMOTE_BEARER_TOKEN": "k" * 48}, clear=False):
            token = _pack_oauth_state(
                client_state="chatgpt-state",
                redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
                now=1000,
            )
            payload = _unpack_oauth_state(token, now=1001)
            self.assertEqual("chatgpt-state", payload["state"])
            self.assertEqual(
                "https://chatgpt.com/connector_platform_oauth_redirect",
                payload["redirect_uri"],
            )
            with self.assertRaises(ValueError):
                _unpack_oauth_state(token + "x", now=1001)
            with self.assertRaises(ValueError):
                _unpack_oauth_state(token, now=2000)

    def test_oauth_redirect_and_scope_are_fail_closed(self) -> None:
        self.assertTrue(_is_chatgpt_redirect_uri("https://chatgpt.com/connector/oauth/abc"))
        self.assertTrue(_is_chatgpt_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect"))
        self.assertFalse(_is_chatgpt_redirect_uri("https://evil.example/connector/oauth/abc"))
        self.assertFalse(_is_chatgpt_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect/evil"))
        self.assertEqual("read:user offline_access", _validated_scope("offline_access read:user"))
        with self.assertRaises(ValueError):
            _validated_scope("repo")

    def test_public_base_url_can_be_pinned_for_render(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CBI_REMOTE_PUBLIC_BASE_URL": "https://cbi-v61-preview.onrender.com/"},
            clear=True,
        ):
            self.assertEqual("https://cbi-v61-preview.onrender.com", _public_base_url())

    def test_main_forwards_diagnostic_hook_to_serve(self) -> None:
        dispatch = mock.Mock(name="dispatch")
        health = mock.Mock(name="health")
        callback = mock.Mock(name="diagnostic_export")
        token = "S" * 64
        parser = mock.Mock()
        parser.parse_args.return_value = SimpleNamespace(host="127.0.0.1", port=18787)
        with (
            mock.patch.object(remote_transport, "_parser", return_value=parser),
            mock.patch.object(chatgpt_oauth_transport, "serve", return_value=17) as serve_mock,
        ):
            result = chatgpt_oauth_transport.main(
                dispatch,
                health=health,
                diagnostic_export=callback,
                diagnostic_static_bearer=token,
            )
        self.assertEqual(result, 17)
        serve_mock.assert_called_once_with(
            dispatch,
            health=health,
            host="127.0.0.1",
            port=18787,
            diagnostic_export=callback,
            diagnostic_static_bearer=token,
        )


if __name__ == "__main__":
    unittest.main()
