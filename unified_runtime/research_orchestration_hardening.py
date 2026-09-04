"""Research-orchestration hardening for CBI v6.1/v6.2.

This overlay intentionally changes only derived planning, route, and completion
views. It does not mutate Evidence, Information History, the hash chain, WAL,
canonical identity, CRM state, outreach sends, or object-store persistence.
"""

from __future__ import annotations

from typing import Any

from .errors import ValidationError


ROOT_IDENTITY_CLAIMS = ("identity.legal_entity", "identity.ultimate_buyer")
ROOT_IDENTITY_BLOCKING_STATES = {
    "CONFLICTED",
    "REFUTED",
    "BLOCKED",
    "SEARCHING",
    "UNSEEN",
}
STRONG_DIRECT_ROUTE_STATES = {
    "CURRENT",
    "CURRENT_CONFIRMED",
}
SUPPORTED_ROUTE_CHANNELS = {
    "EMAIL",
    "PHONE",
    "WHATSAPP",
    "ZALO",
    "SOCIAL",
    "FORM",
}
SOFT_BUDGET_STATUS = "PAUSED_RESOURCE_LIMIT"


class V61ResearchOrchestrationHardeningMixin:
    """Keep research exploratory while preserving evidence and route gates."""

    @staticmethod
    def _investigation_id(arguments: dict[str, Any]) -> str:
        value = str(arguments.get("investigation_id") or "").strip()
        if not value:
            raise ValueError("investigation_id is required")
        return value

    def _information_route_warnings(
        self,
        record: dict[str, Any],
        account_id: str,
    ) -> list[str]:
        """Preserve lower route gates while accepting CURRENT_CONFIRMED."""
        warnings = list(super()._information_route_warnings(record, account_id))
        temporal_status = str(record.get("temporal_status") or "").upper()
        if temporal_status in STRONG_DIRECT_ROUTE_STATES:
            warnings = [
                warning
                for warning in warnings
                if warning != "CONTACT_IS_NOT_CONFIRMED_CURRENT"
            ]
        elif record.get("outreach_eligible_claimed") is True:
            warnings.append("CONTACT_IS_NOT_CONFIRMED_CURRENT")
        if record.get("conflicts_with_information_ids"):
            warnings.append("INFORMATION_ROUTE_HAS_ACTIVE_CONFLICT")
        return sorted(set(warnings))

    @staticmethod
    def _remaining_units(result: dict[str, Any]) -> float | None:
        budget = result.get("budget")
        if not isinstance(budget, dict):
            return None
        try:
            return float(budget.get("remaining_units"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _material_objectives(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        material: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("material"):
                continue
            try:
                eiv = float(row.get("eiv", 0.0))
            except (TypeError, ValueError):
                eiv = 0.0
            if eiv > 0.0:
                material.append(row)
        material.sort(key=lambda row: float(row.get("eiv", 0.0)), reverse=True)
        return material

    def get_next_research_objectives(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(super().get_next_research_objectives(arguments))
        objectives = list(result.get("objectives") or [])
        deferred = list(result.get("deferred_objectives") or [])
        remaining = self._remaining_units(result)

        if result.get("status") == SOFT_BUDGET_STATUS and not objectives:
            material = self._material_objectives(deferred)
            if material:
                raw_limit = arguments.get("limit")
                try:
                    limit = max(1, int(raw_limit)) if raw_limit is not None else len(material)
                except (TypeError, ValueError):
                    limit = len(material)
                selected = material[:limit]
                selected_ids = {id(row) for row in selected}
                result["legacy_status"] = str(result.get("status") or SOFT_BUDGET_STATUS)
                result["objectives"] = selected
                result["deferred_objectives"] = [
                    row for row in deferred if id(row) not in selected_ids
                ]
                result["resource_state"] = "SOFT_BUDGET_EXCEEDED"
                result["research_action"] = "CONTINUE_HIGH_EIV_RESEARCH"
                result["soft_budget_exceeded"] = True
                return result

        result["resource_state"] = (
            "EXHAUSTED" if remaining is not None and remaining <= 0 else "WITHIN_BUDGET"
        )
        result["research_action"] = (
            "CONTINUE_HIGH_EIV_RESEARCH" if objectives else "NO_HIGH_EIV_WORK"
        )
        result["soft_budget_exceeded"] = False
        return result

    @staticmethod
    def _route_payload(
        raw: dict[str, Any],
        *,
        account_id: str,
        source_kind: str,
        evidence_ids: list[str],
        observation_id: str | None = None,
        information_id: str | None = None,
    ) -> dict[str, Any] | None:
        channel = str(raw.get("channel") or raw.get("kind") or "").strip().upper()
        value = str(raw.get("value") or "").strip()
        if not evidence_ids:
            return None
        if channel not in SUPPORTED_ROUTE_CHANNELS or not value:
            return None
        if raw.get("verified") is not True:
            return None
        if raw.get("masked") is True:
            return None
        if raw.get("guessed") is True:
            return None
        if channel in {"WHATSAPP", "ZALO"} and raw.get("channel_proof") is not True:
            return None
        route = {
            "kind": channel,
            "value": value,
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "owner_entity_id": account_id,
            "evidence_ids": list(evidence_ids),
            "route_scope": "BUYER_DIRECT",
            "source": source_kind,
        }
        if observation_id:
            route["observation_id"] = observation_id
        if information_id:
            route["information_id"] = information_id
        return route

    @staticmethod
    def _compiled_route_rejection_reasons(
        observation: dict[str, Any],
        *,
        account_id: str,
    ) -> list[str]:
        reasons: list[str] = []
        if observation.get("result") != "POSITIVE":
            reasons.append("RESULT_NOT_POSITIVE")
        if observation.get("owner_type") != "ACCOUNT":
            reasons.append("OWNER_TYPE_NOT_ACCOUNT")
        if observation.get("owner_id") != account_id:
            reasons.append("OWNER_ID_NOT_ROOT_ACCOUNT")
        evidence_id = str(observation.get("evidence_id") or "").strip()
        if not evidence_id:
            reasons.append("EVIDENCE_ID_REQUIRED")
        source = observation.get("source")
        if not isinstance(source, dict):
            reasons.append("SOURCE_REQUIRED")
        else:
            freshness = str(source.get("freshness") or "").upper()
            if freshness not in STRONG_DIRECT_ROUTE_STATES:
                reasons.append("FRESHNESS_NOT_STRONG_DIRECT")
        value = observation.get("value")
        if not isinstance(value, dict):
            reasons.append("ROUTE_VALUE_OBJECT_REQUIRED")
            return sorted(set(reasons))
        channel = str(value.get("channel") or value.get("kind") or "").strip().upper()
        route_value = str(value.get("value") or "").strip()
        if channel not in SUPPORTED_ROUTE_CHANNELS:
            reasons.append("UNSUPPORTED_ROUTE_CHANNEL")
        if not route_value:
            reasons.append("ROUTE_VALUE_REQUIRED")
        if value.get("verified") is not True:
            reasons.append("ROUTE_NOT_VERIFIED")
        if value.get("masked") is True:
            reasons.append("MASKED_ROUTE")
        if value.get("guessed") is True:
            reasons.append("GUESSED_ROUTE")
        if channel in {"WHATSAPP", "ZALO"} and value.get("channel_proof") is not True:
            reasons.append(f"{channel}_CHANNEL_NOT_PROVEN")
        return sorted(set(reasons))

    def _compiled_company_routes(
        self,
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        account_id = state["start"]["account"]["account_id"]
        routes: list[dict[str, Any]] = []
        for observation in state.get("observations", {}).values():
            if not isinstance(observation, dict):
                continue
            if observation.get("claim_key") != "contact.company_route":
                continue
            if self._compiled_route_rejection_reasons(
                observation, account_id=account_id
            ):
                continue
            value = observation.get("value")
            if not isinstance(value, dict):
                continue
            route = self._route_payload(
                value,
                account_id=account_id,
                source_kind="COMPILED_OBSERVATION",
                evidence_ids=[str(observation["evidence_id"])],
                observation_id=str(observation.get("observation_id") or "") or None,
            )
            if route:
                routes.append(route)
        return routes

    def _information_company_routes(
        self,
        investigation_id: str,
        account_id: str,
    ) -> list[dict[str, Any]]:
        """Recompute current Information route eligibility without rewriting history."""
        try:
            compat_state = self._state(investigation_id)
        except (AttributeError, KeyError):
            return []
        records_by_id = compat_state.get("information_records") or {}
        if not isinstance(records_by_id, dict):
            return []
        evidence_index = compat_state.get("evidence") or {}
        existing_ids = set(records_by_id)
        superseded_ids = {
            str(item)
            for record in records_by_id.values()
            if isinstance(record, dict)
            for item in (record.get("supersedes_information_ids") or [])
            if str(item) in existing_ids
        }

        routes: list[dict[str, Any]] = []
        for information_id, record in records_by_id.items():
            if not isinstance(record, dict):
                continue
            if str(information_id) in superseded_ids:
                continue
            if record.get("outreach_eligible_claimed") is not True:
                continue
            if self._information_route_warnings(record, account_id):
                continue
            evidence_ids = [str(item) for item in (record.get("evidence_ids") or [])]
            if any(evidence_id not in evidence_index for evidence_id in evidence_ids):
                continue
            unresolved_lineage = [
                str(item)
                for field in ("supersedes_information_ids", "conflicts_with_information_ids")
                for item in (record.get(field) or [])
                if str(item) not in existing_ids
            ]
            if unresolved_lineage:
                continue
            value = record.get("value")
            if not isinstance(value, dict):
                continue
            route = self._route_payload(
                value,
                account_id=account_id,
                source_kind="INFORMATION_HISTORY_DERIVED",
                evidence_ids=evidence_ids,
                information_id=str(record.get("information_id") or information_id),
            )
            if route:
                routes.append(route)
        return routes

    @staticmethod
    def _dedupe_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for route in routes:
            key = (
                str(route.get("kind") or ""),
                str(route.get("value") or "").strip().lower(),
                str(route.get("owner_entity_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(route)
        return output

    def evaluate_outreach_readiness(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(super().evaluate_outreach_readiness(arguments))
        investigation_id = self._investigation_id(arguments)
        state = self._v6_state(investigation_id)
        account_id = state["start"]["account"]["account_id"]

        routes = self._compiled_company_routes(state)
        routes.extend(self._information_company_routes(investigation_id, account_id))

        # Lower v6.1 hardening remains the authority for legacy Information
        # Records. This overlay is additive: never erase IDs/routes that the lower
        # canonical projection already validated, and never reparse Information
        # History here.
        lower_company_ids = {
            str(item)
            for item in (result.get("valid_company_route_observation_ids") or [])
            if str(item).strip()
        }
        lower_information_ids = {
            str(item)
            for item in (result.get("valid_information_route_ids") or [])
            if str(item).strip()
        }
        lower_sources = {
            str(item)
            for item in (result.get("canonical_route_sources") or [])
            if str(item).strip()
        }

        existing = result.get("canonical_route_view")
        if isinstance(existing, list):
            for route in existing:
                if not isinstance(route, dict):
                    continue
                information_id = str(route.get("information_id") or "")
                observation_id = str(route.get("observation_id") or "")
                explicitly_account_owned = (
                    route.get("verified") is True
                    and route.get("current") is True
                    and route.get("owned_by_account") is True
                    and route.get("owner_entity_id") == account_id
                )
                lower_validated = (
                    information_id in lower_information_ids
                    or observation_id in lower_company_ids
                )
                if explicitly_account_owned or lower_validated:
                    routes.append(dict(route))
        routes = self._dedupe_routes(routes)

        compiled_ids = {
            str(route["observation_id"])
            for route in routes
            if route.get("observation_id")
        }
        information_ids = {
            str(route["information_id"])
            for route in routes
            if route.get("information_id")
        }
        blockers = list(result.get("block_reasons") or [])
        remaining_blockers = [
            blocker
            for blocker in blockers
            if blocker != "VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED"
        ]

        result["canonical_route_view"] = routes
        result["canonical_route_sources"] = sorted(
            lower_sources
            | {str(route.get("source") or "") for route in routes if route.get("source")}
        )
        result["valid_company_route_observation_ids"] = sorted(
            lower_company_ids | compiled_ids
        )
        result["valid_information_route_ids"] = sorted(
            lower_information_ids | information_ids
        )

        current_readiness = str(
            result.get("outreach_readiness") or result.get("readiness") or "IDENTITY_ONLY"
        )
        has_company_route = bool(
            routes
            or result["valid_company_route_observation_ids"]
            or result["valid_information_route_ids"]
        )
        if has_company_route and not remaining_blockers and current_readiness != "NAMED_ROUTE_READY":
            result["outreach_readiness"] = "COMPANY_ROUTE_READY"
            result["readiness"] = "COMPANY_ROUTE_READY"
            result["block_reasons"] = []
        else:
            result["block_reasons"] = blockers
        result["sends_message"] = False
        return result

    def _promotion_identity_blockers(
        self,
        state: dict[str, Any],
    ) -> list[dict[str, str]]:
        claims = self._claims_view(state)
        blockers: list[dict[str, str]] = []
        for claim_key in ROOT_IDENTITY_CLAIMS:
            row = claims.get(claim_key) if isinstance(claims, dict) else None
            claim_state = (
                str(row.get("state") or "UNSEEN").upper()
                if isinstance(row, dict)
                else "UNSEEN"
            )
            if claim_state in ROOT_IDENTITY_BLOCKING_STATES:
                blockers.append({"claim_key": claim_key, "state": claim_state})
        return sorted(blockers, key=lambda item: (item["claim_key"], item["state"]))

    @staticmethod
    def _peer_identity_material(peer: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": peer.get("name"),
            "country": peer.get("country"),
            "tax_id": peer.get("tax_id"),
        }

    def _current_peer_canonical_resolution(
        self,
        peer: dict[str, Any],
    ) -> dict[str, Any]:
        return dict(self.canonical_registry.resolve(self._peer_identity_material(peer)))

    def _peer_reconciliation_view(
        self,
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        root_blockers = self._promotion_identity_blockers(state)
        rows: list[dict[str, Any]] = []
        peers = state.get("peers") or {}
        if not isinstance(peers, dict):
            return rows
        for peer_id, peer in sorted(peers.items(), key=lambda item: str(item[0])):
            if not isinstance(peer, dict):
                continue
            stage = str(peer.get("stage") or "DISCOVERED")
            if stage in {"PROMOTED_ANCHOR", "FULLY_AUDITED"}:
                continue
            current_resolution = self._current_peer_canonical_resolution(peer)
            status = str(current_resolution.get("status") or "").upper()
            match = current_resolution.get("match")
            matched_account_id = (
                str(match.get("account_id") or "")
                if isinstance(match, dict)
                else ""
            )
            rows.append({
                "peer_id": str(peer.get("peer_id") or peer_id),
                "historical_canonical_resolution": dict(
                    peer.get("canonical_resolution") or {}
                ),
                "current_canonical_resolution": current_resolution,
                "matched_account_id": matched_account_id or None,
                "reconciliation_state": (
                    "STILL_CANONICAL_NEW"
                    if status == "NOT_FOUND"
                    else "CANONICAL_RESOLUTION_AMBIGUOUS"
                    if status == "AMBIGUOUS"
                    else "NOW_CANONICAL_ACCOUNT_EXISTS"
                    if matched_account_id
                    else "CANONICAL_RESOLUTION_UNRESOLVED"
                ),
                "promotion_eligible_under_current_identity": bool(
                    stage == "ANCHOR_ELIGIBLE"
                    and peer.get("disposition") != "NOT_MATERIAL"
                    and status == "NOT_FOUND"
                    and not root_blockers
                ),
            })
        return rows

    def promote_anchor(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        investigation_id = self._investigation_id(arguments)
        state = self._v6_state(investigation_id)
        blockers = self._promotion_identity_blockers(state)
        if blockers:
            detail = ",".join(
                f"{item['claim_key']}={item['state']}" for item in blockers
            )
            raise ValidationError(f"ROOT_CRITICAL_IDENTITY_BLOCKED:{detail}")

        peer_id = str(arguments.get("peer_id") or "").strip()
        peer = (state.get("peers") or {}).get(peer_id) if peer_id else None
        if isinstance(peer, dict) and peer.get("stage") == "ANCHOR_ELIGIBLE":
            resolution = self._current_peer_canonical_resolution(peer)
            if str(resolution.get("status") or "").upper() != "NOT_FOUND":
                match = resolution.get("match")
                matched_account_id = (
                    str(match.get("account_id") or "")
                    if isinstance(match, dict)
                    else ""
                )
                raise ValidationError(
                    "PEER_NOW_RESOLVES_TO_CANONICAL_ACCOUNT:"
                    + (matched_account_id or "UNKNOWN")
                )
        return super().promote_anchor(arguments)

    @staticmethod
    def _normalize_decision_view(result: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(result)
        saturated = bool(normalized.get("decision_saturated"))
        exhausted = bool(normalized.get("budget_exhausted"))
        high_eiv = list(normalized.get("high_eiv_objectives") or [])
        blockers = list(normalized.get("blockers") or [])
        normalized["decision_state"] = "SATURATED" if saturated else "NOT_SATURATED"
        normalized["resource_state"] = "EXHAUSTED" if exhausted else "WITHIN_BUDGET"
        if saturated:
            action = "NO_HIGH_EIV_WORK"
        elif high_eiv:
            action = "CONTINUE_HIGH_EIV_RESEARCH"
        elif blockers:
            action = "RESOLVE_BLOCKERS"
        else:
            action = "REASSESS"
        normalized["research_action"] = action
        return normalized

    def evaluate_decision_saturation(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return self._normalize_decision_view(
            super().evaluate_decision_saturation(arguments)
        )

    def plan_public_source_calls(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(super().plan_public_source_calls(arguments))
        calls = [row for row in result.get("calls") or [] if isinstance(row, dict)]
        executable = [row for row in calls if row.get("execution_required", True)]
        truncated = bool(result.get("truncated"))
        coverage_complete = not executable and not truncated
        result["source_coverage_complete"] = coverage_complete
        result["source_coverage_status"] = (
            "PROVEN_COMPLETE" if coverage_complete else "INCOMPLETE"
        )
        result["remaining_source_attempt_count_at_least"] = len(executable)
        return result

    def _route_projection_diagnostics(
        self,
        state: dict[str, Any],
        outreach: dict[str, Any],
    ) -> dict[str, Any]:
        account_id = state["start"]["account"]["account_id"]
        claims = self._claims_view(state)
        claim = claims.get("contact.company_route") if isinstance(claims, dict) else None
        claim_state = (
            str(claim.get("state") or "UNSEEN").upper()
            if isinstance(claim, dict)
            else "UNSEEN"
        )
        claim_observation_ids = (
            [str(item) for item in (claim.get("observation_ids") or [])]
            if isinstance(claim, dict)
            else []
        )
        claim_evidence_ids = (
            [str(item) for item in (claim.get("evidence_ids") or [])]
            if isinstance(claim, dict)
            else []
        )
        has_canonical_route = bool(
            outreach.get("canonical_route_view")
            or outreach.get("valid_company_route_observation_ids")
            or outreach.get("valid_information_route_ids")
        )
        rows: list[dict[str, Any]] = []
        observations = state.get("observations") or {}
        for observation_id in claim_observation_ids:
            observation = (
                observations.get(observation_id)
                if isinstance(observations, dict)
                else None
            )
            if not isinstance(observation, dict):
                rows.append(
                    {
                        "observation_id": observation_id,
                        "evidence_id": None,
                        "freshness": None,
                        "rejection_reasons": [
                            "OBSERVATION_NOT_AVAILABLE_IN_DERIVED_STATE"
                        ],
                    }
                )
                continue
            source = observation.get("source")
            rows.append(
                {
                    "observation_id": observation_id,
                    "evidence_id": str(observation.get("evidence_id") or "") or None,
                    "freshness": (
                        str(source.get("freshness") or "").upper()
                        if isinstance(source, dict)
                        else None
                    ),
                    "rejection_reasons": self._compiled_route_rejection_reasons(
                        observation, account_id=account_id
                    ),
                }
            )
        supported = claim_state in {"SUPPORTED", "STRONGLY_SUPPORTED"}
        if has_canonical_route:
            status = "CANONICAL_ROUTE_AVAILABLE"
        elif supported:
            status = "SUPPORTED_CLAIM_WITHOUT_CANONICAL_ROUTE"
        else:
            status = "NO_SUPPORTED_COMPANY_ROUTE_CLAIM"
        return {
            "status": status,
            "claim_state": claim_state,
            "claim_observation_ids": claim_observation_ids,
            "claim_evidence_ids": claim_evidence_ids,
            "observations": rows,
            "contains_route_values": False,
            "mutates_history": False,
        }

    def get_account_state(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(super().get_account_state(arguments))
        investigation_id = self._investigation_id(arguments)
        outreach = self.evaluate_outreach_readiness(arguments)
        source_plan = self.plan_public_source_calls(
            {"investigation_id": investigation_id, "limit": 1}
        )
        result["outreach_readiness"] = outreach
        result["routes"] = list(outreach.get("canonical_route_view") or [])
        result["source_coverage"] = {
            "source_coverage_complete": bool(
                source_plan.get("source_coverage_complete")
            ),
            "source_coverage_status": str(
                source_plan.get("source_coverage_status") or "INCOMPLETE"
            ),
            "remaining_source_attempt_count_at_least": int(
                source_plan.get("remaining_source_attempt_count_at_least") or 0
            ),
            "planner_truncated": bool(source_plan.get("truncated")),
            "closure_snapshot_policy": "CLOSURE_MUTATION_RESULT_UNCHANGED",
        }
        state = self._v6_state(investigation_id)
        result["route_projection_diagnostics"] = self._route_projection_diagnostics(
            state, outreach
        )
        result["peer_reconciliation"] = self._peer_reconciliation_view(state)
        return result

    def get_runtime_contract(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        contract = dict(super().get_runtime_contract(arguments))
        contract["research_orchestration_v6_2"] = {
            "governance_principle": "CONSTRAIN_CONCLUSIONS_NOT_EXPLORATION",
            "budget_exhaustion_stops_host_research": False,
            "budget_is_soft_resource_signal": True,
            "decision_saturation_remains_closure_authority": True,
            "company_route_readiness": "COMPANY_ROUTE_READY",
            "named_route_requires_independent_person_ownership_proof": True,
            "source_coverage_view": "READ_ONLY_PLAN_AND_ACCOUNT_STATE",
            "source_coverage_authority": (
                "plan_public_source_calls.source_coverage_complete"
            ),
            "closure_mutation_result_unchanged": True,
            "legacy_closure_network_complete_is_exhaustive_proof": False,
            "persistence_layers_unchanged": [
                "APPEND_ONLY_HISTORY",
                "HASH_CHAIN",
                "MUTATION_WAL",
                "CANONICAL_REGISTRY",
                "R2_OBJECT_STORE_CAS",
            ],
        }
        return contract
