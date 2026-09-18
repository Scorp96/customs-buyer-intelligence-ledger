# CBI v6.3 Active MCP Surface Release Gate Design

**Date:** 2026-09-08

## Problem

Fresh production diagnostics can expose the v6.3 demand-expansion contract and show all three v6.3 mutation families in WAL/reconciliation inventories while the actual ChatGPT/MCP tool surface still omits v6.3 candidate/opportunity tools. Contract presence therefore does not prove callable MCP exposure.

## Goal

Make v6.3 production readiness fail closed unless host-derived evidence proves that the active MCP entrypoint's tool listing contains every v6.3 read-only and mutation tool declared by `mcp_schema_v63.py`.

## Invariants

- CBI Runtime business semantics remain unchanged.
- No new WAL, durable store, event type, mutation path, scoring rule, EIV rule, or customer-state mutation is introduced.
- `mcp_schema_v63.py` remains the source of truth for required v6.3 tool names.
- Runtime contract and WAL inventory cannot substitute for an observed active MCP tool listing.
- MCP surface evidence is bound to the exact current production source snapshot SHA-256.
- Missing, stale, malformed, or incomplete MCP surface evidence blocks production release.

## Evidence contract

Schema: `cbi.v63-mcp-surface-evidence.v1`

Required evidence fields are the exact production source snapshot SHA-256, `active_entrypoint_observed=true`, `tools_list_observed=true`, and the actual active MCP `tool_names`.

The report must come from the active production MCP entrypoint's real tool-list response. Static descriptors, Runtime contract declarations, staging schemas, and source inspection alone are insufficient.

## Gate semantics

`evaluate_v63_production_gate()` computes the required active set from `V63_READ_ONLY_TOOL_NAMES ∪ V63_MUTATION_TOOL_NAMES`. Missing names add `V63_ACTIVE_MCP_SURFACE_INCOMPLETE` and are returned in `missing_active_mcp_tools`.

`evaluate_v63_release_evidence_bundle()` validates the MCP-surface evidence and exposes it under `component_validations.mcp_surface`. Invalid evidence contributes an empty active surface to the production gate, forcing fail-closed behavior.

## Boundary

This hardens release eligibility only. It does not itself deploy or activate the v6.3 adapter, modify buyer state, change EIV/scoring, or promote production.
