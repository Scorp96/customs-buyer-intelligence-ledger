from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from unified_runtime.render_r2_acceptance_client_v63 import (
    RenderR2AcceptanceClient,
    RenderR2AcceptanceClientConfig,
    RenderR2AcceptanceClientError,
)


EXPECTED_SHA = "0123456789abcdef0123456789abcdef01234567"
TOKEN = "v63-acceptance-bearer-token-00000000000000000000"
REQUIRED_MUTATIONS = {
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
}


class _AcceptanceHttpFixture:
    def __init__(self, *, deployed_sha: str = EXPECTED_SHA) -> None:
        self.deployed_sha = deployed_sha
        self.posts: list[dict[str, object]] = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def _json(self, status: int, value: object) -> None:
                payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/healthz":
                    self._json(404, {"status": "not_found"})
                    return
                self._json(
                    200,
                    {
                        "status": "ok",
                        "deployment_identity": {
                            "schema": "cbi.remote-deployment-identity.v6.3",
                            "git_sha": fixture.deployed_sha,
                            "git_sha_source": "RENDER_GIT_COMMIT",
                            "acceptance_pin_required": True,
                            "remote_entrypoint": "mcp/server_v61_remote.py",
                            "runtime_entrypoint": "mcp/server_v61_backup_recovery.py",
                            "object_store_mode": "r2",
                            "object_state_schema": "cbi.object-store-state.v2",
                            "object_state_generation": 7,
                            "restore_generation": 6,
                            "restore_source": "object_state_v2",
                        },
                        "synthetic_secret_access_key": "must-never-escape-health",
                    },
                )

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or "0")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                fixture.posts.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "protocol": self.headers.get("MCP-Protocol-Version"),
                        "body": body,
                    }
                )
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._json(401, {"error": "unauthorized"})
                    return
                method = body.get("method")
                request_id = body.get("id")
                if method == "server/discover":
                    result = {
                        "resultType": "complete",
                        "supportedVersions": ["2026-07-28"],
                        "capabilities": {"tools": {}},
                    }
                elif method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "cbi", "version": "6.3"},
                    }
                elif method == "tools/list":
                    result = {
                        "tools": [
                            {"name": "get_runtime_health"},
                            *[{"name": name} for name in sorted(REQUIRED_MUTATIONS)],
                        ]
                    }
                elif method == "tools/call":
                    result = {
                        "structuredContent": {
                            "status": "DISCOVERED",
                            "candidate_id": "CAND-SYNTH-001",
                            "mutation_meta": {
                                "request_sha256": "a" * 64,
                                "idempotency_key": "raw-key-must-not-escape",
                            },
                            "nested": {
                                "secret_access_key": "raw-secret-must-not-escape",
                                "safe": "kept",
                            },
                        }
                    }
                else:
                    self._json(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": "unknown"},
                        },
                    )
                    return
                self._json(200, {"jsonrpc": "2.0", "id": request_id, "result": result})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class V63RenderR2AcceptanceClientTests(unittest.TestCase):
    def _client(self, fixture: _AcceptanceHttpFixture) -> RenderR2AcceptanceClient:
        return RenderR2AcceptanceClient(
            RenderR2AcceptanceClientConfig(
                base_url=fixture.base_url,
                bearer_token=TOKEN,
                expected_git_sha=EXPECTED_SHA,
                timeout_seconds=5.0,
            )
        )

    def test_deployment_sha_is_pinned_before_any_mcp_post(self) -> None:
        fixture = _AcceptanceHttpFixture(deployed_sha="f" * 40)
        self.addCleanup(fixture.close)
        client = self._client(fixture)
        with self.assertRaisesRegex(RenderR2AcceptanceClientError, "DEPLOYMENT_GIT_SHA_MISMATCH"):
            client.list_tool_names()
        self.assertEqual(fixture.posts, [])
        self.assertNotIn(TOKEN, repr(client.config))

    def test_discovers_initializes_lists_and_proves_required_mutation_surface(self) -> None:
        fixture = _AcceptanceHttpFixture()
        self.addCleanup(fixture.close)
        client = self._client(fixture)

        health = client.read_health()
        self.assertEqual(health["deployment_identity"]["git_sha"], EXPECTED_SHA)
        self.assertNotIn("must-never-escape-health", json.dumps(health, sort_keys=True))

        discovery = client.discover()
        self.assertEqual(discovery["supportedVersions"], ["2026-07-28"])
        initialized = client.initialize()
        self.assertEqual(initialized["protocolVersion"], "2025-06-18")
        names = client.list_tool_names()
        self.assertTrue(REQUIRED_MUTATIONS.issubset(set(names)))

        surface = client.required_v63_mutation_surface()
        self.assertEqual(set(surface["required_tools"]), REQUIRED_MUTATIONS)
        self.assertTrue(REQUIRED_MUTATIONS.issubset(set(surface["observed_tools"])))
        self.assertEqual(surface["deployment_git_sha"], EXPECTED_SHA)

        self.assertGreaterEqual(len(fixture.posts), 4)
        for request in fixture.posts:
            self.assertEqual(request["path"], "/mcp")
            self.assertEqual(request["authorization"], f"Bearer {TOKEN}")
            self.assertEqual(request["protocol"], "2026-07-28")

    def test_tool_response_is_recursively_sanitized(self) -> None:
        fixture = _AcceptanceHttpFixture()
        self.addCleanup(fixture.close)
        client = self._client(fixture)
        result = client.call_tool(
            "append_candidate_discovery",
            {
                "investigation_id": "INV-SYNTH",
                "candidate": {"candidate_id": "CAND-SYNTH-001"},
                "idempotency_key": "caller-key-is-sent-but-never-returned",
            },
        )
        serialized = json.dumps(result, sort_keys=True)
        self.assertEqual(result["status"], "DISCOVERED")
        self.assertEqual(result["nested"]["safe"], "kept")
        self.assertNotIn("raw-key-must-not-escape", serialized)
        self.assertNotIn("raw-secret-must-not-escape", serialized)
        self.assertNotIn("idempotency_key", serialized.casefold())
        self.assertNotIn("secret_access_key", serialized.casefold())
        self.assertNotIn(TOKEN, serialized)


if __name__ == "__main__":
    unittest.main()
