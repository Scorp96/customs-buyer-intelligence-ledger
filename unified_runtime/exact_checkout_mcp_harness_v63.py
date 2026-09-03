from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .mcp_entrypoint_v63 import resolve_active_mcp_entrypoint


class ExactCheckoutMcpHarness:
    def __init__(self, repo_root: Path, persistence_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.persistence_root = Path(persistence_root).resolve()
        self._process: subprocess.Popen[str] | None = None

    def active_entrypoint(self) -> str:
        entrypoint = resolve_active_mcp_entrypoint(self.repo_root)
        if not entrypoint:
            raise RuntimeError("ACTIVE_MCP_ENTRYPOINT_NOT_RESOLVED")
        return entrypoint

    def _environment(self, crash_after_handler: str = "") -> dict[str, str]:
        self.persistence_root.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        environment.update(
            {
                "CBI_SESSION_ROOT": str(self.persistence_root / "sessions"),
                "CBI_HOST_PENDING_ROOT": str(self.persistence_root / "host-pending"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPYCACHEPREFIX": str(self.persistence_root / "pycache"),
            }
        )
        if crash_after_handler:
            environment["CBI_V61_TEST_CRASH_AFTER_HANDLER"] = crash_after_handler
        else:
            environment.pop("CBI_V61_TEST_CRASH_AFTER_HANDLER", None)
        return environment

    @staticmethod
    def _close_streams(process: subprocess.Popen[str]) -> None:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def _rpc(
        self,
        request_id: int,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.poll() is not None:
            raise RuntimeError("MCP_PROCESS_NOT_RUNNING")
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("MCP_PROCESS_STDIO_NOT_AVAILABLE")

        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                },
                ensure_ascii=True,
            )
            + "\n"
        )
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"MCP_PROCESS_ENDED_BEFORE_RESPONSE: {stderr}")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise RuntimeError("MCP_RESPONSE_NOT_OBJECT")
        if response.get("id") != request_id:
            raise RuntimeError("MCP_RESPONSE_ID_MISMATCH")
        return response

    def start(self, *, crash_after_handler: str = "") -> None:
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("MCP_PROCESS_ALREADY_RUNNING")

        entrypoint = self.active_entrypoint()
        entrypoint_path = (self.repo_root / entrypoint).resolve()
        try:
            entrypoint_path.relative_to(self.repo_root)
        except ValueError as exc:
            raise RuntimeError("ACTIVE_MCP_ENTRYPOINT_OUTSIDE_CHECKOUT") from exc
        if not entrypoint_path.is_file():
            raise RuntimeError("ACTIVE_MCP_ENTRYPOINT_NOT_FOUND")

        self._process = subprocess.Popen(
            [sys.executable, "-B", "-Xutf8", str(entrypoint_path), "--stdio"],
            cwd=self.repo_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self._environment(crash_after_handler),
        )
        try:
            response = self._rpc(
                1,
                "initialize",
                {"protocolVersion": "2025-06-18"},
            )
            if "error" in response:
                raise RuntimeError(f"MCP_INITIALIZE_FAILED: {response['error']}")
            if "result" not in response:
                raise RuntimeError("MCP_INITIALIZE_RESULT_MISSING")
        except Exception:
            self.stop()
            raise

    def list_tool_names(self, request_id: int = 2) -> set[str]:
        response = self._rpc(request_id, "tools/list", {})
        if "error" in response:
            raise RuntimeError(f"MCP_TOOLS_LIST_FAILED: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("MCP_TOOLS_LIST_RESULT_INVALID")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("MCP_TOOLS_LIST_MISSING")
        names: set[str] = set()
        for tool in tools:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                names.add(tool["name"])
        return names

    def tool(
        self,
        request_id: int,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        raise RuntimeError("MCP_TOOL_CALL_NOT_IMPLEMENTED")

    def crash_tool(
        self,
        request_id: int,
        name: str,
        arguments: dict[str, Any],
    ) -> None:
        raise RuntimeError("MCP_CRASH_TOOL_NOT_IMPLEMENTED")

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._close_streams(process)
