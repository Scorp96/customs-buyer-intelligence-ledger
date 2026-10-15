"""Read-only, bounded, stable WAL snapshot with Windows delete-share permission.

ISOLATED VALIDATION ONLY. On Windows opens the file handle with
FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE so this verifier's
file handle does not, by itself, deny a writer's atomic os.replace.
It does not grant WAL authenticity; caller must check record/Session/WAL hashes.
"""
from __future__ import annotations

import os
from pathlib import Path


def _windows_read_delete_shared(path: Path, max_bytes: int) -> tuple[bytes, int]:
    import ctypes
    from ctypes import wintypes

    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    DWORD = wintypes.DWORD

    class _FileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", DWORD),
            ("nFileSizeHigh", DWORD),
            ("nFileSizeLow", DWORD),
            ("nNumberOfLinks", DWORD),
            ("nFileIndexHigh", DWORD),
            ("nFileIndexLow", DWORD),
        ]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR, DWORD, DWORD, wintypes.LPVOID, DWORD, DWORD, wintypes.HANDLE
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    api.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, DWORD,
        ctypes.POINTER(DWORD), wintypes.LPVOID,
    ]
    api.ReadFile.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL

    handle = api.CreateFileW(
        str(path), GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, None,
    )
    if handle is None or int(handle) == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = _FileInformation()
        if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("WAL file reparse point forbidden")
        length = (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow)
        if not (0 < length <= max_bytes):
            raise OSError("WAL size outside configured read limit")
        buf = ctypes.create_string_buffer(length)
        read = DWORD(0)
        if not api.ReadFile(handle, buf, length, ctypes.byref(read), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if int(read.value) != length:
            raise OSError("WAL short read")
        index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
        return buf.raw[:length], index
    finally:
        api.CloseHandle(handle)


def read_consistent_wal_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Conservative snapshot: any replacement, truncation or anomaly fails.

    Only a directory controlled by the trusted Host is admissible; this
    function is intentionally NOT a generic path-reading MCP tool.
    """
    path = Path(path)
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("invalid WAL read limit")
    if path.is_symlink() or not path.is_file():
        raise OSError("WAL path invalid, missing or symlink")
    before = path.stat()
    if not 0 < before.st_size <= max_bytes:
        raise OSError("WAL file size out of bounds")
    if os.name == "nt":
        payload, opened_index = _windows_read_delete_shared(path, max_bytes)
        if opened_index != (int(before.st_ino) & ((1 << 64) - 1)):
            raise OSError("WAL handle identity not equal to pre-read path")
    else:
        payload = path.read_bytes()
    after = path.stat()
    if (
        len(payload) != before.st_size
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise OSError("WAL identity changed during read")
    return payload
