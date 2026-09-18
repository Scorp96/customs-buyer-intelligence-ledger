from __future__ import annotations

from typing import Any


V63_READ_ONLY_TOOL_NAMES = (
    "get_product_profiles",
    "get_capability_profile",
    "evaluate_capability_fit",
    "assess_candidate_researchability",
    "rank_candidate_research_queue",
    "preview_customs_seed_expansion",
    "plan_candidate_expansion",
    "evaluate_relative_opportunity",
    "plan_contact_exhaustion",
    "evaluate_expansion_saturation",
    "project_legacy_peer_receipt",
    "preview_recursive_anchor_expansion",
    "evaluate_route_reuse",
    "get_portfolio_metrics",
    "schedule_expansion_research",
    "plan_local_outreach",
    "plan_local_context_resolution",
    "evaluate_sales_readiness",
    "derive_demand_anchor",
    "evaluate_product_opportunity",
)

V63_MUTATION_TOOL_NAMES = (
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
)

_PLANNERS = frozenset({
    "preview_customs_seed_expansion",
    "plan_candidate_expansion",
    "plan_contact_exhaustion",
    "preview_recursive_anchor_expansion",
    "schedule_expansion_research",
    "plan_local_outreach",
    "plan_local_context_resolution",
})

_DESCRIPTIONS = {
    "get_product_profiles": "List version-pinned v6.3 product profiles and PVC-first portfolio metadata.",
    "get_capability_profile": "Read seller manufacturing capability profile without inferring unsupported technical claims.",
    "evaluate_capability_fit": "Compare verified seller capability against a product demand without inventing unsupported specifications or certifications.",
    "assess_candidate_researchability": "Keep discovery high-recall: classify D1-D4 candidates for continued research without treating missing canonical identity, procurement proof, or contact as rejection.",
    "rank_candidate_research_queue": "Rank D1-D4 discovery candidates for further research without requiring a commercial grade; evidence tier and portfolio weight affect research order only.",
    "preview_customs_seed_expansion": "Preview Customs → Demand Anchor → Market Cell → buyer-expansion planning without persistence.",
    "plan_candidate_expansion": "Plan six-group buyer opportunity expansion and public-source work; planning is not execution proof.",
    "evaluate_relative_opportunity": "Compare a candidate opportunity to its reference anchor without mutating commercial evidence.",
    "plan_contact_exhaustion": "Plan grade-aware company/named-route research for a qualified product opportunity.",
    "evaluate_expansion_saturation": "Evaluate expansion blockers separately from Decision Saturation and Source Coverage.",
    "project_legacy_peer_receipt": "Project legacy peer state into a read-only v6.3 compatibility signal.",
    "preview_recursive_anchor_expansion": "Preview recursive expansion from a promoted v6.3 opportunity anchor with cycle dedup.",
    "evaluate_route_reuse": "Evaluate whether a verified current account/person route can be reused for another product opportunity without treating the route as product-demand proof.",
    "get_portfolio_metrics": "Project unique-account and product-opportunity KPIs without duplicating companies across product families.",
    "schedule_expansion_research": "Allocate a soft research budget while keeping material deferred work visible; budget exhaustion is never completion proof.",
    "plan_local_outreach": "Plan recipient-local outreach timing, language, holiday review and route-result cadence without sending a message.",
    "plan_local_context_resolution": "Plan missing timezone, workweek, current-holiday and outreach-language evidence resolution tasks; planning is not execution proof.",
    "evaluate_sales_readiness": "Evaluate route, recipient-local timing/language and seller capability together without sending or creating a draft.",
    "derive_demand_anchor": "Derive a verified demand anchor from immutable Evidence and pinned product knowledge without persistence.",
    "append_candidate_discovery": "Persist one candidate discovery event through the existing production mutation WAL.",
    "create_product_opportunity": "Persist a new Account × Product Opportunity through the existing production mutation WAL.",
    "evaluate_product_opportunity": "Derive an evidence-bound product-opportunity evaluation without creating a second durable fact source.",
    "promote_opportunity_anchor": "Persist v6.3 anchor promotion only after eligibility and cycle-dedup gates pass.",
}


def _base_properties() -> dict[str, Any]:
    return {
        "investigation_id": {"type": "string", "minLength": 1},
        "account_id": {"type": "string", "minLength": 1},
        "opportunity_id": {"type": "string", "minLength": 1},
        "product_profile_id": {"type": "string", "minLength": 1},
    }


def _mutation_controls() -> dict[str, Any]:
    return {
        "idempotency_key": {
            "type": "string",
            "minLength": 8,
            "maxLength": 160,
        },
        "expected_state_version": {"type": "integer", "minimum": 0},
    }


def _evidence_id_array() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }


def _canonical_resolution_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "canonical_status",
            "canonical_account_id",
            "resolver_authority",
            "resolver_is_existing_production_authority",
            "ambiguous",
            "address_only_match",
            "alias_only_match",
        ],
        "properties": {
            "canonical_status": {"enum": ["CONFIRMED", "CREATED"]},
            "canonical_account_id": {"type": "string", "minLength": 1},
            "resolver_authority": {
                "enum": [
                    "EXACT_ACCOUNT_ID",
                    "TAX_ID",
                    "EXTERNAL_ID",
                    "PRIMARY_LEGAL_NAME_COUNTRY",
                    "EXPLICIT_NEW_ID",
                ]
            },
            "resolver_is_existing_production_authority": {"const": True},
            "ambiguous": {"const": False},
            "address_only_match": {"const": False},
            "alias_only_match": {"const": False},
            "tax_conflict": {"type": "boolean"},
            "country_conflict": {"type": "boolean"},
        },
    }



def _derived_view_schema(name: str) -> dict[str, Any]:
    if name == "derive_demand_anchor":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["account_id", "opportunity_id", "source_type", "source_evidence_ids", "product_profile_id", "geography"],
            "properties": {
                "account_id": {"type": "string", "minLength": 1},
                "opportunity_id": {"type": "string", "minLength": 1},
                "source_type": {"type": "string", "minLength": 1},
                "source_evidence_ids": _evidence_id_array(),
                "product_profile_id": {"type": "string", "minLength": 1},
                "product_variant": {"type": "string", "minLength": 1},
                "geography": {"type": "string", "minLength": 1},
                "shipment_date": {"type": "string"},
                "shipment_weight_kg": {"type": "number", "minimum": 0},
                "shipment_quantity": {},
                "container_or_teu": {},
                "destination_port": {"type": "string"},
                "supplier_ids": {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                "origin_country": {"type": "string"},
                "application_hypothesis": {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                "application_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "channel_signal": {"type": "boolean"},
                "supplier_signal": {"type": "boolean"},
            },
        }
    if name == "evaluate_product_opportunity":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["investigation_id", "opportunity_id", "assessment"],
            "properties": {
                "investigation_id": {"type": "string", "minLength": 1},
                "opportunity_id": {"type": "string", "minLength": 1},
                "assessment": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["commercial_value_grade", "commercial_value_score", "commercial_evidence_ids"],
                    "properties": {
                        "commercial_value_grade": {"enum": ["A+", "A", "A-", "B+", "B", "B-", "C", "D", "NQ"]},
                        "commercial_value_score": {"type": "number", "minimum": 0, "maximum": 100},
                        "commercial_evidence_ids": _evidence_id_array(),
                        "research_confidence": {"type": "number", "minimum": 0, "maximum": 100},
                        "lifecycle_target": {"enum": ["OPPORTUNITY_CREATED", "QUALIFIED_TARGET", "CONTACT_EXHAUSTION", "SALES_READY", "ANCHOR_ELIGIBLE", "FULLY_AUDITED"]},
                        "novelty_signals": {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                        "decision_basis": {"type": "string"},
                    },
                },
            },
        }
    raise KeyError(name)


def _mutation_schema(name: str) -> dict[str, Any]:
    controls = _mutation_controls()
    investigation = {"type": "string", "minLength": 1}

    if name == "append_candidate_discovery":
        properties = {
            "investigation_id": investigation,
            "candidate": {
                "type": "object",
                "additionalProperties": True,
                "required": [
                    "candidate_id",
                    "discovered_from_anchor_id",
                    "branch_group",
                    "branch",
                    "company_name",
                    "product_profile_id",
                ],
                "properties": {
                    "candidate_id": {"type": "string", "minLength": 1},
                    "discovered_from_anchor_id": {"type": "string", "minLength": 1},
                    "branch_group": {
                        "enum": [
                            "TRADE_GRAPH",
                            "APPLICATION_GRAPH",
                            "CHANNEL_GRAPH",
                            "MARKET_GRAPH",
                            "COMPETITIVE_GRAPH",
                            "CROSS_SELL_GRAPH",
                        ]
                    },
                    "branch": {"type": "string", "minLength": 1},
                    "company_name": {"type": "string", "minLength": 1},
                    "product_profile_id": {"type": "string", "minLength": 1},
                    "discovery_attempt_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "relationship_evidence_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
            **controls,
        }
        required = ["investigation_id", "candidate", "idempotency_key"]
    elif name == "create_product_opportunity":
        properties = {
            "investigation_id": investigation,
            "canonical_resolution": _canonical_resolution_schema(),
            "opportunity": {
                "type": "object",
                "additionalProperties": True,
                "required": [
                    "opportunity_id",
                    "account_id",
                    "product_profile_id",
                    "product_profile_version",
                    "product_profile_sha256",
                ],
                "properties": {
                    "opportunity_id": {"type": "string", "minLength": 1},
                    "account_id": {"type": "string", "minLength": 1},
                    "product_profile_id": {"type": "string", "minLength": 1},
                    "product_profile_version": {"type": "string", "minLength": 1},
                    "product_profile_sha256": {"type": "string", "pattern": r"^[0-9a-fA-F]{64}$"},
                    "application_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "buyer_archetype_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "market_cell_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
            **controls,
        }
        required = ["investigation_id", "canonical_resolution", "opportunity", "idempotency_key"]
    elif name == "promote_opportunity_anchor":
        properties = {
            "investigation_id": investigation,
            "opportunity_id": {"type": "string", "minLength": 1},
            "promotion_reason": {"type": "string", "minLength": 1},
            "anchor_eligibility": {
                "type": "object",
                "additionalProperties": True,
                "required": ["anchor_eligible"],
                "properties": {
                    "anchor_eligible": {"const": True},
                    "material_novelty_signals": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
            "cycle_dedup_complete": {"const": True},
            **controls,
        }
        required = [
            "investigation_id",
            "opportunity_id",
            "promotion_reason",
            "anchor_eligibility",
            "cycle_dedup_complete",
            "idempotency_key",
        ]
    else:
        raise KeyError(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _descriptor(name: str, *, read_only: bool) -> dict[str, Any]:
    planner = name in _PLANNERS
    if read_only:
        if name in {"derive_demand_anchor", "evaluate_product_opportunity"}:
            input_schema = _derived_view_schema(name)
        else:
            input_schema = {
                "type": "object",
                "properties": _base_properties(),
                "required": [],
                "additionalProperties": True,
            }
    else:
        input_schema = _mutation_schema(name)

    return {
        "name": name,
        "description": _DESCRIPTIONS[name],
        "inputSchema": input_schema,
        "outputSchema": {"type": "object"},
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False,
            "idempotentHint": not read_only,
        },
        "contract": {
            "planning_is_execution_proof": False if planner else None,
            "host_execution_required": True if planner else False,
            "sends_message": False,
            "server_side_draft_created": False,
            "mutation_boundary": None if read_only else "EXISTING_PRODUCTION_WAL_ONLY",
        },
    }

def build_v63_tool_descriptors() -> list[dict[str, Any]]:
    return [
        *(_descriptor(name, read_only=True) for name in V63_READ_ONLY_TOOL_NAMES),
        *(_descriptor(name, read_only=False) for name in V63_MUTATION_TOOL_NAMES),
    ]
