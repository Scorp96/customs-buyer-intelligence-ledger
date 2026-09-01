# CBI Research Orchestration v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CBI research exploration soft-budgeted, expose unambiguous completion states, and project verified company-owned routes without weakening named-route safety.

**Architecture:** Add a front-of-MRO `V61ResearchOrchestrationHardeningMixin` that wraps existing v6.1 production methods using `super()`. It modifies only derived planner/route/completion views and leaves persistence, evidence validation, WAL, hash chain, canonical registry, R2, CRM, and send behavior untouched.

**Tech Stack:** Python 3.11, unittest, existing CBI UnifiedRuntime mixin architecture.

**Spec:** `docs/superpowers/specs/2026-09-01-cbi-research-orchestration-v2-design.md`

## Global Constraints

- Decision Saturation remains the only research closure authority.
- Budget exhaustion is not completion.
- Company route readiness must not imply named-person route ownership.
- Existing production persistence and mutation layers are out of scope.
- New behavior must be supplied as an overlay; do not rewrite `unified_runtime/v6.py`.

---

### Task 1: Soft-budget objective planner

**Files:**
- Create: `unified_runtime/research_orchestration_hardening.py`
- Test: `tests/test_v61_research_orchestration_hardening.py`

**Interfaces:**
- Consumes: `super().get_next_research_objectives(arguments)` result.
- Produces: backward-compatible `PAUSED_RESOURCE_LIMIT` status plus `legacy_status`, `resource_state`, `research_action`, and visible material deferred objectives after soft budget exhaustion.

- [ ] Write failing tests for material deferred objectives after budget exhaustion and no-work behavior.
- [ ] Run tests and confirm RED because the new mixin does not exist.
- [ ] Implement minimal planner normalization.
- [ ] Run tests and confirm GREEN.

### Task 2: Canonical account-owned company route projection

**Files:**
- Modify: `unified_runtime/research_orchestration_hardening.py`
- Test: `tests/test_v61_research_orchestration_hardening.py`

**Interfaces:**
- Consumes: `_v6_state(investigation_id)` and `super().evaluate_outreach_readiness(arguments)`. The lower readiness layer remains the sole parser/normalizer of append-only Information History.
- Produces: `canonical_route_view`, company route IDs, and `COMPANY_ROUTE_READY` only when buyer-owned route proof is valid.

- [ ] Write failing tests for compiled official routes, preservation of lower-layer canonical Information routes, person-owned/unverified route rejection, and no duplicate re-parsing of legacy Information History.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement route collectors and readiness projection.
- [ ] Run targeted tests and confirm GREEN.

### Task 3: Decision/resource state separation and read-only source coverage

**Files:**
- Modify: `unified_runtime/research_orchestration_hardening.py`
- Test: `tests/test_v61_research_orchestration_hardening.py`

**Interfaces:**
- Consumes: `super().evaluate_decision_saturation`, `super().plan_public_source_calls`, and read-only `super().get_account_state`.
- Produces: `decision_state`, `resource_state`, `research_action`, `source_coverage_complete`, `source_coverage_status`, and account-state source-coverage diagnostics.
- Does **not** override the mutation-sensitive `evaluate_investigation_closure`; exact Closure WAL/recovery snapshots remain unchanged.

- [ ] Write failing tests for exhausted-but-unsaturated, saturated-and-exhausted, missing-source coverage, and account-state coverage projection.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement derived-state normalization without changing the underlying Decision Saturation or Closure mutation verdict.
- [ ] Run targeted tests and confirm GREEN.

### Task 4: MRO and contract integration

**Files:**
- Modify: `unified_runtime/__init__.py`
- Modify: `unified_runtime/research_orchestration_hardening.py`
- Test: `tests/test_v61_research_orchestration_hardening.py`

**Interfaces:**
- Produces: `V61ResearchOrchestrationHardeningMixin` at the front of `UnifiedRuntime` MRO and `research_orchestration_v6_2` contract metadata.

- [ ] Add contract test describing soft budget, route ownership, and completion semantics.
- [ ] Add MRO import/insertion patch.
- [ ] Run full overlay unit suite.
- [ ] Syntax-check production module.
- [ ] Package a commit-ready patch and application script.
