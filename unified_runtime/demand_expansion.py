from __future__ import annotations

import copy
from typing import Any

from .contact_exhaustion import plan_contact_exhaustion as _plan_contact_exhaustion
from .capability_profile import evaluate_capability_fit as _evaluate_capability_fit
from .capability_binding_v63 import bind_private_capability_bundle as _bind_private_capability_bundle
from .candidate_research_gate import (
    assess_candidate_researchability as _assess_candidate_researchability,
    rank_candidate_research_queue as _rank_candidate_research_queue,
)
from .contract_v63 import build_v63_contract
from .demand_pipeline import plan_customs_seed_expansion
from .demand_market import (
    derive_demand_anchor as _derive_demand_anchor,
    derive_market_cell as _derive_market_cell,
    evaluate_market_acceptance as _evaluate_market_acceptance,
    is_direct_procurement_source as _is_direct_procurement_source,
)
from .expansion_planner import (
    evaluate_expansion_saturation as _evaluate_expansion_saturation,
    generate_discovery_queries,
    plan_expansion,
)
from .opportunity_domain import (
    LIFECYCLE_STAGES as _V63_LIFECYCLE_STAGES,
    relative_opportunity,
    derive_product_opportunity_evaluation as _derive_product_opportunity_evaluation,
)
from .legacy_peer_projection import project_legacy_peer_receipt as _project_legacy_peer_receipt
from .recursive_expansion import prepare_recursive_expansion as _prepare_recursive_expansion
from .product_profiles import list_product_profiles
from .source_execution import plan_public_source_tasks
from .research_scheduler import schedule_research_work as _schedule_research_work
from .route_reuse import reuse_route_for_opportunity as _reuse_route_for_opportunity
from .portfolio_metrics import compute_portfolio_metrics as _compute_portfolio_metrics
from .local_outreach_policy import plan_local_outreach as _plan_local_outreach
from .local_context_resolution import plan_local_context_resolution as _plan_local_context_resolution
from .sales_readiness import evaluate_sales_readiness as _evaluate_sales_readiness
from .runtime_durable_backend_v63 import get_v63_runtime_durable_backend_state, invoke_v63_runtime_durable_backend
from .v63_projection import project_product_opportunities as _project_product_opportunities


_WAL_BINDING_ERROR = "V63_MUTATION_REQUIRES_PRODUCTION_WAL_BINDING"


class V63DemandExpansionMixin:
    """Read-only v6.3 overlay plus fail-closed mutation boundary.

    The pure business/domain functions are safe to exercise before the production
    MCP/WAL adapter is available. Durable mutation methods deliberately refuse to
    run until they are bound to the existing production WAL/correlation layer.
    """

    def get_runtime_contract(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        base = super().get_runtime_contract(arguments or {})
        result = copy.deepcopy(base)
        result["demand_expansion_v6_3"] = build_v63_contract()
        backend_state = get_v63_runtime_durable_backend_state(self)
        backend_bound = backend_state["status"] == "BOUND_EXISTING_DURABLE_STORE"
        result["demand_expansion_v6_3"]["runtime_overlay_mutation_binding"] = (
            "BOUND_EXISTING_PRODUCTION_WAL" if backend_bound else "FAIL_CLOSED_PENDING_PRODUCTION_WAL"
        )
        result["demand_expansion_v6_3"]["runtime_durable_backend_binding"] = backend_state["status"]
        result["demand_expansion_v6_3"]["runtime_durable_backend_schema"] = backend_state["backend_schema"]
        result["demand_expansion_v6_3"]["runtime_durable_backend_parallel_store_allowed"] = backend_state["parallel_state_store_allowed"]
        result["demand_expansion_v6_3"]["runtime_durable_backend_requires_existing_mutation_correlation"] = backend_state["requires_existing_mutation_correlation"]
        result["demand_expansion_v6_3"]["runtime_durable_backend_raw_idempotency_key_persisted"] = backend_state["raw_idempotency_key_persisted"]
        result["demand_expansion_v6_3"]["runtime_durable_backend_side_effect_reexecution_allowed"] = backend_state["side_effect_reexecution_allowed"]

        read_model_bindings = {
            "durable_event_reader": "BOUND" if callable(getattr(self, "_read_v63_durable_events", None)) else "UNBOUND",
            "opportunity_event_query": "BOUND" if callable(getattr(self, "_query_v63_opportunity_events", None)) else "UNBOUND",
            "evidence_ownership_verifier": "BOUND" if callable(getattr(self, "_validate_v63_evidence_ownership", None)) else "UNBOUND",
            "evidence_provenance_verifier": "BOUND" if callable(getattr(self, "_validate_v63_evidence_provenance", None)) else "UNBOUND",
            "opportunity_evidence_verifier": "BOUND" if callable(getattr(self, "_validate_v63_opportunity_evidence_binding", None)) else "UNBOUND",
            "opportunity_derived_state_provider": "BOUND" if callable(getattr(self, "_derive_v63_opportunity_runtime_view", None)) else "UNBOUND",
        }
        if getattr(self, "_v63_capability_profiles", None):
            capability_binding = "BOUND_IN_MEMORY"
        elif callable(getattr(self, "_load_v63_capability_bundle", None)):
            capability_binding = "PRIVATE_LOADER_BOUND"
        else:
            capability_binding = "UNBOUND"
        read_model_bindings["capability_profile_source"] = capability_binding

        blocker_codes = {
            "durable_event_reader": "V63_DURABLE_EVENT_READER_NOT_BOUND",
            "opportunity_event_query": "V63_OPPORTUNITY_EVENT_QUERY_NOT_BOUND",
            "evidence_ownership_verifier": "V63_EVIDENCE_OWNERSHIP_VERIFIER_NOT_BOUND",
            "evidence_provenance_verifier": "V63_EVIDENCE_PROVENANCE_VERIFIER_NOT_BOUND",
            "opportunity_evidence_verifier": "V63_OPPORTUNITY_EVIDENCE_VERIFIER_NOT_BOUND",
            "opportunity_derived_state_provider": "V63_OPPORTUNITY_DERIVED_VIEW_PROVIDER_NOT_BOUND",
            "capability_profile_source": "V63_CAPABILITY_PROFILE_SOURCE_NOT_BOUND",
        }
        blockers = [
            blocker_codes[name]
            for name, state in read_model_bindings.items()
            if state == "UNBOUND"
        ]
        result["demand_expansion_v6_3"]["read_model_runtime_bindings_v6_3"] = read_model_bindings
        result["demand_expansion_v6_3"]["runtime_integration_blockers_v6_3"] = blockers
        result["demand_expansion_v6_3"]["runtime_read_model_bindings_complete"] = not blockers
        result["demand_expansion_v6_3"]["runtime_read_model_binding_status"] = (
            "BOUND" if not blockers else "FAIL_CLOSED_INCOMPLETE"
        )
        result["demand_expansion_v6_3"]["runtime_binding_status_is_not_production_acceptance"] = True
        result["demand_expansion_v6_3"]["required_read_model_tools_v6_3"] = [
            "get_product_opportunities",
            "get_demand_anchors",
            "get_market_cells",
            "evaluate_market_acceptance",
            "get_expansion_state",
        ]
        result["demand_expansion_v6_3"]["read_model_tools_exposed_v6_3"] = {
            name: callable(getattr(self, name, None))
            for name in result["demand_expansion_v6_3"]["required_read_model_tools_v6_3"]
        }
        result["demand_expansion_v6_3"]["read_model_tool_surface_complete_v6_3"] = all(
            result["demand_expansion_v6_3"]["read_model_tools_exposed_v6_3"].values()
        )
        return result

    def get_product_profiles(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": "READY",
            "profiles": list_product_profiles(),
            "persistent_mutation_performed": False,
        }


    def _v63_durable_events_for_projection(self, investigation_id: str) -> list[dict[str, Any]]:
        investigation = str(investigation_id or "").strip()
        if not investigation:
            raise ValueError("INVESTIGATION_ID_REQUIRED")
        reader = getattr(self, "_read_v63_durable_events", None)
        if not callable(reader):
            raise RuntimeError("V63_DURABLE_EVENT_READER_NOT_BOUND")
        events = reader(investigation)
        if events is None:
            return []
        if not isinstance(events, (list, tuple)):
            raise RuntimeError("V63_DURABLE_EVENT_READER_INVALID_RESULT")
        return [copy.deepcopy(row) for row in events if isinstance(row, dict)]

    def _v63_query_opportunity_events(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        query = getattr(self, "_query_v63_opportunity_events", None)
        if not callable(query):
            raise RuntimeError("V63_OPPORTUNITY_EVENT_QUERY_NOT_BOUND")
        result = query(copy.deepcopy(filters))
        if result is None:
            return []
        if not isinstance(result, (list, tuple)):
            raise RuntimeError("V63_OPPORTUNITY_EVENT_QUERY_INVALID_RESULT")
        return [copy.deepcopy(row) for row in result if isinstance(row, dict)]

    def _v63_validate_evidence_owner(self, investigation_id: str, account_id: str, evidence_ids: list[str]) -> None:
        verifier = getattr(self, "_validate_v63_evidence_ownership", None)
        if not callable(verifier):
            raise RuntimeError("V63_EVIDENCE_OWNERSHIP_VERIFIER_NOT_BOUND")
        result = verifier(str(investigation_id), str(account_id), list(evidence_ids))
        valid = bool(result.get("valid")) if isinstance(result, dict) else bool(result)
        if not valid:
            raise ValueError("EVIDENCE_OWNER_MISMATCH")

    def _v63_validate_evidence_provenance(self, investigation_id: str, evidence_ids: list[str], source_type: str) -> None:
        verifier = getattr(self, "_validate_v63_evidence_provenance", None)
        if not callable(verifier):
            raise RuntimeError("V63_EVIDENCE_PROVENANCE_VERIFIER_NOT_BOUND")
        result = verifier(str(investigation_id), list(evidence_ids), str(source_type).upper())
        valid = bool(result.get("valid")) if isinstance(result, dict) else bool(result)
        if not valid:
            raise ValueError(f"{str(source_type).upper()}_EVIDENCE_PROVENANCE_MISMATCH")

    def _v63_validate_opportunity_evidence_binding(
        self, investigation_id: str, opportunity: dict[str, Any], evidence_ids: list[str]
    ) -> None:
        verifier = getattr(self, "_validate_v63_opportunity_evidence_binding", None)
        if not callable(verifier):
            raise RuntimeError("V63_OPPORTUNITY_EVIDENCE_VERIFIER_NOT_BOUND")
        result = verifier(str(investigation_id), copy.deepcopy(opportunity), list(evidence_ids))
        valid = bool(result.get("valid")) if isinstance(result, dict) else bool(result)
        if not valid:
            raise ValueError("EVIDENCE_OPPORTUNITY_BINDING_MISMATCH")

    def _v63_join_opportunity_runtime_view(self, investigation_id: str, opportunity: dict[str, Any]) -> dict[str, Any]:
        row = copy.deepcopy(opportunity)
        durable_stage = str(row.get("stage") or row.get("lifecycle_stage") or "OPPORTUNITY_CREATED").strip().upper()
        row["durable_stage"] = durable_stage
        provider = getattr(self, "_derive_v63_opportunity_runtime_view", None)
        if not callable(provider):
            row["derived_state_joined"] = False
            row["derived_state_status"] = "UNBOUND"
            return row
        view = provider(str(investigation_id), copy.deepcopy(row))
        if view in (None, {}):
            row["derived_state_joined"] = False
            row["derived_state_status"] = "NO_DERIVED_STATE"
            return row
        if not isinstance(view, dict):
            raise RuntimeError("V63_DERIVED_OPPORTUNITY_VIEW_INVALID_RESULT")
        identity_fields = ("opportunity_id", "account_id", "product_profile_id", "product_profile_version", "product_profile_sha256")
        for field in identity_fields:
            if field in view and view.get(field) not in (None, ""):
                left = str(row.get(field) or "")
                right = str(view.get(field) or "")
                if field in {"product_profile_id", "product_profile_sha256"}:
                    left, right = left.upper(), right.upper()
                if left and left != right:
                    raise ValueError(f"V63_DERIVED_VIEW_IDENTITY_CONFLICT:{field}")

        evidence_ids = [str(v).strip() for v in view.get("commercial_evidence_ids", []) if str(v).strip()]
        target_stage = str(view.get("lifecycle_stage") or view.get("lifecycle_target") or "").strip().upper()
        has_commercial_assertion = any(
            key in view and view.get(key) not in (None, "")
            for key in ("commercial_value_grade", "commercial_value_score", "commercial_score")
        )
        advances_to_qualified = (
            target_stage in _V63_LIFECYCLE_STAGES
            and _V63_LIFECYCLE_STAGES.index(target_stage) >= _V63_LIFECYCLE_STAGES.index("QUALIFIED_TARGET")
        )
        if (has_commercial_assertion or advances_to_qualified) and not evidence_ids:
            raise ValueError("V63_DERIVED_VIEW_COMMERCIAL_EVIDENCE_REQUIRED")
        if evidence_ids:
            self._v63_validate_evidence_owner(
                str(investigation_id),
                str(row.get("account_id") or ""),
                evidence_ids,
            )
            self._v63_validate_opportunity_evidence_binding(
                str(investigation_id), row, evidence_ids
            )

        allowed = {
            "commercial_value_grade", "commercial_value_score", "commercial_score",
            "commercial_evidence_ids", "research_confidence", "outreach_readiness",
            "company_route_status", "named_route_status", "contact_exhaustion_state",
            "research_state", "commercial_state", "anchor_eligibility", "expansion_state",
            "market_acceptance", "relative_class", "relative_score_delta",
            "derived_from_existing_evidence", "derived_basis", "current_routes",
        }
        for field in allowed:
            if field in view:
                row[field] = copy.deepcopy(view[field])

        if target_stage:
            if target_stage not in _V63_LIFECYCLE_STAGES:
                raise ValueError("V63_DERIVED_VIEW_INVALID_LIFECYCLE_STAGE")
            if durable_stage not in _V63_LIFECYCLE_STAGES:
                raise ValueError("V63_DURABLE_VIEW_INVALID_LIFECYCLE_STAGE")
            durable_index = _V63_LIFECYCLE_STAGES.index(durable_stage)
            target_index = _V63_LIFECYCLE_STAGES.index(target_stage)
            row["lifecycle_stage"] = _V63_LIFECYCLE_STAGES[max(durable_index, target_index)]
        else:
            row["lifecycle_stage"] = durable_stage
        row["derived_state_joined"] = True
        row["derived_state_status"] = "RECONSTRUCTED_FROM_EXISTING_EVIDENCE_AND_POLICY"
        return row

    def get_product_opportunities(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        investigation_id = str(args.get("investigation_id") or "").strip()
        if investigation_id:
            events = self._v63_durable_events_for_projection(investigation_id)
            projection_scope = "INVESTIGATION"
        else:
            events = self._v63_query_opportunity_events({
                "account_id": args.get("account_id"),
                "opportunity_id": args.get("opportunity_id"),
                "product_profile_id": args.get("product_profile_id"),
            })
            projection_scope = "VISIBLE_PORTFOLIO_QUERY"
        result = _project_product_opportunities(
            events,
            account_id=args.get("account_id"),
            opportunity_id=args.get("opportunity_id"),
            product_profile_id=args.get("product_profile_id"),
        )
        normalized_rows = []
        for raw_row in result["opportunities"]:
            row = copy.deepcopy(raw_row)
            row_investigation_id = str(row.get("investigation_id") or investigation_id).strip()
            if not row_investigation_id:
                raise RuntimeError("V63_GLOBAL_OPPORTUNITY_EVENT_MISSING_INVESTIGATION_ID")
            row["investigation_id"] = row_investigation_id
            normalized_rows.append(self._v63_join_opportunity_runtime_view(row_investigation_id, row))
        result["opportunities"] = normalized_rows
        result["projection_scope"] = projection_scope
        result["derived_state_join_enabled"] = callable(getattr(self, "_derive_v63_opportunity_runtime_view", None))
        return result

    def _v63_resolve_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        supplied = arguments.get("opportunity")
        investigation_id = str(arguments.get("investigation_id") or "").strip()
        opportunity_id = str(arguments.get("opportunity_id") or "").strip()

        if investigation_id or opportunity_id:
            if not investigation_id or not opportunity_id:
                raise ValueError("INVESTIGATION_ID_AND_OPPORTUNITY_ID_REQUIRED")
            projected = self.get_product_opportunities({
                "investigation_id": investigation_id,
                "opportunity_id": opportunity_id,
            })
            rows = list(projected.get("opportunities") or [])
            if len(rows) != 1:
                raise ValueError("OPPORTUNITY_NOT_FOUND")
            durable = copy.deepcopy(rows[0])
            for field in ("account_id", "product_profile_id", "product_profile_version", "product_profile_sha256"):
                if arguments.get(field) not in (None, "") and str(arguments.get(field)).upper() != str(durable.get(field) or "").upper():
                    raise ValueError(f"OPPORTUNITY_CONTEXT_IDENTITY_CONFLICT:{field}")
            if isinstance(supplied, dict) and supplied:
                for field in ("opportunity_id", "account_id", "product_profile_id", "product_profile_version", "product_profile_sha256"):
                    if supplied.get(field) not in (None, "") and str(supplied.get(field)).upper() != str(durable.get(field) or "").upper():
                        raise ValueError(f"SUPPLIED_OPPORTUNITY_IDENTITY_CONFLICT:{field}")
            return durable

        if isinstance(supplied, dict) and supplied:
            return copy.deepcopy(supplied)
        raise ValueError("INVESTIGATION_ID_AND_OPPORTUNITY_ID_REQUIRED")

    def get_demand_anchors(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        seeds = list(args.get("seeds") or [])
        anchors = [self.derive_demand_anchor(dict(seed)) for seed in seeds if isinstance(seed, dict)]
        return {
            "status": "READY",
            "anchors": anchors,
            "derived_view": True,
            "requires_immutable_evidence_inputs": True,
            "persistent_mutation_performed": False,
        }

    def get_market_cells(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        cells = []
        for item in list(args.get("items") or []):
            if not isinstance(item, dict):
                continue
            cells.append(_derive_market_cell(
                dict(item.get("anchor") or {}),
                list(item.get("application_ids") or []),
                list(item.get("buyer_archetype_ids") or []),
                channel=item.get("channel"),
            ))
        return {
            "status": "READY",
            "market_cells": cells,
            "derived_view": True,
            "persistent_mutation_performed": False,
        }

    def evaluate_market_acceptance(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = _evaluate_market_acceptance(list(dict(arguments or {}).get("anchors") or []))
        result["derived_view"] = True
        result["persistent_mutation_performed"] = False
        return result

    def get_expansion_state(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        opportunities = self.get_product_opportunities(args)
        return {
            "status": "READY",
            "product_opportunities": opportunities["opportunities"],
            "product_opportunity_count": opportunities["projected_opportunity_count"],
            "legacy_projection": copy.deepcopy(args.get("legacy_projection")),
            "persistent_mutation_performed": False,
        }

    def get_capability_profile(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        profile_id = str(args.get("product_profile_id") or "PVC").strip().upper()
        profiles = getattr(self, "_v63_capability_profiles", {}) or {}
        if not profiles:
            loader = getattr(self, "_load_v63_capability_bundle", None)
            if callable(loader):
                bundle = loader()
                if bundle is not None:
                    _bind_private_capability_bundle(self, bundle)
                    profiles = getattr(self, "_v63_capability_profiles", {}) or {}
        capability = copy.deepcopy(profiles.get(profile_id))
        if capability is None:
            return {
                "status": "UNCONFIGURED",
                "product_profile_id": profile_id,
                "capability_profile": None,
                "reason": "CAPABILITY_PROFILE_NOT_BOUND",
                "persistent_mutation_performed": False,
            }
        return {
            "status": "READY",
            "product_profile_id": profile_id,
            "capability_profile": capability,
            "persistent_mutation_performed": False,
        }

    def evaluate_capability_fit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(arguments.get("product_profile_id") or "PVC").strip().upper()
        current = self.get_capability_profile({"product_profile_id": profile_id})
        if current["status"] != "READY":
            return {
                "status": "UNCONFIGURED",
                "product_profile_id": profile_id,
                "capability_fit": None,
                "reason": current["reason"],
                "persistent_mutation_performed": False,
            }
        fit = _evaluate_capability_fit(
            current["capability_profile"],
            dict(arguments.get("demand") or {}),
        )
        return {
            "status": "READY",
            "product_profile_id": profile_id,
            "capability_fit": fit,
            "persistent_mutation_performed": False,
        }

    def assess_candidate_researchability(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _assess_candidate_researchability(copy.deepcopy(arguments))
        result["persistent_mutation_performed"] = False
        return result

    def rank_candidate_research_queue(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rows = _rank_candidate_research_queue(list(arguments.get("candidates") or []))
        return {
            "status": "READY",
            "candidates": rows,
            "commercial_grade_required": False,
            "persistent_mutation_performed": False,
        }

    def preview_customs_seed_expansion(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        requested_source_type = str(args.get("source_type") or "CUSTOMS").strip().upper()
        if requested_source_type != "CUSTOMS":
            raise ValueError("CUSTOMS_SOURCE_REQUIRED")
        investigation_id = str(args.get("investigation_id") or "").strip()
        account_id = str(args.get("account_id") or "").strip()
        evidence_ids = [str(v).strip() for v in args.get("source_evidence_ids", []) if str(v).strip()]
        self._v63_validate_evidence_owner(investigation_id, account_id, evidence_ids)
        opportunity = self._v63_resolve_opportunity(args)
        self._v63_validate_opportunity_evidence_binding(investigation_id, opportunity, evidence_ids)
        self._v63_validate_evidence_provenance(investigation_id, evidence_ids, "CUSTOMS")
        args["source_type"] = "CUSTOMS"
        result = plan_customs_seed_expansion(args)
        result["demand_anchor"]["evidence_ownership_verified"] = True
        result["demand_anchor"]["direct_procurement_provenance_verified"] = True
        result["preview_only"] = True
        result["persistent_mutation_performed"] = False
        return result

    def plan_candidate_expansion(self, arguments: dict[str, Any]) -> dict[str, Any]:
        context = copy.deepcopy(arguments)
        query_limit = int(context.pop("query_limit", 100) or 100)
        source_task_limit = int(context.pop("source_task_limit", 1000) or 1000)
        expansion_plan = plan_expansion(context)
        discovery_plan = generate_discovery_queries({**context, "limit": query_limit})
        source_plan = plan_public_source_tasks(
            expansion_plan,
            discovery_plan,
            max_tasks=source_task_limit,
        )
        return {
            "status": "PLANNED",
            "expansion_plan": expansion_plan,
            "discovery_plan": discovery_plan,
            "source_plan": source_plan,
            "planning_is_execution_proof": False,
            "host_execution_required": True,
            "persistent_mutation_performed": False,
        }

    def project_legacy_peer_receipt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _project_legacy_peer_receipt(arguments)

    def preview_recursive_anchor_expansion(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _prepare_recursive_expansion(arguments)
        result["preview_only"] = True
        result["persistent_mutation_performed"] = False
        return result

    def evaluate_relative_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return relative_opportunity(
            float(arguments.get("anchor_score") or 0.0),
            float(arguments.get("candidate_score") or 0.0),
            str(arguments.get("anchor_grade") or ""),
            str(arguments.get("candidate_grade") or ""),
            strategic=bool(arguments.get("strategic", False)),
        )

    def plan_contact_exhaustion(self, arguments: dict[str, Any]) -> dict[str, Any]:
        opportunity = self._v63_resolve_opportunity(arguments)
        current_routes = dict(arguments.get("current_routes") or {})
        return _plan_contact_exhaustion(opportunity, current_routes)

    def evaluate_expansion_saturation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _evaluate_expansion_saturation(arguments)

    def evaluate_route_reuse(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _reuse_route_for_opportunity(
            dict(arguments.get("route") or {}),
            self._v63_resolve_opportunity(arguments),
        )
        result["persistent_mutation_performed"] = False
        return result

    def get_portfolio_metrics(self, arguments: dict[str, Any]) -> dict[str, Any]:
        supplied = arguments.get("opportunities")
        if isinstance(supplied, list):
            opportunities = list(supplied)
        else:
            opportunities = self.get_product_opportunities(arguments)["opportunities"]
        result = _compute_portfolio_metrics(opportunities)
        result["persistent_mutation_performed"] = False
        return result

    def schedule_expansion_research(self, arguments: dict[str, Any]) -> dict[str, Any]:
        supplied = arguments.get("opportunities")
        if isinstance(supplied, list):
            opportunities = list(supplied)
        else:
            opportunities = self.get_product_opportunities(arguments)["opportunities"]
        result = _schedule_research_work(
            opportunities,
            float(arguments.get("budget_units") or 0.0),
        )
        result["persistent_mutation_performed"] = False
        return result

    def plan_local_outreach(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _plan_local_outreach(copy.deepcopy(arguments))
        result["persistent_mutation_performed"] = False
        return result

    def plan_local_context_resolution(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _plan_local_context_resolution(copy.deepcopy(arguments))
        result["persistent_mutation_performed"] = False
        return result

    def evaluate_sales_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        opportunity = self._v63_resolve_opportunity(arguments)
        arguments = {**copy.deepcopy(arguments), "opportunity": opportunity}
        profile_id = str(opportunity.get("product_profile_id") or arguments.get("product_profile_id") or "").strip().upper()
        current = self.get_capability_profile({"product_profile_id": profile_id})
        if current["status"] != "READY":
            return {
                "status": "UNCONFIGURED",
                "product_profile_id": profile_id or None,
                "sales_readiness": None,
                "reason": current.get("reason") or "CAPABILITY_PROFILE_NOT_BOUND",
                "persistent_mutation_performed": False,
            }
        readiness = _evaluate_sales_readiness(copy.deepcopy(arguments), current["capability_profile"])
        return {
            "status": "READY",
            "product_profile_id": profile_id,
            "sales_readiness": readiness,
            "persistent_mutation_performed": False,
        }

    def _invoke_v63_durable_mutation(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return invoke_v63_runtime_durable_backend(self, tool_name, arguments)

    def derive_demand_anchor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        investigation_id = str(args.get("investigation_id") or "").strip()
        if not investigation_id:
            raise ValueError("INVESTIGATION_ID_REQUIRED_FOR_EVIDENCE_BINDING")
        account_id = str(args.get("account_id") or "").strip()
        evidence_ids = [str(v).strip() for v in args.get("source_evidence_ids", []) if str(v).strip()]
        self._v63_validate_evidence_owner(investigation_id, account_id, evidence_ids)
        opportunity = self._v63_resolve_opportunity(args)
        self._v63_validate_opportunity_evidence_binding(investigation_id, opportunity, evidence_ids)
        source_type = str(args.get("source_type") or "").strip().upper()
        provenance_verified = False
        if _is_direct_procurement_source(source_type):
            self._v63_validate_evidence_provenance(investigation_id, evidence_ids, source_type)
            provenance_verified = True
        result = _derive_demand_anchor(args)
        result["derived_view"] = True
        result["evidence_ownership_verified"] = True
        result["direct_procurement_provenance_verified"] = provenance_verified
        result["persistent_mutation_performed"] = False
        return result

    def append_candidate_discovery(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._invoke_v63_durable_mutation("append_candidate_discovery", arguments)

    def create_product_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._invoke_v63_durable_mutation("create_product_opportunity", arguments)

    def evaluate_product_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        opportunity = self._v63_resolve_opportunity(args)
        evidence_ids = [
            str(v).strip()
            for v in dict(args.get("assessment") or {}).get("commercial_evidence_ids", [])
            if str(v).strip()
        ]
        self._v63_validate_evidence_owner(
            str(args.get("investigation_id") or ""),
            str(opportunity.get("account_id") or ""),
            evidence_ids,
        )
        self._v63_validate_opportunity_evidence_binding(
            str(args.get("investigation_id") or ""), opportunity, evidence_ids
        )
        result = _derive_product_opportunity_evaluation(args)
        result["validated_against_projected_opportunity"] = True
        return result

    def promote_opportunity_anchor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._invoke_v63_durable_mutation("promote_opportunity_anchor", arguments)
