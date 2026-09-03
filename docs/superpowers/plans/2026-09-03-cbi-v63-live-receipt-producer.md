# CBI v6.3 Exact-Checkout Live Receipt Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce execution-backed backend-correlation and exact-recovery acceptance receipts by exercising the active v6.1 production MCP/recovery path in an isolated exact checkout.

**Architecture:** A private stdio JSON-RPC process harness resolves the active recovery entrypoint from `.mcp.json`, launches it with disposable persistence roots, drives real v6.3 mutations and handler-after-side-effect crash injection, extracts WAL/event evidence, and feeds the existing v6.3 validators. Exact-checkout success remains separate from Render/R2 readiness and never sets `production_ready=true`.

**Tech Stack:** Python 3.10/3.11 stdlib, subprocess + JSON-RPC stdio, existing v6.1 WAL/recovery adapter, existing v6.3 source-snapshot/correlation/recovery validators, unittest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-03-cbi-v63-live-receipt-producer-design.md`

## Global Constraints

- Work only on `cbi-v6-3-demand-expansion`; never update `cbi-v6-cloud-runtime-20260901` in this phase.
- All execution persistence must be redirected to disposable temporary roots.
- `execution_origin=LIVE_PRODUCTION_CHECKOUT` may be emitted only after launching and exercising the active production MCP/recovery entrypoint.
- `execution_environment=EXACT_CHECKOUT_ISOLATED` and `deployment_environment=NOT_RENDER_PRODUCTION` are mandatory artifact fields.
- Reference/synthetic reports can define required case inventories only; they cannot be promoted to live evidence.
- Recovery must never reexecute the mutation side effect.
- Correlation and canonical request hash must both match before recovery can claim a durable result.
- Wrong correlation/hash, duplicate exact events, missing proof, and cross-key claims fail closed.
- Raw idempotency keys must not appear in emitted acceptance artifacts or durable business event payload evidence.
- Source snapshot is calculated at runtime and validated again before artifact finalization.
- No artifact in this phase may set `production_ready=true`; `render_r2_acceptance_required=true` remains mandatory.

---

### Task 1: Feature-only TDD gate and anti-forgery producer boundary

**Files:**
- Create: `.github/workflows/cbi-v63-live-acceptance-ci.yml`
- Create: `tests/test_v63_exact_checkout_live_acceptance_producer.py`
- Create: `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ExactCheckoutAcceptanceConfig:
    repo_root: Path
    expected_git_sha: str
    output_dir: Path


def run_v63_exact_checkout_live_acceptance(
    config: ExactCheckoutAcceptanceConfig,
) -> dict[str, Any]:
    ...
```

The public producer interface accepts execution configuration only. It must not accept caller-provided backend reports, receipt envelopes, `passed` booleans, correlation verdicts, or reexecution verdicts.

- [ ] Add a feature-only GitHub Actions workflow listening only to `cbi-v6-3-demand-expansion`, with `contents: read`, Python 3.11, targeted producer tests, and v6.3 regression; no deployment or secrets.
- [ ] Write RED tests proving the producer module/API is absent and that the intended function signature cannot accept forged report/verdict arguments.
- [ ] Push RED and verify GitHub Actions fails specifically in the new targeted test.
- [ ] Implement the minimal dataclass/API shell. The shell validates configuration shape and fails closed with `ACCEPTANCE_EXECUTION_NOT_IMPLEMENTED`; it cannot emit live receipts yet.
- [ ] Push GREEN and verify targeted tests plus existing v6.3 regression pass.

### Task 2: Active MCP stdio process harness

**Files:**
- Create: `unified_runtime/exact_checkout_mcp_harness_v63.py`
- Modify: `tests/test_v63_exact_checkout_live_acceptance_producer.py`

**Interfaces:**

```python
class ExactCheckoutMcpHarness:
    def __init__(self, repo_root: Path, persistence_root: Path): ...
    def active_entrypoint(self) -> str: ...
    def start(self, *, crash_after_handler: str = "") -> None: ...
    def tool(self, request_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def crash_tool(self, request_id: int, name: str, arguments: dict[str, Any]) -> None: ...
    def stop(self) -> None: ...
```

- [ ] RED: prove the harness resolves the entrypoint through `resolve_active_mcp_entrypoint`, launches that file rather than `server_v61.py`, and initializes JSON-RPC over stdio.
- [ ] RED: `tools/list` must expose `append_candidate_discovery`, `create_product_opportunity`, and `promote_opportunity_anchor`.
- [ ] RED: crash injection sets `CBI_V61_TEST_CRASH_AFTER_HANDLER=<tool>` and requires process exit code 91.
- [ ] Implement process lifecycle using the proven pattern from `tests/test_v61_adapter_wal.py`, but do not import test helpers into production code.
- [ ] Redirect `CBI_SESSION_ROOT`, `CBI_HOST_PENDING_ROOT`, and Python bytecode output to the disposable acceptance root.
- [ ] GREEN targeted tests; verify the resolved entrypoint is the active recovery chain and not a synthetic/reference executable.

### Task 3: Exact source/git pinning and observable persistence reader

**Files:**
- Modify: `unified_runtime/exact_checkout_mcp_harness_v63.py`
- Modify: `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`
- Modify: `tests/test_v63_exact_checkout_live_acceptance_producer.py`

- [ ] RED: expected git SHA mismatch blocks before spawning a mutation process.
- [ ] RED: `build_v63_production_source_snapshot(repo_root)` must return `READY`; capture its snapshot SHA before any scenario.
- [ ] RED: finalization calls `validate_v63_production_source_snapshot`; a changed pinned source file blocks artifact issuance.
- [ ] Implement read-only helpers for the disposable session/event log and `mcp-idempotency-v61` WAL root derived from the isolated session root.
- [ ] Implement evidence normalization that exposes event sequence, event type, correlation id, request SHA, result snapshot/hash, and event counts without copying raw idempotency keys.
- [ ] GREEN targeted tests including snapshot drift.

### Task 4: Three real success-path scenarios

**Files:**
- Modify: `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`
- Modify: `tests/test_v63_exact_checkout_live_acceptance_producer.py`

- [ ] RED: execute a valid `append_candidate_discovery` through active MCP and prove exactly one `V63_CANDIDATE_DISCOVERED` event with matching mutation correlation and canonical request hash.
- [ ] RED: execute a valid `create_product_opportunity` and prove the exact result snapshot plus snapshot hash are durably bound to the event.
- [ ] RED: execute a valid `promote_opportunity_anchor` and prove exactly one anchor-promotion event with eligibility/cycle-dedup snapshots.
- [ ] Implement deterministic acceptance fixtures with unique synthetic IDs and no customer data.
- [ ] Derive `exact_correlation_proven` and `exact_request_hash_proven` from observed event/WAL evidence, never caller booleans.
- [ ] GREEN targeted tests.

### Task 5: Crash/restart exactly-once recovery for all three mutations

**Files:**
- Modify: `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`
- Modify: `tests/test_v63_exact_checkout_live_acceptance_producer.py`

- [ ] RED candidate crash: crash after `append_candidate_discovery` handler, require PREPARED WAL + one durable event, restart same active entrypoint, replay same request, and require event count remains one.
- [ ] RED opportunity crash: same sequence; recovered result must equal the exact persisted opportunity result snapshot and no second opportunity event may appear.
- [ ] RED anchor crash: same sequence; event count remains one and recovered result preserves durable eligibility/cycle-dedup semantics.
- [ ] Implement crash/restart executor using the same persistence root across both processes.
- [ ] Require recovered response mutation metadata to indicate replay/reconciliation when the active adapter exposes it; never infer success from process exit alone.
- [ ] GREEN targeted tests and existing v6.1 WAL tests.

### Task 6: Adversarial fail-closed acceptance cases

**Files:**
- Modify: `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`
- Modify: `tests/test_v63_exact_checkout_live_acceptance_producer.py`

- [ ] RED wrong correlation: acceptance fixture durable state has a nonmatching correlation and replay remains reconciliation-required.
- [ ] RED wrong request hash: matching correlation with wrong canonical request SHA remains reconciliation-required.
- [ ] RED duplicate exact event: two qualifying exact events must remain ambiguous and unreconciled.
- [ ] RED different-key claim: a second idempotency key cannot claim the first key's event/result.
- [ ] Build adversarial fixture state only inside disposable persistence roots; do not edit repository source and do not call the reference semantic helper as the execution path.
- [ ] GREEN all four scenarios with `reexecute_side_effect=false` derived from unchanged event/store counts.

### Task 7: Receipt builder, existing validators, and artifact contract

**Files:**
- Modify: `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`
- Create: `scripts/run_v63_exact_checkout_live_acceptance.py`
- Modify: `tests/test_v63_exact_checkout_live_acceptance_producer.py`

- [ ] RED: backend artifact must contain exactly the ten names from `REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS`, `adapter_path_exercised=EXISTING_PRODUCTION_INVOKE_MUTATION`, and `runtime_store_exercised=EXISTING_PRODUCTION_APPEND_ONLY_STORE`.
- [ ] RED: exact-recovery receipt envelope must contain exactly the case inventory required by `run_live_exact_recovery_acceptance`, with `execution_origin=LIVE_PRODUCTION_CHECKOUT` and `adapter_path_exercised=ACTIVE_PRODUCTION_SERVER_V61_RECOVERY_PATH` derived from the executed harness.
- [ ] Feed backend artifact into `validate_v63_backend_correlation_acceptance` and recovery envelope into `run_live_exact_recovery_acceptance`, pinned to the same runtime source snapshot.
- [ ] Write `V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json`, `V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json`, and `V63_EXACT_CHECKOUT_ACCEPTANCE.json` atomically in the requested output directory.
- [ ] Ensure top-level acceptance includes `execution_environment=EXACT_CHECKOUT_ISOLATED`, `deployment_environment=NOT_RENDER_PRODUCTION`, exact git SHA, exact source snapshot, `render_r2_acceptance_required=true`, and `production_ready=false`.
- [ ] Add CLI accepting only `--expected-git-sha` and `--output-dir`; nonzero unless both validators verify.
- [ ] Scan artifacts to ensure raw idempotency keys are absent.

### Task 8: Full exact-checkout acceptance and regression gates

**Files:**
- Modify: `.github/workflows/cbi-v63-live-acceptance-ci.yml`
- Test: all repository tests/protocols

- [ ] Run producer tests on Python 3.10 and 3.11 where practical; minimum release gate is Linux/Python 3.11 exact-checkout process acceptance.
- [ ] Run `python -m unittest discover -s tests -p 'test_v63_*.py' -q`.
- [ ] Run full `python -m unittest discover -s tests -p 'test_*.py' -q`.
- [ ] Run `python mcp/v6_protocol_test.py`.
- [ ] Run `python mcp/v61_hardening_protocol_test.py`.
- [ ] Run `git diff --check` and Python compile checks for new producer/harness/CLI modules.
- [ ] In feature-only CI, execute `scripts/run_v63_exact_checkout_live_acceptance.py --expected-git-sha $GITHUB_SHA --output-dir <temp>` and upload the three JSON artifacts only after the command succeeds.
- [ ] Verify production branch still equals `ba3bffdae13cef186b20b50335c3207fb3390ec6` before closing this phase.
- [ ] Do not merge or trigger Render/R2 from this workflow.

## Exact-Checkout Success Gate

This implementation phase is complete only when:

1. Real active MCP execution produces all required success/crash/adversarial evidence.
2. Backend correlation validator returns `verified=true`.
3. Live exact recovery validator returns `verified=true` on the same source snapshot.
4. Crash/restart proves no duplicate durable side effect for all three v6.3 mutations.
5. No raw idempotency key appears in generated artifacts.
6. Full repository and protocol regression is green.
7. Production branch is unchanged.
8. Top-level acceptance still says `production_ready=false` and `render_r2_acceptance_required=true`.

Only then proceed to isolated Render/R2/PVC deployment acceptance.