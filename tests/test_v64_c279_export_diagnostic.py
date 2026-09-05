from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from mcp.c279_export_diagnostic import C279ExportDiagnostic, DiagnosticExportError
from mcp.object_store_persistence import ObjectStoreConflict
from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63


class _SeedObjectClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}

    @staticmethod
    def _etag(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()[:32]

    def get(self, key: str):
        if key not in self.objects:
            return None, ""
        return self.objects[key], self.etags[key]

    def put(self, key: str, body: bytes, *, if_match: str = "", if_none_match: bool = False):
        if if_none_match and key in self.objects:
            raise ObjectStoreConflict("exists")
        if if_match and self.etags.get(key, "") != if_match:
            raise ObjectStoreConflict("etag mismatch")
        self.objects[key] = bytes(body)
        self.etags[key] = self._etag(body)
        return self.etags[key]

    def list_keys(self, prefix: str):
        return sorted(key for key in self.objects if key.startswith(prefix))

    def delete(self, key: str):
        self.objects.pop(key, None)
        self.etags.pop(key, None)


class _ReadOnlyObjectClient:
    def __init__(self, seeded: _SeedObjectClient) -> None:
        self.seeded = seeded
        self.get_calls: list[str] = []
        self.write_attempts: list[str] = []

    def get(self, key: str):
        self.get_calls.append(key)
        return self.seeded.get(key)

    def put(self, *args, **kwargs):
        self.write_attempts.append("put")
        raise AssertionError("diagnostic export attempted object-store write")

    def list_keys(self, *args, **kwargs):
        self.write_attempts.append("list_keys")
        raise AssertionError("diagnostic export must not list object-store keys")

    def delete(self, *args, **kwargs):
        self.write_attempts.append("delete")
        raise AssertionError("diagnostic export attempted object-store delete")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_object_state(root: Path, investigation_id: str, session_bytes: bytes) -> _SeedObjectClient:
    export_root = root / "export" / "cbi-cloud-runtime"
    sessions = export_root / "sessions"
    sessions.mkdir(parents=True)
    session = sessions / f"{investigation_id}.jsonl"
    session.write_bytes(session_bytes)
    manifest = {
        "schema": "cbi.cloud-runtime-export.v1",
        "hash_chains_valid": True,
        "activation_ready": True,
        "pre_archive_quiescence_check": True,
        "payload_files": {f"sessions/{investigation_id}.jsonl": _sha256_file(session)},
        "source_durable_fingerprint_sha256": "0" * 64,
    }
    (export_root / "export-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive = root / "migration.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(export_root, arcname="cbi-cloud-runtime")

    client = _SeedObjectClient()
    writer = RecoveryObjectStoreStateManagerV63(client, prefix="cbi-v64-c279-test")
    writer.seed_migration_archive(archive, _sha256_file(archive))
    return client


def _decrypt_envelope(private_key: X25519PrivateKey, envelope_bytes: bytes) -> bytes:
    envelope = json.loads(envelope_bytes.decode("utf-8"))
    ephemeral_public = base64.b64decode(envelope["ephemeral_public_key_b64"], validate=True)
    nonce = base64.b64decode(envelope["nonce_b64"], validate=True)
    ciphertext = base64.b64decode(envelope["ciphertext_b64"], validate=True)
    peer = type(private_key.public_key()).from_public_bytes(ephemeral_public)
    shared = private_key.exchange(peer)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"cbi-v64-c279-export-v1",
    ).derive(shared)
    return ChaCha20Poly1305(key).decrypt(
        nonce,
        ciphertext,
        b"cbi.v64-c279-export-envelope.v1",
    )


class V64C279ExportDiagnosticTests(unittest.TestCase):
    def test_disabled_export_fails_before_object_store_access(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-export-disabled-") as temp:
            seed = _seed_object_state(Path(temp), "INV-DIAGNOSTIC", b'{"seq":1}\n')
            reader = _ReadOnlyObjectClient(seed)
            manager = RecoveryObjectStoreStateManagerV63(reader, prefix="cbi-v64-c279-test")
            private_key = X25519PrivateKey.generate()
            public_b64 = base64.b64encode(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii")
            diagnostic = C279ExportDiagnostic(
                state_manager=manager,
                investigation_id="INV-DIAGNOSTIC",
                recipient_public_key_b64=public_b64,
                enabled=False,
            )

            with self.assertRaisesRegex(DiagnosticExportError, "EXPORT_DISABLED"):
                diagnostic.export_once()
            self.assertEqual(reader.get_calls, [])
            self.assertEqual(reader.write_attempts, [])

    def test_export_restores_exact_session_get_only_encrypts_and_is_one_shot(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-export-") as temp:
            root = Path(temp)
            investigation_id = "INV-DIAGNOSTIC"
            plaintext = b'{"seq":1,"private":"PRIVATE-C279-SENTINEL"}\n'
            seed = _seed_object_state(root, investigation_id, plaintext)
            reader = _ReadOnlyObjectClient(seed)
            manager = RecoveryObjectStoreStateManagerV63(reader, prefix="cbi-v64-c279-test")
            private_key = X25519PrivateKey.generate()
            public_b64 = base64.b64encode(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii")
            live_root = root / "live"
            live_root.mkdir()
            live_sentinel = live_root / "sentinel.txt"
            live_sentinel.write_text("LIVE-UNCHANGED", encoding="utf-8")

            diagnostic = C279ExportDiagnostic(
                state_manager=manager,
                investigation_id=investigation_id,
                recipient_public_key_b64=public_b64,
                enabled=True,
                protected_live_root=live_root,
            )
            envelope = diagnostic.export_once()

            self.assertNotIn(b"PRIVATE-C279-SENTINEL", envelope)
            self.assertEqual(_decrypt_envelope(private_key, envelope), plaintext)
            parsed = json.loads(envelope.decode("utf-8"))
            self.assertEqual(set(parsed), {
                "schema",
                "algorithm",
                "ephemeral_public_key_b64",
                "nonce_b64",
                "ciphertext_b64",
            })
            self.assertEqual(parsed["schema"], "cbi.v64-c279-export-envelope.v1")
            self.assertEqual(parsed["algorithm"], "X25519-HKDF-SHA256-CHACHA20POLY1305")
            self.assertNotIn(investigation_id, envelope.decode("utf-8"))
            self.assertGreaterEqual(len(reader.get_calls), 2)
            self.assertEqual(reader.write_attempts, [])
            self.assertEqual(live_sentinel.read_text(encoding="utf-8"), "LIVE-UNCHANGED")

            with self.assertRaisesRegex(DiagnosticExportError, "EXPORT_ALREADY_CONSUMED"):
                diagnostic.export_once()
            self.assertEqual(reader.write_attempts, [])

    def test_wrong_recipient_private_key_cannot_decrypt(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-export-key-") as temp:
            root = Path(temp)
            investigation_id = "INV-DIAGNOSTIC"
            seed = _seed_object_state(root, investigation_id, b'{"seq":1}\n')
            reader = _ReadOnlyObjectClient(seed)
            manager = RecoveryObjectStoreStateManagerV63(reader, prefix="cbi-v64-c279-test")
            intended = X25519PrivateKey.generate()
            public_b64 = base64.b64encode(
                intended.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii")
            diagnostic = C279ExportDiagnostic(
                state_manager=manager,
                investigation_id=investigation_id,
                recipient_public_key_b64=public_b64,
                enabled=True,
            )
            envelope = diagnostic.export_once()

            with self.assertRaises(Exception):
                _decrypt_envelope(X25519PrivateKey.generate(), envelope)


if __name__ == "__main__":
    unittest.main()
