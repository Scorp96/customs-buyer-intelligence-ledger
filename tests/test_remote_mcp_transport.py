from __future__ import annotations

import unittest

from mcp.remote_transport import (
    MODERN_PROTOCOL_VERSION,
    RemoteAuthConfig,
    RemoteMcpApplication,
    RemoteTransportError,
)


class RemoteMcpTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, dict]] = []

        def fake_dispatch(method: str, params: dict):
            self.calls.append((method, params))
            if method == "initialize":
                return {
                    "protocolVersion": params.get("protocolVersion") or "2025-06-18",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {"name": "cbi-test", "version": "6.1"},
                    "instructions": "test instructions",
                }
            if method == "tools/list":
                return {"tools": [{"name": "get_runtime_health", "inputSchema": {"type": "object"}}]}
            if method == "tools/call":
                return {
                    "content": [{"type": "text", "text": "OK"}],
                    "structuredContent": {"status": "PASS"},
                }
            if method == "ping":
                return {}
            raise ValueError("unsupported")

        self.dispatch = fake_dispatch

    def _app(self, mode: str = "none", token: str = "") -> RemoteMcpApplication:
        return RemoteMcpApplication(
            self.dispatch,
            auth=RemoteAuthConfig(mode=mode, bearer_token=token),
        )

    def test_modern_server_discover_uses_production_capabilities(self) -> None:
        app = self._app()
        status, payload = app.dispatch_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": "d1",
                "method": "server/discover",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
            {
                "MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
                "Mcp-Method": "server/discover",
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("complete", payload["result"]["resultType"])
        self.assertEqual([MODERN_PROTOCOL_VERSION], payload["result"]["supportedVersions"])
        self.assertIn("tools", payload["result"]["capabilities"])
        self.assertEqual("private", payload["result"]["cacheScope"])
        self.assertEqual("initialize", self.calls[0][0])

    def test_legacy_initialize_remains_supported(self) -> None:
        app = self._app()
        status, payload = app.dispatch_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            {},
        )
        self.assertEqual(200, status)
        self.assertEqual("2025-06-18", payload["result"]["protocolVersion"])

    def test_notifications_return_no_jsonrpc_payload(self) -> None:
        app = self._app()
        status, payload = app.dispatch_jsonrpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {},
        )
        self.assertEqual(202, status)
        self.assertIsNone(payload)
        self.assertEqual([], self.calls)

    def test_bearer_auth_is_fail_closed(self) -> None:
        token = "x" * 40
        app = self._app(mode="bearer", token=token)
        request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        with self.assertRaises(RemoteTransportError) as ctx:
            app.dispatch_jsonrpc(request, {})
        self.assertEqual(401, ctx.exception.http_status)
        status, payload = app.dispatch_jsonrpc(
            request,
            {"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(200, status)
        self.assertEqual({}, payload["result"])

    def test_method_and_tool_headers_must_match_body(self) -> None:
        app = self._app()
        with self.assertRaises(RemoteTransportError):
            app.dispatch_jsonrpc(
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                {"Mcp-Method": "tools/list"},
            )
        with self.assertRaises(RemoteTransportError):
            app.dispatch_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "get_runtime_health", "arguments": {}},
                },
                {"Mcp-Method": "tools/call", "Mcp-Name": "start_investigation"},
            )

    def test_unsupported_protocol_is_rejected(self) -> None:
        app = self._app()
        with self.assertRaises(RemoteTransportError) as ctx:
            app.dispatch_jsonrpc(
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                {"MCP-Protocol-Version": "2099-01-01"},
            )
        self.assertEqual(-32022, ctx.exception.rpc_code)

    def test_origin_allowlist_is_enforced_only_when_configured(self) -> None:
        app = RemoteMcpApplication(
            self.dispatch,
            auth=RemoteAuthConfig(mode="none", allowed_origins=("https://chatgpt.com",)),
        )
        request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        with self.assertRaises(RemoteTransportError) as ctx:
            app.dispatch_jsonrpc(request, {"Origin": "https://evil.example"})
        self.assertEqual(403, ctx.exception.http_status)
        status, _ = app.dispatch_jsonrpc(request, {"Origin": "https://chatgpt.com"})
        self.assertEqual(200, status)


if __name__ == "__main__":
    unittest.main()
