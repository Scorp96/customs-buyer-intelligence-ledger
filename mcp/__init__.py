"""Shared MCP package bootstrap.

The production v6.1 adapter relies on sentinel file locks that must recover when
a worker dies between a durable mutation and its terminal receipt. Windows can
keep a terminated process object queryable while another process still owns a
handle, so a successful OpenProcess call alone is not proof that the process is
still executing. Install a narrow Windows-only liveness probe before importing
MCP server modules; non-Windows platforms are unchanged.
"""

from __future__ import annotations

import os


def _install_windows_process_liveness_probe() -> None:
    if os.name != "nt":
        return

    import ctypes

    from unified_runtime import resilience as _resilience

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def windows_pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True

        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            try:
                exit_code = ctypes.c_uint32()
                if not kernel32.GetExitCodeProcess(
                    handle,
                    ctypes.byref(exit_code),
                ):
                    # Query failure is not sufficient evidence to steal a lock.
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)

        # Access denied means a process exists but cannot be queried. Preserve
        # the conservative existing behavior and treat it as alive.
        return ctypes.get_last_error() == 5

    _resilience._pid_is_alive = windows_pid_is_alive


_install_windows_process_liveness_probe()
