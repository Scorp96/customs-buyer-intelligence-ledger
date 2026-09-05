from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


CRYPTO_AVAILABLE = importlib.util.find_spec("cryptography") is not None
BEARER = "B" * 64
INTENT = "I" * 64
PLAINTEXT = b'{"seq":1,"synthetic":"C279-CAPTURE-PLAINTEXT"}\n'


@contextmanager
def _export_server(payload: bytes, *, byte_length: int | None = None, sha256: str | None = None, status: int = 200, error_body: bytes = b""):
    observed: dict[str, object] = {}
    response = {
        "schema": "cbi.v64-c279-single-session-export.v1",
        "snapshot_sha256": sha256 or hashlib.sha256(payload).hexdigest(),
        "byte_length": len(payload) if byte_length is None else byte_length,
        "tail_seq": 1,
        "tail_event_hash": "1" * 64,
        "payload_encoding": "base64",
        "payload": base64.b64encode(payload).decode("ascii"),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):  # noqa: A003
            return

        def do_POST(self):  # noqa: N802
            observed["path"] = self.path
            observed["authorization"] = self.headers.get("Authorization")
            observed["intent"] = self.headers.get("X-CBI-Diagnostic-Intent")
            observed["content_type"] = self.headers.get("Content-Type")
            length = int(self.headers.get("Content-Length") or "0")
            observed["body"] = self.rfile.read(length)
            body = error_body if status != 200 else json.dumps(response, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class V64C279CaptureIntentTests(unittest.TestCase):
    @staticmethod
    def _module():
        return importlib.import_module("scripts.capture_v64_c279_single_session")

    def test_capture_rejects_missing_or_short_intent_before_network_request(self):
        capture = self._module()
        for supplied_intent in ("", "I" * 31):
            with self.subTest(intent_length=len(supplied_intent)), mock.patch.object(capture.urllib.request, "urlopen") as urlopen:
                with self.assertRaises(capture.CaptureError) as caught:
                    capture.capture_and_encrypt(
                        base_url="https://example.invalid",
                        bearer=BEARER,
                        intent=supplied_intent,
                        recipient_public_key_b64="not-used-before-network",
                    )
                self.assertEqual(str(caught.exception), "CAPTURE_INTENT_INVALID")
                urlopen.assert_not_called()

    def test_capture_sends_exact_intent_header_before_encryption(self):
        capture = self._module()
        with mock.patch.object(
            capture.urllib.request,
            "urlopen",
            side_effect=capture.urllib.error.URLError("synthetic"),
        ) as urlopen:
            with self.assertRaises(capture.CaptureError) as caught:
                capture.capture_and_encrypt(
                    base_url="https://example.invalid",
                    bearer=BEARER,
                    intent=INTENT,
                    recipient_public_key_b64="not-used-before-network",
                )
        self.assertEqual(str(caught.exception), "CAPTURE_HTTP_UNAVAILABLE")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-cbi-diagnostic-intent"), INTENT)


@unittest.skipUnless(CRYPTO_AVAILABLE, "cryptography capture dependency not installed")
class V64C279CaptureTests(unittest.TestCase):
    @staticmethod
    def _module():
        return importlib.import_module("scripts.capture_v64_c279_single_session")

    @staticmethod
    def _recipient():
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        private = X25519PrivateKey.generate()
        public_b64 = base64.b64encode(
            private.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        return private, public_b64

    @staticmethod
    def _decrypt(private_key, envelope: dict[str, str]) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        peer = X25519PublicKey.from_public_bytes(base64.b64decode(envelope["ephemeral_public_key"], validate=True))
        shared = private_key.exchange(peer)
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=b"cbi-v64-c279-export-v1",
        ).derive(shared)
        aad = b"cbi.v64-c279-ciphertext.v1|" + envelope["snapshot_sha256"].encode("ascii")
        return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)

    def test_encrypt_round_trip_exact_envelope_and_no_plaintext_field(self):
        capture = self._module()
        private, public_b64 = self._recipient()
        sha = hashlib.sha256(PLAINTEXT).hexdigest()
        envelope = capture.encrypt_snapshot(
            PLAINTEXT,
            snapshot_sha256=sha,
            recipient_public_key_b64=public_b64,
        )
        self.assertEqual(set(envelope), {
            "schema",
            "ephemeral_public_key",
            "salt",
            "nonce",
            "snapshot_sha256",
            "ciphertext",
        })
        self.assertEqual(envelope["schema"], "cbi.v64-c279-ciphertext.v1")
        self.assertEqual(envelope["snapshot_sha256"], sha)
        self.assertNotIn("payload", envelope)
        self.assertNotIn(base64.b64encode(PLAINTEXT).decode("ascii"), json.dumps(envelope))
        self.assertEqual(self._decrypt(private, envelope), PLAINTEXT)

    def test_ciphertext_flip_and_snapshot_hash_aad_change_raise_invalid_tag(self):
        from cryptography.exceptions import InvalidTag

        capture = self._module()
        private, public_b64 = self._recipient()
        sha = hashlib.sha256(PLAINTEXT).hexdigest()
        envelope = capture.encrypt_snapshot(PLAINTEXT, snapshot_sha256=sha, recipient_public_key_b64=public_b64)

        tampered = dict(envelope)
        raw = bytearray(base64.b64decode(tampered["ciphertext"], validate=True))
        raw[len(raw) // 2] ^= 1
        tampered["ciphertext"] = base64.b64encode(bytes(raw)).decode("ascii")
        with self.assertRaises(InvalidTag):
            self._decrypt(private, tampered)

        aad_changed = dict(envelope)
        aad_changed["snapshot_sha256"] = "f" * 64
        with self.assertRaises(InvalidTag):
            self._decrypt(private, aad_changed)

    def test_capture_validates_length_and_sha_before_encryption(self):
        capture = self._module()
        _private, public_b64 = self._recipient()
        with _export_server(PLAINTEXT, byte_length=len(PLAINTEXT) + 1) as (base_url, _observed):
            with self.assertRaises(capture.CaptureError) as caught:
                capture.capture_and_encrypt(base_url=base_url, bearer=BEARER, intent=INTENT, recipient_public_key_b64=public_b64)
            self.assertEqual(str(caught.exception), "CAPTURE_BYTE_LENGTH_MISMATCH")
        with _export_server(PLAINTEXT, sha256="0" * 64) as (base_url, _observed):
            with self.assertRaises(capture.CaptureError) as caught:
                capture.capture_and_encrypt(base_url=base_url, bearer=BEARER, intent=INTENT, recipient_public_key_b64=public_b64)
            self.assertEqual(str(caught.exception), "CAPTURE_SHA256_MISMATCH")

    def test_capture_posts_exact_empty_object_with_exact_intent_and_never_leaks_credentials(self):
        capture = self._module()
        private, public_b64 = self._recipient()
        with _export_server(PLAINTEXT) as (base_url, observed):
            envelope = capture.capture_and_encrypt(
                base_url=base_url,
                bearer=BEARER,
                intent=INTENT,
                recipient_public_key_b64=public_b64,
            )
        self.assertEqual(observed["path"], "/internal/v64/c279-session-export")
        self.assertEqual(observed["authorization"], f"Bearer {BEARER}")
        self.assertEqual(observed["intent"], INTENT)
        self.assertEqual(observed["content_type"], "application/json")
        self.assertEqual(observed["body"], b"{}")
        self.assertEqual(self._decrypt(private, envelope), PLAINTEXT)

        with _export_server(PLAINTEXT, status=503, error_body=BEARER.encode("ascii")) as (base_url, _observed):
            with self.assertRaises(capture.CaptureError) as caught:
                capture.capture_and_encrypt(base_url=base_url, bearer=BEARER, intent=INTENT, recipient_public_key_b64=public_b64)
            self.assertNotIn(BEARER, str(caught.exception))

    def test_cli_persists_only_ciphertext_json(self):
        _capture = self._module()
        private, public_b64 = self._recipient()
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts" / "capture_v64_c279_single_session.py"
        with _export_server(PLAINTEXT) as (base_url, _observed), tempfile.TemporaryDirectory(prefix="cbi-v64-c279-cli-") as temp:
            output = Path(temp) / "ciphertext.json"
            env = dict(os.environ)
            env["CBI_V64_C279_CAPTURE_BEARER"] = BEARER
            env["CBI_V64_C279_CAPTURE_INTENT"] = INTENT
            run = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--base-url",
                    base_url,
                    "--recipient-public-key-b64",
                    public_b64,
                    "--output",
                    str(output),
                ],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn(BEARER, run.stdout + run.stderr)
            self.assertNotIn(INTENT, run.stdout + run.stderr)
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), ["ciphertext.json"])
            envelope = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(set(envelope), {
                "schema",
                "ephemeral_public_key",
                "salt",
                "nonce",
                "snapshot_sha256",
                "ciphertext",
            })
            self.assertEqual(self._decrypt(private, envelope), PLAINTEXT)


if __name__ == "__main__":
    unittest.main()
