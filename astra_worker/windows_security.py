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
_SERVICE_SID_RE = re.compile(r"S-1-5-80(?:-\d+)+")
_SYSTEM_SID = "S-1-5-18"
_ADMINISTRATORS_SID = "S-1-5-32-544"
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_DACL_PROTECTED = 0x1000
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0x00
_ACCESS_DENIED_ACE_TYPE = 0x01
_FILE_ALL_ACCESS = 0x001F01FF
_GENERIC_ALL = 0x10000000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


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


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
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


def _security_libraries() -> tuple[Any, Any]:
    _require_windows()
    try:
        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise WindowsSecurityError("Windows security libraries are unavailable") from exc

    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return advapi32, kernel32


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


def default_worker_state_root() -> Path:
    """Return the only default persistent worker state root."""

    return _programdata_worker_root()


def resolve_service_sid(service_name: str = "ASTRAWorker") -> str:
    """Resolve the Windows virtual service SID using a fixed sc.exe query."""

    _require_windows()
    if not isinstance(service_name, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", service_name):
        raise WindowsSecurityError("service name is invalid")
    try:
        completed = subprocess.run(
            ["sc.exe", "showsid", service_name],
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WindowsSecurityError("service SID query is unavailable") from exc
    if completed.returncode != 0:
        raise WindowsSecurityError("service SID query failed")
    stdout = completed.stdout if isinstance(completed.stdout, bytes) else b""
    matches = [value.decode("ascii") for value in re.findall(br"S-1-5-80(?:-\d+)+", stdout)]
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1 or _SID_RE.fullmatch(unique[0]) is None:
        raise WindowsSecurityError("service SID query returned an ambiguous result")
    return unique[0]


def require_elevated_administrator() -> None:
    """Fail closed unless the current one-time provisioning process is elevated."""

    _require_windows()
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError) as exc:
        raise WindowsSecurityError("administrator token could not be determined") from exc
    if not is_admin:
        raise WindowsSecurityError("secret provisioning requires an elevated administrator")


def _sid_string(advapi32: Any, kernel32: Any, sid_address: int) -> str:
    if not sid_address:
        raise WindowsSecurityError("ACL ACE contains an empty SID")
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid_address), ctypes.byref(text)):
        code = ctypes.get_last_error()
        raise WindowsSecurityError(f"ConvertSidToStringSidW failed with Windows error {code}")
    try:
        value = text.value
        if not value or _SID_RE.fullmatch(value) is None:
            raise WindowsSecurityError("ACL ACE contains an invalid SID")
        return value
    finally:
        if text:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _acl_for_path(path: Path) -> tuple[dict[str, int], set[str], bool]:
    advapi32, kernel32 = _security_libraries()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise WindowsSecurityError(f"GetNamedSecurityInfoW failed with Windows error {result}")
    if not descriptor:
        raise WindowsSecurityError("Windows returned no security descriptor")
    try:
        if not dacl:
            raise WindowsSecurityError("worker state has a NULL DACL")

        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            code = ctypes.get_last_error()
            raise WindowsSecurityError(
                f"GetSecurityDescriptorControl failed with Windows error {code}"
            )

        info = _ACL_SIZE_INFORMATION()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(info),
            ctypes.sizeof(info),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            code = ctypes.get_last_error()
            raise WindowsSecurityError(f"GetAclInformation failed with Windows error {code}")

        grants: dict[str, int] = {}
        denies: set[str] = set()
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                code = ctypes.get_last_error()
                raise WindowsSecurityError(f"GetAce failed with Windows error {code}")
            header = _ACE_HEADER.from_address(ace.value)
            if header.AceSize < ctypes.sizeof(_ACE_HEADER) + ctypes.sizeof(wintypes.DWORD) + 4:
                raise WindowsSecurityError("ACL ACE is too small")
            if header.AceType not in {_ACCESS_ALLOWED_ACE_TYPE, _ACCESS_DENIED_ACE_TYPE}:
                raise WindowsSecurityError("worker ACL contains an unsupported ACE type")
            mask_address = ace.value + ctypes.sizeof(_ACE_HEADER)
            mask = wintypes.DWORD.from_address(mask_address).value
            sid_address = mask_address + ctypes.sizeof(wintypes.DWORD)
            sid = _sid_string(advapi32, kernel32, sid_address)
            if header.AceType == _ACCESS_ALLOWED_ACE_TYPE:
                grants[sid] = grants.get(sid, 0) | int(mask)
            else:
                denies.add(sid)
        return grants, denies, bool(control.value & _SE_DACL_PROTECTED)
    finally:
        kernel32.LocalFree(descriptor)


def _has_full_control(mask: int) -> bool:
    return bool(mask & _GENERIC_ALL) or (mask & _FILE_ALL_ACCESS) == _FILE_ALL_ACCESS


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(os.lstat(path), "st_file_attributes", 0))
    except OSError as exc:
        raise WindowsSecurityError("worker state path could not be inspected") from exc
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _state_paths(root: Path) -> list[Path]:
    paths = [root]
    try:
        for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            parent = Path(directory)
            for name in list(dirnames):
                child = parent / name
                if _is_reparse_point(child):
                    raise WindowsSecurityError("worker state contains a reparse-point directory")
                paths.append(child)
            for name in filenames:
                child = parent / name
                if _is_reparse_point(child):
                    raise WindowsSecurityError("worker state contains a reparse-point file")
                paths.append(child)
    except OSError as exc:
        raise WindowsSecurityError("worker state tree could not be enumerated") from exc
    return paths


def _run_icacls(path: Path, *arguments: str) -> None:
    try:
        completed = subprocess.run(
            ["icacls.exe", str(path), *arguments],
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WindowsSecurityError("worker ACL hardening command is unavailable") from exc
    if completed.returncode != 0:
        raise WindowsSecurityError("worker ACL hardening command failed")


def harden_worker_acl(
    path: Path,
    service_sid: str,
    *,
    enforce_programdata: bool = True,
) -> None:
    """Replace the worker state DACL with the exact three-trustee contract."""

    _require_windows()
    if not isinstance(service_sid, str) or _SID_RE.fullmatch(service_sid) is None:
        raise WindowsSecurityError("service_sid is not a valid SID string")
    root = Path(path).resolve()
    if not root.is_dir():
        raise WindowsSecurityError("worker state root is not a directory")
    if _is_reparse_point(root):
        raise WindowsSecurityError("worker state root cannot be a reparse point")

    if enforce_programdata:
        expected = _programdata_worker_root()
        if os.path.normcase(str(root)) != os.path.normcase(str(expected)):
            raise WindowsSecurityError("worker ACL hardening is restricted to ProgramData/ASTRAWorker")

    paths = _state_paths(root)
    allowed = (service_sid, _SYSTEM_SID, _ADMINISTRATORS_SID)
    allowed_set = set(allowed)

    for current in paths:
        _run_icacls(current, "/inheritance:r")
        permission = "(OI)(CI)F" if current.is_dir() else "F"
        _run_icacls(
            current,
            "/grant:r",
            *(f"*{sid}:{permission}" for sid in allowed),
        )

        grants, denies, _protected = _acl_for_path(current)
        for sid in sorted(set(grants) - allowed_set):
            _run_icacls(current, "/remove:g", f"*{sid}")
        for sid in sorted(denies):
            _run_icacls(current, "/remove:d", f"*{sid}")

    verify_worker_acl(root, service_sid, enforce_programdata=enforce_programdata)


def verify_worker_acl(
    path: Path,
    service_sid: str,
    *,
    enforce_programdata: bool = True,
) -> None:
    """Prove that the worker state tree grants access only to three trusted identities."""

    _require_windows()
    if not isinstance(service_sid, str) or _SID_RE.fullmatch(service_sid) is None:
        raise WindowsSecurityError("service_sid is not a valid SID string")
    root = Path(path).resolve()
    if not root.is_dir():
        raise WindowsSecurityError("worker state root is not a directory")
    if _is_reparse_point(root):
        raise WindowsSecurityError("worker state root cannot be a reparse point")

    if enforce_programdata:
        expected = _programdata_worker_root()
        if os.path.normcase(str(root)) != os.path.normcase(str(expected)):
            raise WindowsSecurityError("worker ACL verification is restricted to ProgramData/ASTRAWorker")

    allowed = {service_sid, _SYSTEM_SID, _ADMINISTRATORS_SID}
    for index, current in enumerate(_state_paths(root)):
        grants, denies, protected = _acl_for_path(current)
        if index == 0 and not protected:
            raise WindowsSecurityError("worker state root still inherits parent ACL entries")
        if set(grants) != allowed:
            raise WindowsSecurityError("worker state grants access to an unexpected identity")
        if denies & allowed:
            raise WindowsSecurityError("worker state denies a required trusted identity")
        for sid in allowed:
            if not _has_full_control(grants[sid]):
                raise WindowsSecurityError("worker state trusted identity lacks Full Control")


def validate_worker_state_location(path: Path, service_sid: str) -> None:
    """Validate fixed location and prove ACL safety through an isolated verifier process."""

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
