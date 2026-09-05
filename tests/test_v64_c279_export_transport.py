from __future__ import annotations

from contextlib import contextmanager
import json
import threading
import unittest
import urllib.error
import urllib.request

from mcp import remote_transport as base
from mcp.chatgpt_oauth_transport import ChatGPTOAuthRequestHandler, ChatGPTRemoteAuthConfig


PATH = "/internal/v64/c279-session-export"
STATIC_TOKEN = "S" * 64
OAUTH_LIKE_TOKEN = "O" * 64


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
    auth = ChatGPTRemoteAuthConfig(mode="none")
    app = base.RemoteMcpApplication(
        _dispatch,
        auth=auth,
        health=lambda: {"status": "ok", "marker": "stable"},
    )
    server = base._ReusableThreadingHTTPServer(("127.0.0.1", 0), ChatGPTOAuthRequestHandler)
    server.app = app
    server.public_base = f"http://127.0.0.1:{server.server_address[1]}"
    server.diagnostic_export = callback
    server.diagnostic_static_bearer = STATIC_TOKEN
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.public_base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(base_url: str, method: str, path: str, *, body: bytes | None = None, headers=None):
    request = urllib.request.Request(
        base_url + path,
        data=body,
        headers=dict(headers or {}),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


class V64C279ExportTransportTests(unittest.TestCase):
    def _callback(self):
        return {
            "schema": "cbi.v64-c279-single-session-export.v1",
            "snapshot_sha256": "0" * 64,
            "byte_length": 2,
            "tail_seq": 1,
            "tail_event_hash": "1" * 64,
            "payload_encoding": "base64",
            "payload": "e30=",
        }

    def test_static_bearer_primitive_is_exact_and_sanitized(self):
        require = getattr(base, "require_static_bearer")
        require({"Authorization": f"Bearer {STATIC_TOKEN}"}, STATIC_TOKEN)
        with self.assertRaises(base.RemoteTransportError) as missing:
            require({}, STATIC_TOKEN)
        self.assertEqual(missing.exception.http_status, 401)
        self.assertEqual(str(missing.exception), "Bearer authentication required")
        with self.assertRaises(base.RemoteTransportError) as wrong:
            require({"Authorization": f"Bearer {OAUTH_LIKE_TOKEN}"}, STATIC_TOKEN)
        self.assertEqual(wrong.exception.http_status, 401)
        self.assertEqual(str(wrong.exception), "Invalid bearer credential")
        self.assertNotIn(STATIC_TOKEN, str(wrong.exception))
        self.assertNotIn(OAUTH_LIKE_TOKEN, str(wrong.exception))

    def test_callback_absent_returns_404_before_auth_for_get_and_post(self):
        with _server(None) as base_url:
            for method, body in (("GET", None), ("POST", b"{}")):
                status, _headers, _body = _request(
                    base_url,
                    method,
                    PATH,
                    body=body,
                    headers={"Content-Type": "application/json"} if body is not None else {},
                )
                self.assertEqual(status, 404)

    def test_enabled_route_rejects_missing_and_wrong_static_bearer_without_callback(self):
        calls: list[int] = []
        def callback():
            calls.append(1)
            return self._callback()
        with _server(callback) as base_url:
            status, _headers, _body = _request(
                base_url, "POST", PATH, body=b"{}", headers={"Content-Type": "application/json"}
            )
            self.assertEqual(status, 401)
            status, _headers, _body = _request(
                base_url,
                "POST",
                PATH,
                body=b"{}",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {OAUTH_LIKE_TOKEN}"},
            )
            self.assertEqual(status, 401)
            self.assertEqual(calls, [])

    def test_query_content_type_and_body_are_fail_closed(self):
        calls: list[int] = []
        def callback():
            calls.append(1)
            return self._callback()
        auth = {"Authorization": f"Bearer {STATIC_TOKEN}"}
        with _server(callback) as base_url:
            status, _headers, _body = _request(
                base_url,
                "POST",
                PATH + "?id=x",
                body=b"{}",
                headers={**auth, "Content-Type": "application/json"},
            )
            self.assertEqual(status, 404)
            status, _headers, _body = _request(
                base_url,
                "POST",
                PATH,
                body=b"{}",
                headers={**auth, "Content-Type": "text/plain"},
            )
            self.assertEqual(status, 400)
            status, _headers, _body = _request(
                base_url,
                "POST",
                PATH,
                body=b"{",
                headers={**auth, "Content-Type": "application/json"},
            )
            self.assertEqual(status, 400)
            status, _headers, _body = _request(
                base_url,
                "POST",
                PATH,
                body=b'{"x":1}',
                headers={**auth, "Content-Type": "application/json"},
            )
            self.assertEqual(status, 400)
            self.assertEqual(calls, [])

    def test_exact_post_succeeds_once_and_has_fixed_security_headers(self):
        calls: list[int] = []
        def callback():
            calls.append(1)
            return self._callback()
        with _server(callback) as base_url:
            status, headers, body = _request(
                base_url,
                "POST",
                PATH,
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {STATIC_TOKEN}",
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(calls, [1])
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(json.loads(body.decode("utf-8")), self._callback())

    def test_get_and_delete_are_405_when_enabled(self):
        with _server(self._callback) as base_url:
            for method in ("GET", "DELETE"):
                status, _headers, _body = _request(base_url, method, PATH)
                self.assertEqual(status, 405)

    def test_existing_health_mcp_and_oauth_metadata_are_unchanged(self):
        with _server(self._callback) as base_url:
            status, _headers, body = _request(base_url, "GET", "/healthz")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body.decode("utf-8")), {"status": "ok", "marker": "stable"})

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
            status, _headers, body = _request(
                base_url,
                "POST",
                "/mcp",
                body=json.dumps(request).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body.decode("utf-8"))["result"], {"tools": []})

            status, _headers, body = _request(
                base_url, "GET", "/.well-known/oauth-protected-resource/mcp"
            )
            self.assertEqual(status, 200)
            metadata = json.loads(body.decode("utf-8"))
            self.assertNotIn("c279", json.dumps(metadata).lower())
            self.assertEqual(metadata["resource"], base_url + "/mcp")


if __name__ == "__main__":
    unittest.main()
