"""Non-destructive production portfolio governance for v6.1.

The scheduler must not research the same canonical account twice merely because
historical session files exist. This layer derives lifecycle/environment views
without deleting or rewriting any append-only investigation history.
"""

from __future__ import annotations

from typing import Any

from . import v6 as _v6


PORTFOLIO_LIFECYCLES = (
    "ACTIVE",
    "SUPERSEDED",
    "ARCHIVED",
    "TEST",
    "MIGRATION_ONLY",
    "QUARANTINED",
    "PLACEHOLDER",
)
PORTFOLIO_ENVIRONMENTS = ("PRODUCTION", "TEST", "MIGRATION", "PLACEHOLDER")

_EXPLICIT_NON_PRODUCTION_MARKERS = {
    "plugin_runtime_check_only",
    "pending_user_input",
    "pending_user_target",
}


class V61PortfolioHardeningMixin:
    """Make the portfolio scheduler canonical-account aware and test-safe."""

    @staticmethod
    def _portfolio_scope(start: dict[str, Any]) -> str:
        raw_input = start.get("input") if isinstance(start.get("input"), dict) else {}
        return str(
            raw_input.get("investigation_scope")
            or start.get("investigation_scope")
            or "DEFAULT"
        ).strip() or "DEFAULT"

    @staticmethod
    def _portfolio_environment(start: dict[str, Any]) -> str:
        account = start.get("account") if isinstance(start.get("account"), dict) else {}
        raw_input = start.get("input") if isinstance(start.get("input"), dict) else {}
        explicit = str(raw_input.get("portfolio_environment") or "").upper().strip()
        if explicit in PORTFOLIO_ENVIRONMENTS:
            return explicit
        if raw_input.get("synthetic") is True or str(account.get("country") or "").casefold() == "synthetic":
            return "TEST"
        marker_values = {
            str(account.get("account_id") or "").casefold(),
            str(account.get("name") or "").casefold(),
        }
        if marker_values & _EXPLICIT_NON_PRODUCTION_MARKERS:
            return "PLACEHOLDER"
        if str(raw_input.get("portfolio_lifecycle") or "").upper() == "MIGRATION_ONLY":
            return "MIGRATION"
        return "PRODUCTION"

    @staticmethod
    def _explicit_lifecycle(start: dict[str, Any], environment: str) -> str:
        raw_input = start.get("input") if isinstance(start.get("input"), dict) else {}
        explicit = str(raw_input.get("portfolio_lifecycle") or "").upper().strip()
        if explicit in PORTFOLIO_LIFECYCLES:
            return explicit
        if environment == "TEST":
            return "TEST"
        if environment == "PLACEHOLDER":
            return "PLACEHOLDER"
        if environment == "MIGRATION":
            return "MIGRATION_ONLY"
        return "ACTIVE"

    @staticmethod
    def _maturity_rank(row: dict[str, Any]) -> tuple[int, int, int, int, str]:
        saturation = str(row.get("decision_saturation") or "")
        saturation_rank = {
            "SATURATED": 4,
            "NOT_SATURATED": 3,
            "PAUSED_RESOURCE_LIMIT": 2,
            "BLOCKED": 1,
        }.get(saturation, 0)
        return (
            saturation_rank,
            int(row.get("observation_count") or 0),
            int(row.get("peer_count") or 0),
            int(row.get("event_count") or 0),
            str(row.get("investigation_id") or ""),
        )

    def _portfolio_row(self, investigation_id: str) -> dict[str, Any]:
        state = self._v6_state(investigation_id)
        start = state["start"]
        account = self.get_account_state({"investigation_id": investigation_id})
        next_work = self.get_next_research_objectives({
            "investigation_id": investigation_id,
            "limit": 1,
        })
        environment = self._portfolio_environment(start)
        lifecycle = self._explicit_lifecycle(start, environment)
        scope = self._portfolio_scope(start)
        account_id = str(account["account"].get("account_id") or "")
        return {
            "investigation_id": investigation_id,
            "account_id": account_id,
            "account_name": account["account"].get("name"),
            "investigation_scope": scope,
            "canonical_scope_key": f"{account_id}::{scope}",
            "environment": environment,
            "lifecycle": lifecycle,
            "commercial_value_grade": account["commercial_value"]["commercial_value_grade"],
            "research_confidence": account["research_confidence"]["research_confidence"],
            "decision_saturation": account["decision_saturation"]["status"],
            "next_eiv": next_work["objectives"][0]["eiv"] if next_work["objectives"] else 0.0,
            "budget": next_work["budget"],
            "observation_count": len(state["observations"]),
            "peer_count": len(state["peers"]),
            "event_count": len(state["events"]),
            "last_safe_seq": state["events"][-1]["seq"],
            "last_safe_event_hash": state["events"][-1]["event_hash"],
        }

    def get_portfolio_queue(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _v6._require_object(arguments, "arguments")
        limit = int(args.get("limit", 100))
        if not 1 <= limit <= 1000:
            raise _v6.ValidationError("limit must be 1-1000")
        include_non_active = args.get("include_non_active") is True
        include_non_production = args.get("include_non_production") is True

        scanned: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        for path in sorted(self.store.root.glob("INV-*.jsonl")):
            try:
                scanned.append(self._portfolio_row(path.stem))
            except (_v6.ValidationError, KeyError, TypeError, ValueError) as exc:
                quarantined.append({
                    "investigation_id": path.stem,
                    "lifecycle": "QUARANTINED",
                    "environment": "PRODUCTION",
                    "status": "QUARANTINED_READ_ONLY",
                    "error": str(exc),
                })

        active_candidates = [
            row
            for row in scanned
            if row["lifecycle"] == "ACTIVE" and row["environment"] == "PRODUCTION"
        ]
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in active_candidates:
            groups.setdefault(row["canonical_scope_key"], []).append(row)

        active_ids: set[str] = set()
        superseded_by: dict[str, str] = {}
        duplicate_groups: dict[str, list[str]] = {}
        for scope_key, rows in groups.items():
            winner = max(rows, key=self._maturity_rank)
            active_ids.add(winner["investigation_id"])
            if len(rows) > 1:
                duplicate_groups[scope_key] = [row["investigation_id"] for row in rows]
            for row in rows:
                if row["investigation_id"] != winner["investigation_id"]:
                    superseded_by[row["investigation_id"]] = winner["investigation_id"]

        projected: list[dict[str, Any]] = []
        for row in scanned:
            item = dict(row)
            investigation_id = item["investigation_id"]
            if investigation_id in superseded_by:
                item["lifecycle"] = "SUPERSEDED"
                item["superseded_by"] = superseded_by[investigation_id]
            elif item["lifecycle"] == "ACTIVE" and item["environment"] == "PRODUCTION":
                item["lifecycle"] = "ACTIVE" if investigation_id in active_ids else "SUPERSEDED"
            projected.append(item)

        visible = []
        for row in projected:
            if not include_non_production and row["environment"] != "PRODUCTION":
                continue
            if not include_non_active and row["lifecycle"] != "ACTIVE":
                continue
            visible.append(row)
        if include_non_active:
            visible.extend(quarantined)

        grade_rank = {grade: index for index, grade in enumerate(_v6.COMMERCIAL_VALUE_GRADES)}
        visible.sort(
            key=lambda row: (
                0 if row.get("lifecycle") == "ACTIVE" else 1,
                grade_rank.get(row.get("commercial_value_grade", "NQ"), 99),
                -float(row.get("next_eiv", 0.0)),
                str(row.get("investigation_id") or ""),
            )
        )
        queue = visible[:limit]

        excluded_non_production = [
            row for row in projected if row["environment"] != "PRODUCTION"
        ]
        superseded = [row for row in projected if row["lifecycle"] == "SUPERSEDED"]
        return {
            "schema": "cbi.portfolio-queue.v6.1",
            "count": len(queue),
            "active_count": sum(row.get("lifecycle") == "ACTIVE" for row in projected),
            "total_scanned": len(projected) + len(quarantined),
            "superseded_count": len(superseded),
            "excluded_non_production_count": len(excluded_non_production),
            "quarantined_count": len(quarantined),
            "canonical_duplicate_groups": duplicate_groups,
            "queue": queue,
            "policy": {
                "one_active_investigation_per_canonical_account_and_scope": True,
                "historical_sessions_deleted": False,
                "test_and_placeholder_sessions_excluded_by_default": True,
                "winner_selection": "SATURATION_THEN_OBSERVATION_PEER_EVENT_MATURITY",
            },
        }

    def resume_investigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().resume_investigation(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        portfolio = self.get_portfolio_queue({
            "limit": 1000,
            "include_non_active": True,
            "include_non_production": True,
        })
        priority = next(
            (row for row in portfolio.get("queue", []) if row.get("investigation_id") == investigation_id),
            None,
        )
        if isinstance(result.get("last_safe_state"), dict):
            result["last_safe_state"]["portfolio_priority"] = priority
        result["portfolio_priority"] = priority
        return result
