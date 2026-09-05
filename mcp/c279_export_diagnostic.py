#!/usr/bin/env python3
"""Isolated, one-shot encrypted C279 diagnostic export helper.

This module is intentionally scoped to the temporary C279 diagnostic branch. It
restores the authoritative object-store generation into a temporary directory,
extracts exactly one investigation session, and returns only an authenticated
encrypted envelope. It never calls object-store mutation APIs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


ENVELOPE_SCHEMA = "cbi.v64-c279-export-envelope.v1"
ALGORITHM = "X25519-HKDF-SHA256-CHACHA20POLY1305"
AAD = b"cbi.v64-c279-export-envelope.v1"
HKDF_INFO = b"cbi-v64-c279-export-v1"


class DiagnosticExportError(RuntimeError):
    pass


def _tree_fingerprint(root: Path | None) -> str | None:
    if root is None:
        return None
    resolved = root.expanduser().resolve()
    if not resolved.exists():
        return "MISSING"
    digest = hashlib.sha256()
    if resolved.is_file():
        digest.update(b"FILE\0")
        digest.update(resolved.read_bytes())
        return digest.hexdigest()
    for path in sorted(resolved.rglob("*")):
        rel = path.relative_to(resolved).as_posix()
        if path.is_dir():
            digest.update(f"D\0{rel}\n".encode("utf-8"))
            continue
        if path.is_file():
            body = path.read_bytes()
            digest.update(f"F\0{rel}\0{len(body)}\0".encode("utf-8"))
            digest.update(hashlib.sha256(body).digest())
            digest.update(b"\n")
    return digest.hexdigest()


def _recipient_public_key(value: str) -> X25519PublicKey:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
        if len(raw) != 32:
            raise ValueError("X25519 public key must be 32 bytes")
        return X25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise DiagnosticExportError("RECIPIENT_PUBLIC_KEY_INVALID") from exc


def _encrypt(plaintext: bytes, recipient: X25519PublicKey) -> bytes:
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    shared = ephemeral_private.exchange(recipient)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=HKDF_INFO,
    ).derive(shared)
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, plaintext, AAD)
    envelope: dict[str, Any] = {
        "schema": ENVELOPE_SCHEMA,
        "algorithm": ALGORITHM,
        "ephemeral_public_key_b64": base64.b64encode(ephemeral_public).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }
    return (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class C279ExportDiagnostic:
    """Restore one authoritative session read-only and return it encrypted once."""

    def __init__(
        self,
        *,
        state_manager,
        investigation_id: str,
        recipient_public_key_b64: str,
        enabled: bool,
        protected_live_root: Path | None = None,
    ) -> None:
        self.state_manager = state_manager
        self.investigation_id = str(investigation_id or "").strip()
        self.recipient_public_key_b64 = str(recipient_public_key_b64 or "").strip()
        self.enabled = bool(enabled)
        self.protected_live_root = protected_live_root
        self._consumed = False

    def export_once(self) -> bytes:
        if not self.enabled:
            raise DiagnosticExportError("EXPORT_DISABLED")
        if self._consumed:
            raise DiagnosticExportError("EXPORT_ALREADY_CONSUMED")
        if not self.investigation_id or any(ch in self.investigation_id for ch in "/\\\x00"):
            raise DiagnosticExportError("INVESTIGATION_ID_INVALID")

        recipient = _recipient_public_key(self.recipient_public_key_b64)
        before_live = _tree_fingerprint(self.protected_live_root)

        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-export-restore-") as temp_name:
            restored_root = Path(temp_name) / "runtime"
            try:
                restored = self.state_manager.restore_into(restored_root)
            except Exception as exc:
                raise DiagnosticExportError("EXPORT_RESTORE_FAILED") from exc
            if not restored:
                raise DiagnosticExportError("EXPORT_SOURCE_UNAVAILABLE")

            session_path = restored_root / "sessions" / f"{self.investigation_id}.jsonl"
            if not session_path.is_file():
                raise DiagnosticExportError("EXPORT_SESSION_NOT_FOUND")
            plaintext = session_path.read_bytes()

        after_live = _tree_fingerprint(self.protected_live_root)
        if before_live != after_live:
            raise DiagnosticExportError("PROTECTED_LIVE_ROOT_CHANGED")

        envelope = _encrypt(plaintext, recipient)
        self._consumed = True
        return envelope
