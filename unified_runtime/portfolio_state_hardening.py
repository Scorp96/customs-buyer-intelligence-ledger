"""Final production-state portfolio safeguards discovered by Private Golden.

This overlay is intentionally narrow: it preserves the existing portfolio
projection and only fixes two production-state hazards proven by durable user
state:

* initialization-only duplicate sessions must not supersede a session that
  already contains durable research; and
* explicit historical synthetic/pending identifiers must not project as
  production work merely because older rows predate the current markers.

No source JSONL is rewritten or deleted.
"""

from __future__ import annotations

from typing import Any


class V61PortfolioStateHardeningMixin:
    """Prefer researched durable state and quarantine explicit test placeholders."""

    def _portfolio_environment(self, start: dict[str, Any]) -> str:
        environment = super()._portfolio_environment(start)
        if environment != "PRODUCTION":
            return environment

        account = start.get("account") if isinstance(start.get("account"), dict) else {}
        account_id = str(account.get("account_id") or "").strip().casefold()

        if account_id.startswith(("synth-", "synthetic-")):
            return "TEST"
        if account_id == "pending_buyer_input":
            return "PLACEHOLDER"
        return environment

    @staticmethod
    def _maturity_rank(row: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
        observations = int(row.get("observation_count") or 0)
        peers = int(row.get("peer_count") or 0)
        events = int(row.get("event_count") or 0)

        # A normal newly initialized v6 session contains only the start/runtime
        # initialization tail.  Any actual research-bearing state must win over
        # such an empty duplicate regardless of the empty session's derived
        # NOT_SATURATED label.
        has_durable_research = observations > 0 or peers > 0 or events > 2

        saturation = str(row.get("decision_saturation") or "")
        saturation_rank = {
            "SATURATED": 4,
            "NOT_SATURATED": 3,
            "PAUSED_RESOURCE_LIMIT": 2,
            "BLOCKED": 1,
        }.get(saturation, 0)
        return (
            1 if has_durable_research else 0,
            saturation_rank,
            observations,
            peers,
            events,
            str(row.get("investigation_id") or ""),
        )

    def get_portfolio_queue(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().get_portfolio_queue(arguments)
        policy = result.get("policy")
        if isinstance(policy, dict):
            policy["winner_selection"] = (
                "DURABLE_RESEARCH_PRESENT_THEN_SATURATION_THEN_"
                "OBSERVATION_PEER_EVENT_MATURITY"
            )
            policy["initialization_only_session_may_supersede_researched_session"] = False
            policy["historical_synth_ids_project_as_test"] = True
        return result
