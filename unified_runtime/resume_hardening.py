"""Read-only v6.1 resume semantics for legacy and current investigations.

Resume is a recovery/read operation. It must never upgrade a legacy session or
append ``V6_RUNTIME_INITIALIZED`` merely because a caller asks for the last safe
state. Explicit start/migration paths remain the only places that may materialize
the v6 extension.
"""

from __future__ import annotations

from typing import Any

from . import v6 as _v6


class V61ResumeReadOnlyMixin:
    """Preserve the v6 resume contract without mutating durable history."""

    def resume_investigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _v6._require_object(arguments, "arguments")
        investigation_id = _v6._nonempty(args.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        extension = state.get("extension") if isinstance(state.get("extension"), dict) else {}
        return {
            "schema": "cbi.investigation-state.v6.1",
            "investigation_id": investigation_id,
            "status": "RESUMED",
            "durable": True,
            "last_safe_seq": state["events"][-1]["seq"],
            "last_safe_event_hash": state["events"][-1]["event_hash"],
            "observations": len(state["observations"]),
            "objectives": len(state["objectives"]),
            "open_material_pivots": len(self._material_pivots(state)),
            "transport_session_is_state_owner": False,
            "resume_mutated_durable_state": False,
            "legacy_adapter_read_only": extension.get("legacy_adapter_read_only") is True,
        }
