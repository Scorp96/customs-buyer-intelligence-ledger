from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from .protocol import ProtocolError, canonical_json_v1, parse_strict_json


class WindowsSecurityError(RuntimeError):
    """Raised when the Windows worker secret or state boundary cannot be proved."""


MAGIC = b"ASTRA_SECRET_V1\0"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4
_ALLOWED_SECRET_KEYS = {"task_hmac_key_b64", "receipt_hmac_key_b64", "github_token"}
_SID_RE = re.compile(r"^S-\d+(?:-\d+)+$")


@dataclass(frozen=True)
class SecretBundle:
    task_hmac_key: bytes
    receipt_hmac_key: bytes
    github_token: str

    def __post_init__(self) -> None:
        for name, value in (
            ("task_hmac_key", self.task_hmac_key),
            ("receipt_hmac_key", self.receipt_hmac_key),
        ):
            if not isinstance(value, bytes) or len(value) < 32:
                raise WindowsSecurityError(f"{name} must be at least 32 random bytes")
        if self.task_hmac_key == self.receipt_hmac_key:
            raise WindowsSecurityError("task and receipt HMAC keys must be independent")
        if (
            not isinstance(self.github_token, str)
            or not self.github_token.strip()
            or "\x00" in self.github_token
        ):
            raise WindowsSecurityError("github_token must be non-empty text without NUL")

    def to_clear_bytes(self) -> bytes:
        return canonical_json_v1(
            {
                "task_hmac_key_b64": base64.b64encode(self.task_hmac_key).decode("ascii"),
                "receipt_hmac_key_b64": base64.b64encode(self.receipt_hmac_key).decode("ascii"),
                "github_token": self.github_token,
            }
        )

    @classmethod
    def from_clear_bytes(cls, raw: bytes) -> "SecretBundle":
        if not isinstance(raw, bytes):
            raise WindowsSecurityError("secret cleartext must be bytes")
        try:
            payload = parse_strict_json(raw.decode("utf-8"))
        except (UnicodeError, ProtocolError) as exc:
            raise WindowsSecurityError("secret cleartext is malformed") from exc
        if not isinstance(payload, dict) or set(payload) != _ALLOWED_SECRET_KEYS:
            raise WindowsSecurityError("secret bundle has an invalid schema")
        try:
            task_key = base64.b64decode(payload["task_hmac_key_b64"], validate=True)
            receipt_key = base64.b64decode(payload["receipt_hmac_key_b64"], validate=True)
        except (TypeError, ValueError) as exc:
            raise WindowsSecurityError("secret HMAC keys are not valid base64") from exc
        return cls(
            task_hmac_key=task_key,
            receipt_hmac_key=receipt_key,
            github_token=payload["github_token"],
        )


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsSecurityError("Windows DPAPI is available only on Windows")


def _input_blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    if not isinstance(data, bytes) or not data:
        raise WindowsSecurityError("DPAPI input must be non-empty bytes")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _windows_libraries() -> tuple[Any, Any]:
    _require_windows()
    try:
        crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise WindowsSecurityError("Windows cryptographic libraries are unavailable") from exc

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32


def _copy_and_free(blob: _DATA_BLOB, kernel32: Any) -> bytes:
    if not blob.pbData or not blob.cbData:
        raise WindowsSecurityError("DPAPI returned an empty result")
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect_machine_secret(clear: bytes) -> bytes:
    crypt32, kernel32 = _windows_libraries()
    input_blob, _input_buffer = _input_blob(clear)
    output_blob = _DATA_BLOB()
    flags = _CRYPTPROTECT_UI_FORBIDDEN | _CRYPTPROTECT_LOCAL_MACHINE
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "ASTRA Worker secret",
        None,
        None,
        None,
        flags,
        ctypes.byref(output_blob),
    ):
        code = ctypes.get_last_error()
        raise WindowsSecurityError(f"CryptProtectData failed with Windows error {code}")
    return _copy_and_free(output_blob, kernel32)


def unprotect_machine_secret(blob: bytes) -> bytes:
    crypt32, kernel32 = _windows_libraries()
    input_blob, _input_buffer = _input_blob(blob)
    output_blob = _DATA_BLOB()
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        code = ctypes.get_last_error()
        raise WindowsSecurityError(f"CryptUnprotectData failed with Windows error {code}")
    try:
        return _copy_and_free(output_blob, kernel32)
    finally:
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))


def write_secret_bundle(path: Path, bundle: SecretBundle) -> None:
    _require_windows()
    target = Path(path)
    if not target.parent.is_dir():
        raise WindowsSecurityError("secret parent directory does not exist")
    protected = MAGIC + protect_machine_secret(bundle.to_clear_bytes())
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(target.parent), prefix=f".{target.name}.", delete=False
        ) as handle:
            handle.write(protected)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
        temp_path = None
    except OSError as exc:
        raise WindowsSecurityError("cannot persist protected worker secrets") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def read_secret_bundle(path: Path) -> SecretBundle:
    try:
        stored = Path(path).read_bytes()
    except OSError as exc:
        raise WindowsSecurityError("cannot read worker secret bundle") from exc
    if not stored.startswith(MAGIC) or len(stored) <= len(MAGIC):
        raise WindowsSecurityError("worker secret file is not an ASTRA DPAPI bundle")
    clear = unprotect_machine_secret(stored[len(MAGIC) :])
    return SecretBundle.from_clear_bytes(clear)


def _programdata_worker_root() -> Path:
    _require_windows()
    program_data = os.environ.get("ProgramData")
    if not program_data:
        raise WindowsSecurityError("ProgramData is unavailable")
    return (Path(program_data) / "ASTRAWorker").resolve()


def validate_worker_state_location(path: Path, service_sid: str) -> None:
    """Validate location now and fail closed until the installer-owned ACL verifier approves it.

    The ACL verifier entry point is intentionally a separate trusted-installation surface.  Before
    that CLI mode exists, a correctly located path still fails closed rather than being treated as
    ACL-safe by inference.
    """

    _require_windows()
    if not isinstance(service_sid, str) or _SID_RE.fullmatch(service_sid) is None:
        raise WindowsSecurityError("service_sid is not a valid SID string")
    root = _programdata_worker_root()
    target = Path(path).resolve()
    try:
        common = os.path.commonpath([str(root), str(target)])
    except ValueError as exc:
        raise WindowsSecurityError("worker state path is outside ProgramData/ASTRAWorker") from exc
    if os.path.normcase(common) != os.path.normcase(str(root)):
        raise WindowsSecurityError("worker state path is outside ProgramData/ASTRAWorker")

    command = [
        sys.executable,
        "-m",
        "astra_worker.cli",
        "verify-acl",
        "--path",
        str(target),
        "--service-sid",
        service_sid,
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "GIT_"))
    }
    environment["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(
            command,
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WindowsSecurityError("worker ACL verifier is unavailable") from exc
    if completed.returncode != 0 or completed.stdout.strip() != "ASTRA_ACL_OK":
        raise WindowsSecurityError("worker ACL verification did not establish the required ACL")
