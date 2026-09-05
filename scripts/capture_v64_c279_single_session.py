#!/usr/bin/env python3
"""Capture one validated C279 export response and persist ciphertext only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


EXPORT_PATH = "/internal/v64/c279-session-export"
EXPORT_SCHEMA = "cbi.v64-c279-single-session-export.v1"
CIPHERTEXT_SCHEMA = "cbi.v64-c279-ciphertext.v1"
HKDF_INFO = b"cbi-v64-c279-export-v1"
_MAX_PLAINTEXT_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = 12 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CaptureError(RuntimeError):
    pass


def _public_key(value: str) -> X25519PublicKey:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
        if len(raw) != 32:
            raise ValueError("wrong key length")
        return X25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise CaptureError("CAPTURE_RECIPIENT_PUBLIC_KEY_INVALID") from exc


def encrypt_snapshot(
    payload: bytes,
    *,
    snapshot_sha256: str,
    recipient_public_key_b64: str,
) -> dict[str, str]:
    body = bytes(payload)
    sha = str(snapshot_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(sha) or hashlib.sha256(body).hexdigest() != sha:
        raise CaptureError("CAPTURE_SHA256_MISMATCH")
    if len(body) > _MAX_PLAINTEXT_BYTES:
        raise CaptureError("CAPTURE_PAYLOAD_TOO_LARGE")

    recipient = _public_key(recipient_public_key_b64)
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    shared = ephemeral_private.exchange(recipient)
    salt = os.urandom(32)
    nonce = os.urandom(12)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=HKDF_INFO,
    ).derive(shared)
    aad = CIPHERTEXT_SCHEMA.encode("ascii") + b"|" + sha.encode("ascii")
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, body, aad)
    return {
        "schema": CIPHERTEXT_SCHEMA,
        "ephemeral_public_key": base64.b64encode(ephemeral_public).decode("ascii"),
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "snapshot_sha256": sha,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def _endpoint(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception as exc:
        raise CaptureError("CAPTURE_BASE_URL_INVALID") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise CaptureError("CAPTURE_BASE_URL_INVALID")
    return raw + EXPORT_PATH


def _read_response(response) -> bytes:
    declared = str(response.headers.get("Content-Length") or "").strip()
    if declared:
        try:
            if int(declared) > _MAX_RESPONSE_BYTES:
                raise CaptureError("CAPTURE_RESPONSE_TOO_LARGE")
        except ValueError as exc:
            raise CaptureError("CAPTURE_RESPONSE_INVALID") from exc
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise CaptureError("CAPTURE_RESPONSE_TOO_LARGE")
    return body


def _validated_export(body: bytes) -> tuple[bytes, str]:
    try:
        value = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise CaptureError("CAPTURE_RESPONSE_INVALID") from exc
    if not isinstance(value, dict):
        raise CaptureError("CAPTURE_RESPONSE_INVALID")
    if value.get("schema") != EXPORT_SCHEMA or value.get("payload_encoding") != "base64":
        raise CaptureError("CAPTURE_RESPONSE_INVALID")

    sha = str(value.get("snapshot_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(sha):
        raise CaptureError("CAPTURE_RESPONSE_INVALID")
    try:
        byte_length = int(value.get("byte_length"))
    except (TypeError, ValueError) as exc:
        raise CaptureError("CAPTURE_RESPONSE_INVALID") from exc
    if byte_length < 0 or byte_length > _MAX_PLAINTEXT_BYTES:
        raise CaptureError("CAPTURE_RESPONSE_INVALID")
    try:
        payload = base64.b64decode(str(value.get("payload") or ""), validate=True)
    except Exception as exc:
        raise CaptureError("CAPTURE_RESPONSE_INVALID") from exc
    if len(payload) != byte_length:
        raise CaptureError("CAPTURE_BYTE_LENGTH_MISMATCH")
    if hashlib.sha256(payload).hexdigest() != sha:
        raise CaptureError("CAPTURE_SHA256_MISMATCH")
    return payload, sha


def capture_and_encrypt(
    *,
    base_url: str,
    bearer: str,
    recipient_public_key_b64: str,
) -> dict[str, object]:
    token = str(bearer or "").strip()
    if len(token) < 32:
        raise CaptureError("CAPTURE_BEARER_INVALID")
    endpoint = _endpoint(base_url)
    request = urllib.request.Request(
        endpoint,
        data=b"{}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "CBI-v6.4-C279-Capture/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(response.status) != 200:
                raise CaptureError(f"CAPTURE_HTTP_{int(response.status)}")
            body = _read_response(response)
    except urllib.error.HTTPError as exc:
        raise CaptureError(f"CAPTURE_HTTP_{int(exc.code)}") from None
    except urllib.error.URLError:
        raise CaptureError("CAPTURE_HTTP_UNAVAILABLE") from None
    except TimeoutError:
        raise CaptureError("CAPTURE_HTTP_UNAVAILABLE") from None

    payload, sha = _validated_export(body)
    return encrypt_snapshot(
        payload,
        snapshot_sha256=sha,
        recipient_public_key_b64=recipient_public_key_b64,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture one C279 session export and persist ciphertext only")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--recipient-public-key-b64", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bearer = str(os.environ.get("CBI_V64_C279_CAPTURE_BEARER") or "").strip()
    try:
        envelope = capture_and_encrypt(
            base_url=args.base_url,
            bearer=bearer,
            recipient_public_key_b64=args.recipient_public_key_b64,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(envelope, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        return 0
    except (CaptureError, OSError) as exc:
        code = str(exc) if isinstance(exc, CaptureError) else "CAPTURE_OUTPUT_WRITE_FAILED"
        print(f"C279 capture failed: {code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
