#!/usr/bin/env python3
"""Test-only legacy render shim.

This fixture preserves the pre-Outreach-recovery WAL/correlation behavior while
stripping adapter control fields before the strict business render handler. It
exists only to manufacture a historical correlated OUTREACH_RENDERED event
without the newer exact result snapshot, so recovery can prove it remains
fail-closed.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import server_v61_closure_recovery as _closure  # noqa: E402

_v61 = _closure._v61
_BASE_RENDER_HANDLER = _v61._ORIGINAL_HANDLERS["render_outreach_action_card"]


def _legacy_render_runtime_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    runtime_args = copy.deepcopy(arguments)
    runtime_args.pop("idempotency_key", None)
    runtime_args.pop("expected_state_version", None)
    return _BASE_RENDER_HANDLER(runtime_args)


def _legacy_render_mcp_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return _v61._invoke_mutation(
        "render_outreach_action_card",
        _legacy_render_runtime_handler,
        arguments,
    )


_v61._server.TOOL_HANDLERS["render_outreach_action_card"] = _legacy_render_mcp_handler


def main() -> int:
    return _closure.main()


if __name__ == "__main__":
    raise SystemExit(main())
