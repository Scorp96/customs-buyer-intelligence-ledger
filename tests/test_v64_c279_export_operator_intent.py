from __future__ import annotations

from contextlib import contextmanager
import json
import threading
import unittest
import urllib.error
import urllib.request

from mcp import remote_transport as base
from mcp.chatgpt_oauth_transport import ChatGPTOAuthRequestHandler


PATH = "/internal/v64/c279-session-export"
STATIC_TOKEN = "S" * 64
OPERATOR_TOKEN = "O" * 64
INTENT = "I" * 64


class _OperatorAuth:
    def authorize(self, headers):
        value = str(headers.get("Authorization") or headers.get("authorization") or "")
        if value != f"Bearer {OPERATOR_TOKEN}":
            raise base.RemoteTransportError(
                "operator authentication required",
                http_status=401,
                rpc_code=-32001,
            )


def _dispatch(method: str, params: dict):
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cbi-test", "version": "1"},
            "instructions": "stable",
        }
    if method == "tools/list":
        return {"tools": []}
    return {"method": method, "params": params}


@contextmanager
def _server(callback):
    app = base.RemoteMcpApplication(
        _dispatch,
        auth=_OperatorAuth(),
        health=lambda: {"status": "ok"},
    )
    server = base._ReusableThreadingHTTPServer(("127.0.0.1", 0), ChatGPTOAuthRequestHandler)
    server.app = app
    server.public_base = f"http://127.0.0.1:{server.server_address[1]}"
    server.diagnostic_export = callback
    server.diagnostic_static_bearer = STATIC_TOKEN
    server.diagnostic_operator_intent = INTENT
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.public_base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post(base_url: str, *, token: str | None, intent: str | None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if intent is not None:
        headers["X-CBI-Diagnostic-Intent"] = intent
    request = urllib.request.Request(
        base_url + PATH,
        data=b"{}",
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


class V64C279ExportOperatorIntentTests(unittest.TestCase):
    def _payload(self):
        return {
            "schema": "cbi.v64-c279-single-session-export.v1",
            "snapshot_sha256": "0" * 64,
            "byte_length": 2,
            "tail_seq": 1,
            "tail_event_hash": "1" * 64,
            "payload_encoding": "base64",
            "payload": "e30=",
        }

    def test_operator_auth_requires_exact_intent_before_callback(self):
        calls: list[int] = []

        def callback():
            calls.append(1)
            return self._payload()

        with _server(callback) as base_url:
            status, _ = _post(base_url, token=OPERATOR_TOKEN, intent=None)
            self.assertEqual(status, 404)
            status, _ = _post(base_url, token=OPERATOR_TOKEN, intent="X" * 64)
            self.assertEqual(status, 404)
            self.assertEqual(calls, [])

            status, _ = _post(base_url, token=None, intent=INTENT)
            self.assertEqual(status, 401)
            status, _ = _post(base_url, token=STATIC_TOKEN, intent=INTENT)
            self.assertEqual(status, 401)
            self.assertEqual(calls, [])

            status, body = _post(base_url, token=OPERATOR_TOKEN, intent=INTENT)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body.decode("utf-8")), self._payload())
            self.assertEqual(calls, [1])

    def test_operator_intent_does_not_change_existing_mcp_auth(self):
        with _server(self._payload) as base_url:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
            body = json.dumps(request).encode("utf-8")
            req = urllib.request.Request(
                base_url + "/mcp",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPERATOR_TOKEN}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertEqual(int(response.status), 200)
                self.assertEqual(json.loads(response.read().decode("utf-8"))["result"], {"tools": []})


if __name__ == "__main__":
    unittest.main()
