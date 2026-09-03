from __future__ import annotations

from pathlib import Path
from typing import Any

from .mcp_entrypoint_v63 import resolve_active_mcp_entrypoint


class ExactCheckoutMcpHarness:
    def __init__(self, repo_root: Path, persistence_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.persistence_root = Path(persistence_root).resolve()

    def active_entrypoint(self) -> str:
        entrypoint = resolve_active_mcp_entrypoint(self.repo_root)
        if not entrypoint:
            raise RuntimeError("ACTIVE_MCP_ENTRYPOINT_NOT_RESOLVED")
        return entrypoint

    def start(self, *, crash_after_handler: str = "") -> None:
        raise RuntimeError("MCP_PROCESS_START_NOT_IMPLEMENTED")

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
        return None
