#!/usr/bin/env python3
"""Test-only partial bundle crash shim.

This server deliberately exits after WAL PREPARED and one correlated
V6_OBSERVATION_COMPILED prefix event, before any final
V6_RESEARCH_BUNDLE_COMPILED summary can exist. It is used only to prove that
production recovery fails closed on a partial durable bundle prefix.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_bundle_recovery as _bundle  # noqa: E402


_v61 = _bundle._v61
_RUNTIME = _bundle._RUNTIME


def _partial_runtime_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    investigation_id = str(arguments.get("investigation_id") or "").strip()
    if not investigation_id:
        raise RuntimeError("partial bundle test requires investigation_id")
    _RUNTIME.store.append(
        investigation_id,
        "V6_OBSERVATION_COMPILED",
        {
            "schema": "cbi.test.partial-bundle-prefix.v1",
            "investigation_id": investigation_id,
            "test_only_partial_prefix": True,
        },
    )
    os._exit(91)


def _partial_mcp_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return _v61._invoke_mutation(
        "compile_and_append_research_bundle",
        _partial_runtime_handler,
        arguments,
    )


_v61._server.TOOL_HANDLERS["compile_and_append_research_bundle"] = _partial_mcp_handler


def main() -> int:
    return _bundle.main()


if __name__ == "__main__":
    raise SystemExit(main())
