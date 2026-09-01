# CBI Research Orchestration v2 Design

## Goal

Preserve CBI v6.1's evidence governance, append-only durability, canonical identity, WAL, and R2 persistence while making host research exploratory rather than budget-blocked. CBI validates and persists conclusions; it must not prematurely stop useful research merely because a soft allocation is exhausted.

## Non-negotiable invariants

- Decision Saturation remains the only production research-closure authority.
- Budget exhaustion is a resource state, never research completion.
- FACT / INFERENCE / CONFLICT boundaries remain unchanged.
- Account-owned company routes may make outreach `COMPANY_ROUTE_READY`; they must never be promoted to a named person's direct route without separate ownership proof.
- R2, WAL, hash chain, append-only history, canonical registry, migration lineage, CRM gating, and send gating are unchanged.
- Existing public fields remain available where possible; new fields clarify ambiguous legacy semantics.

## Architecture

Add a new `V61ResearchOrchestrationHardeningMixin` at the front of the existing `UnifiedRuntime` MRO. The mixin delegates to the current production implementation through `super()` and then normalizes only derived planning, route, and completion views.

The overlay has four responsibilities:

1. **Soft-budget planner** — when the underlying planner returns `PAUSED_RESOURCE_LIMIT` but still has material deferred high-EIV work, promote that work back into executable objectives and mark the budget as softly exceeded.
2. **Canonical company route projection** — preserve the lower hardening layer's canonical Information History route projection and supplement it with safe account-owned routes from compiled observations. Only current, verified, non-guessed, channel-proven, buyer-owned routes qualify.
3. **Explicit decision/resource states** — expose independent `decision_state`, `resource_state`, and `research_action` instead of forcing callers to infer them from one overloaded status.
4. **Source-coverage semantics** — expose exhaustive public-source coverage as a read-only diagnostic without rewriting the mutation-sensitive Closure snapshot. The existing Closure result remains an exact, replayable decision snapshot; callers must not treat its legacy `network_complete` field as proof of exhaustive source coverage.

## Route eligibility

A compiled observation can become a company route only when all of the following are true:

- `claim_key == contact.company_route`
- `result == POSITIVE`
- `owner_type == ACCOUNT`
- `owner_id == canonical account id`
- route value contains supported channel + non-empty value
- `verified == true`
- `channel_proof == true`
- `guessed == false`
- source freshness is current/recent

An Information Record remains governed by the existing canonical route projection. This overlay does not re-parse raw Information History; it preserves lower-layer compatibility and only accepts an already-canonical route when:

- `information_type == ROUTE`
- `route_scope == BUYER_DIRECT`
- `outreach_eligible_effective == true`
- `subject_owner_id == canonical account id`
- temporal status is current/recent
- route value is verified, channel-proven, and not guessed

Person-owned records, cross-entity records, identity-only records, and unverified numbers are never upgraded by this overlay.

## Planner semantics

When the legacy planner reports zero remaining units:

- If material deferred objectives remain, return them in `objectives` while preserving `status=PAUSED_RESOURCE_LIMIT` for backward compatibility, also expose `legacy_status=PAUSED_RESOURCE_LIMIT`, `resource_state=SOFT_BUDGET_EXCEEDED`, and `research_action=CONTINUE_HIGH_EIV_RESEARCH`. Host orchestration must use `research_action` rather than treating the pause status as completion.
- Keep the original budget numbers unchanged for auditability.
- If no high-value work remains, leave the underlying status intact and expose `research_action=NO_HIGH_EIV_WORK`.

## Completion and source-coverage semantics

Decision Saturation remains unchanged. The overlay adds to the read-only decision view:

- `decision_state = SATURATED | NOT_SATURATED`
- `resource_state = WITHIN_BUDGET | EXHAUSTED`
- `research_action = NO_HIGH_EIV_WORK | CONTINUE_HIGH_EIV_RESEARCH | RESOLVE_BLOCKERS | REASSESS`

`plan_public_source_calls` additionally returns:

- `source_coverage_complete`
- `source_coverage_status = PROVEN_COMPLETE | INCOMPLETE`
- `remaining_source_attempt_count_at_least`

`get_account_state` exposes the same current source-coverage diagnostic under `source_coverage`. A truncated planner response can never prove completeness.

The production `evaluate_investigation_closure` mutation result is deliberately **not** overridden by this overlay. Closure recovery persists and reconstructs an exact Decision Saturation snapshot; adding later/current source-coverage calculations to that result would break exact crash-replay semantics. The legacy Closure `network_complete` field therefore remains compatibility data and is explicitly documented as **not** exhaustive-source proof. Closure authority remains Decision Saturation, not 100% source coverage.

## Compatibility

The overlay is intentionally additive and reversible. It does not rewrite old events, Closure receipts, WAL results, or recovery snapshots. Existing Closure fields remain byte/semantic compatible; the new read-only source-coverage fields remove the need for callers to overload `network_complete`.
