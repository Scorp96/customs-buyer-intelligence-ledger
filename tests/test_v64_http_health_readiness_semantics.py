"""Real loopback HTTP regression: liveness is not durable MCP readiness."""
from __future__ import annotations

import http.client
import json
import threading
import unittest

from mcp import remote_transport as transport


class HttpHealthReadinessSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = {"status": "ok", "service": "customs-buyer-intelligence"}
        cls.raise_health_error = False

        def health():
            if cls.raise_health_error:
                raise RuntimeError("simulated private storage failure")
            return dict(cls.current)

        app = transport.RemoteMcpApplication(
            lambda method, params: {},
            auth=transport.RemoteAuthConfig(mode="bearer", bearer_token="x" * 48),
            health=health,
        )
        cls.server = transport._ReusableThreadingHTTPServer(
            ("127.0.0.1", 0), transport.RemoteMcpRequestHandler
        )
        cls.server.app = app
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        type(self).current = {"status": "ok", "service": "customs-buyer-intelligence"}
        type(self).raise_health_error = False

    def get(self, path: str):
        host, port = self.server.server_address
        client = http.client.HTTPConnection(host, port, timeout=4)
        try:
            client.request("GET", path)
            res = client.getresponse()
            status = res.status
            headers = dict(res.getheaders())
            raw = res.read()
            return status, headers, json.loads(raw) if raw else None
        finally:
            client.close()

    def test_healthy_runtime_is_ready(self):
        status, headers, body = self.get("/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_degraded_runtime_preserves_process_liveness_but_fails_readiness(self):
        type(self).current = {"status": "degraded", "service": "customs-buyer-intelligence"}
        live_status, _, live_body = self.get("/healthz")
        ready_status, ready_headers, ready_body = self.get("/readyz")
        self.assertEqual(live_status, 200)
        self.assertEqual(live_body["status"], "degraded")
        self.assertEqual(ready_status, 503)
        self.assertEqual(ready_body["status"], "degraded")
        self.assertEqual(ready_headers.get("Cache-Control"), "no-store")

    def test_unknown_or_nonready_status_fails_closed(self):
        for raw in ("bootstrap_required", "error", "degraded", "", "unknown", None):
            with self.subTest(status=raw):
                type(self).current = {"status": raw}
                code, _, body = self.get("/readyz")
                self.assertEqual(code, 503)
                self.assertEqual(body["status"], raw)

    def test_provider_health_exception_returns_minimal_error_503(self):
        type(self).raise_health_error = True
        for path in ("/healthz", "/readyz"):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual(status, 503)
                self.assertEqual(body, {"status": "error"})
                self.assertNotIn("simulated private storage failure", json.dumps(body))

    def test_nonhealth_404_and_method_rules_not_changed(self):
        for path, expected in (("/missing", 404), ("/mcp", 405)):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, expected)
                self.assertIsNone(body)
                self.assertEqual(headers.get("Content-Length"), "0")


if __name__ == "__main__":
    unittest.main()
