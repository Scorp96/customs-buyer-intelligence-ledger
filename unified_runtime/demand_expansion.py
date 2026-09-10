from __future__ import annotations

import copy
from typing import Any

from .contact_exhaustion import plan_contact_exhaustion as _plan_contact_exhaustion
from .capability_profile import evaluate_capability_fit as _evaluate_capability_fit
from .candidate_research_gate import (
    assess_candidate_researchability as _assess_candidate_researchability,
    rank_candidate_research_queue as _rank_candidate_research_queue,
)
from .contract_v63 import build_v63_contract
from .demand_pipeline import plan_customs_seed_expansion
from .demand_market import derive_demand_anchor as _derive_demand_anchor
from .expansion_planner import (
    evaluate_expansion_saturation as _evaluate_expansion_saturation,
    generate_discovery_queries,
    plan_expansion,
)
from .opportunity_domain import relative_opportunity, derive_product_opportunity_evaluation as _derive_product_opportunity_evaluation
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
        return result

    def get_product_profiles(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": "READY",
            "profiles": list_product_profiles(),
            "persistent_mutation_performed": False,
        }

    def get_capability_profile(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        profile_id = str(args.get("product_profile_id") or "PVC").strip().upper()
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
        result = plan_customs_seed_expansion(arguments)
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
        opportunity = dict(arguments.get("opportunity") or {})
        current_routes = dict(arguments.get("current_routes") or {})
        return _plan_contact_exhaustion(opportunity, current_routes)

    def evaluate_expansion_saturation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _evaluate_expansion_saturation(arguments)

    def evaluate_route_reuse(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _reuse_route_for_opportunity(
            dict(arguments.get("route") or {}),
            dict(arguments.get("opportunity") or {}),
        )
        result["persistent_mutation_performed"] = False
        return result

    def get_portfolio_metrics(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _compute_portfolio_metrics(list(arguments.get("opportunities") or []))
        result["persistent_mutation_performed"] = False
        return result

    def schedule_expansion_research(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = _schedule_research_work(
            list(arguments.get("opportunities") or []),
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
        opportunity = dict(arguments.get("opportunity") or {})
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
        result = _derive_demand_anchor(copy.deepcopy(arguments))
        result["derived_view"] = True
        result["persistent_mutation_performed"] = False
        return result

    def append_candidate_discovery(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._invoke_v63_durable_mutation("append_candidate_discovery", arguments)

    def create_product_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._invoke_v63_durable_mutation("create_product_opportunity", arguments)

    def evaluate_product_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _derive_product_opportunity_evaluation(copy.deepcopy(arguments))

    def promote_opportunity_anchor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._invoke_v63_durable_mutation("promote_opportunity_anchor", arguments)
