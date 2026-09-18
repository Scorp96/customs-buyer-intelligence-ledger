# CBI v6.3 Exact-Checkout Live Receipt Producer Design

## Goal

Add a production-grade acceptance producer that generates **execution-backed** v6.3 live recovery and backend-correlation receipts from an exact feature checkout. The producer must exercise the active v6.1 production MCP mutation/recovery path and existing append-only durability primitives; it must not synthesize, relabel, or copy reference-runner results and call them live evidence.

This phase proves the exact checkout before any production merge. It does **not** prove Render/R2 deployment health and must not set `production_ready=true` by itself.

## Current verified baseline

- Feature branch: `cbi-v6-3-demand-expansion`.
- Expanded v6.3 feature commit: `4a3b61e34e368a498857cf62cc81cb260fbf9d75`.
- Production branch remains pinned to `ba3bffdae13cef186b20b50335c3207fb3390ec6`.
- Bootstrap attestation reports repository tests, v6 protocol, and v6.1 hardening protocol passing.
- v6.3 static integration proves delegated server overlay, sync recovery extension, static correlation bridge, and ten deterministic reference no-reexecution scenarios.
- Existing validators reject reference/synthetic evidence but there is no producer that can currently create execution-backed `LIVE_PRODUCTION_CHECKOUT` receipts.

## Non-negotiable invariants

1. **No production mutation.** The producer runs only in an isolated exact checkout with temporary persistence roots unless an explicit later deployment acceptance phase provides isolated disposable production-like storage.
2. **No evidence relabeling.** `execution_origin=LIVE_PRODUCTION_CHECKOUT` may be emitted only by code that actually launched and exercised the active production MCP/recovery path in that checkout.
3. **No reference promotion.** `run_v63_reference_recovery_acceptance()` may define the required semantic case inventory, but its results cannot be copied into live receipts.
4. **No side-effect reexecution.** Recovery of a prepared mutation must never invoke the mutation side effect a second time.
5. **Exact correlation.** A recovery claim must match both mutation correlation identity and canonical request hash.
6. **Cross-key isolation.** A second idempotency key must never claim the first key's durable result.
7. **Fail closed on ambiguity.** Wrong correlation, wrong request hash, duplicate exact events, missing events, or ambiguous durable state must remain unreconciled rather than guessing a result.
8. **Raw idempotency keys are not durable business payload.** Receipts may include a receipt identifier, but durable correlation evidence must not leak the raw idempotency key into business events.
9. **Snapshot pinning.** Every acceptance artifact must be pinned to the exact production-source snapshot calculated from the checkout under test.
10. **Separate gates remain separate.** Exact-checkout acceptance is necessary but insufficient for Render/R2/PVC live production readiness.

## Architecture

Introduce a new exact-checkout acceptance producer with four isolated responsibilities.

### 1. Active MCP process harness

A small harness launches the **actual active v6.1 production recovery entrypoint** used by the feature candidate, over stdio JSON-RPC, with temporary `CBI_SESSION_ROOT`, `CBI_HOST_PENDING_ROOT`, idempotency/WAL roots, and other persistence paths redirected to a disposable directory.

The harness exposes only:

- initialize process;
- call a mutation tool;
- invoke a crash-injected mutation call;
- restart the exact same active entrypoint against the same persistence roots;
- read resulting structured response, durable events, WAL state, and append-only store evidence;
- terminate cleanly.

It must not import a simplified reference backend as the execution path.

### 2. Scenario executor

The executor covers the exact ten backend-correlation scenarios already required by `REQUIRED_V63_BACKEND_CORRELATION_SCENARIOS`:

- `CANDIDATE_SUCCESS_EVENT_CORRELATED`
- `CANDIDATE_RECOVERY_NO_REEXECUTION`
- `OPPORTUNITY_SUCCESS_SNAPSHOT_CORRELATED`
- `OPPORTUNITY_RECOVERY_EXACT_SNAPSHOT`
- `ANCHOR_SUCCESS_EVENT_CORRELATED`
- `ANCHOR_RECOVERY_NO_REEXECUTION`
- `WRONG_CORRELATION_FAILS_CLOSED`
- `WRONG_REQUEST_HASH_FAILS_CLOSED`
- `AMBIGUOUS_DUPLICATE_EVENT_FAILS_CLOSED`
- `DIFFERENT_KEY_CANNOT_CLAIM_RESULT`

The first six must execute the corresponding real v6.3 mutations through the active production adapter. Crash/recovery cases use the existing handler-after-side-effect crash injection mechanism and restart the same checkout against the same durable state.

The final four are adversarial reconciliation cases. They must mutate or construct only the **acceptance fixture state inside the disposable checkout**; they must never edit repository source or production data. Each must prove fail-closed behavior through the active recovery semantics rather than by directly calling the reference semantic helper and copying its outcome.

### 3. Evidence extractor and receipt builder

The extractor reads observable evidence created by the real run:

- active MCP/recovery entrypoint identity;
- exact source snapshot SHA-256;
- WAL state before and after restart;
- mutation correlation id from durable event/WAL evidence;
- canonical request hash;
- durable event count before and after recovery;
- returned exact result snapshot where applicable;
- whether any mutation side effect was invoked after restart;
- whether a different idempotency key claimed an existing result;
- recovery status and blockers.

It then produces two artifacts from the same underlying executions:

1. `cbi.v63-backend-correlation-acceptance.v1`
2. `cbi.v63-live-exact-recovery-receipts.v1`

The producer must compute verdict fields from observed evidence. It must never accept caller-supplied booleans such as `passed=true`, `exact_correlation_proven=true`, or `reexecute_side_effect=false` without deriving them from the run.

### 4. Existing validators remain release authority

The producer does not replace existing validators. Its artifacts are fed into:

- `validate_v63_backend_correlation_acceptance(...)`
- `run_live_exact_recovery_acceptance(...)`

A producer run succeeds only when both validators return verified against the same exact source snapshot.

## Execution origin semantics

The term `LIVE_PRODUCTION_CHECKOUT` means **the active production code path of the exact checkout under acceptance**, not the public production deployment.

To prevent ambiguity, every producer artifact must also carry:

- `execution_environment = EXACT_CHECKOUT_ISOLATED`
- `deployment_environment = NOT_RENDER_PRODUCTION`
- exact git commit SHA;
- exact production-source snapshot SHA-256.

The release evidence gate must continue to require a later Render/R2 acceptance artifact before declaring production readiness.

## Mutation flow

For a success scenario:

1. Build deterministic valid arguments with a unique acceptance namespace.
2. Call the real mutation through active MCP JSON-RPC.
3. Capture structured result.
4. Read WAL/durable event evidence.
5. Prove event correlation id and request hash correspond to that mutation request.
6. Prove the expected durable event/result exists exactly once.
7. Emit the scenario evidence.

For a crash/recovery scenario:

1. Build deterministic valid arguments and a unique idempotency key.
2. Launch active MCP entrypoint with handler-after-side-effect crash injection enabled for that tool.
3. Call the mutation and require the process to terminate with the expected crash code before returning a normal RPC result.
4. Record the prepared WAL and exactly-once durable side effect/event created before crash.
5. Restart the active production recovery entrypoint against the same persistence roots.
6. Reissue the same mutation request.
7. Require recovery/reconciliation behavior defined by the active adapter path.
8. Compare event/store counts before and after restart and prove no side-effect reexecution occurred.
9. Emit receipt evidence from the observed pre/post state.

## Exact-result rules by v6.3 mutation

### `append_candidate_discovery`

- prove exactly one candidate-discovered durable event for the successful correlation;
- recovery must not append a second candidate event;
- wrong correlation, wrong request hash, duplicate exact event, and different-key claim must fail closed.

### `create_product_opportunity`

- prove the success result snapshot is durably bound to the exact correlation/request;
- recovery must return or reconstruct the exact persisted snapshot without executing opportunity creation again;
- snapshot hash mismatch must not be accepted.

### `promote_opportunity_anchor`

- prove exactly one anchor-promotion durable event;
- recovery must not append a second anchor promotion;
- recovery must preserve anchor eligibility/cycle-dedup semantics and fail closed when those durable conditions are invalid.

## Source snapshot binding

The producer must calculate the source snapshot at runtime using the existing v6.3 production source snapshot function. It must not hard-code the currently attested snapshot.

The run is blocked if:

- snapshot calculation is not `READY`;
- the checkout git SHA differs from the expected acceptance commit supplied by the caller;
- source files change between scenario execution and artifact finalization;
- backend-correlation and exact-recovery artifacts report different source snapshots.

## Files and interfaces

Recommended implementation boundaries:

- `unified_runtime/exact_checkout_live_acceptance_producer_v63.py`
  - orchestration and evidence construction only;
  - no CLI parsing.
- `scripts/run_v63_exact_checkout_live_acceptance.py`
  - CLI wrapper;
  - accepts expected git SHA and output directory;
  - exits nonzero unless both validators verify.
- `tests/test_v63_exact_checkout_live_acceptance_producer.py`
  - TDD coverage for execution-backed evidence, crash/recovery, source drift, fail-closed adversarial cases, and anti-forgery behavior.

If existing low-level MCP test-process helpers can be safely extracted without changing production semantics, a private helper module may be introduced. Do not import helper methods directly from `tests/` into production code.

## Artifact contract

A successful run writes, at minimum:

- `V63_EXACT_CHECKOUT_BACKEND_CORRELATION.json`
- `V63_EXACT_CHECKOUT_RECOVERY_RECEIPTS.json`
- `V63_EXACT_CHECKOUT_ACCEPTANCE.json`

`V63_EXACT_CHECKOUT_ACCEPTANCE.json` contains:

- schema/version;
- git commit SHA;
- production-source snapshot SHA-256;
- execution/deployment environment labels;
- backend-correlation validator result;
- live exact-recovery validator result;
- scenario count and names;
- explicit `render_r2_acceptance_required=true`;
- explicit `production_ready=false`.

No artifact generated by this phase may set `production_ready=true`.

## Error handling

The producer fails closed and exits nonzero on any of the following:

- active MCP entrypoint cannot initialize;
- expected v6.3 mutation is not present in the live tool inventory;
- crash injection does not crash at the expected boundary;
- WAL is missing, committed too early, malformed, or detached from durable correlation evidence;
- durable event count increases during recovery where no reexecution is permitted;
- correlation id/request hash mismatch;
- exact persisted result cannot be reconstructed;
- source snapshot drift;
- scenario inventory differs from the validator-required inventory;
- a validator returns blocked;
- the harness detects use of reference/synthetic adapter as the producer execution path.

Failure artifacts may contain diagnostic metadata but must never contain raw secrets or raw idempotency keys copied from internal persistence.

## Testing strategy

Implementation follows strict TDD.

### RED 1 — anti-forgery boundary

Write a test proving a caller cannot hand the producer a prebuilt reference report or booleans and obtain live-verified output. The producer interface should accept execution configuration, not a caller-provided verdict report.

### RED 2 — real success path

Write a test that launches the exact active MCP path in a disposable checkout, executes a v6.3 mutation, and proves the emitted correlation/request-hash evidence comes from the resulting WAL/durable event.

### RED 3 — crash/restart no-reexecution

Inject crash after the handler side effect, restart against the same persistence roots, replay the same request, and assert the relevant durable event/result count remains exactly one.

### RED 4 — adversarial fail-closed cases

Exercise wrong correlation, wrong request hash, ambiguous duplicate exact event, and different-key claim through acceptance fixture durable state and require validator-compatible fail-closed evidence.

### RED 5 — snapshot drift

Change the checkout after scenario execution in a test fixture and require finalization to fail rather than issue an acceptance artifact.

### GREEN / regression

After targeted tests pass, run:

- new producer tests;
- all `test_v63_*.py` tests;
- full repository `unittest discover`;
- `mcp/v6_protocol_test.py`;
- `mcp/v61_hardening_protocol_test.py`;
- `git diff --check`.

## Success criteria

This exact-checkout phase succeeds only when all are true:

1. All ten required backend-correlation scenarios are produced from execution-backed evidence.
2. `validate_v63_backend_correlation_acceptance` returns `verified=true` pinned to the exact source snapshot.
3. `run_live_exact_recovery_acceptance` returns `verified=true` for the same source snapshot.
4. Crash/recovery cases prove no side-effect reexecution.
5. Wrong-correlation/hash, duplicate, and cross-key cases fail closed.
6. No raw idempotency key is persisted into durable business event evidence.
7. Full v6/v6.1/v6.3 regression remains green.
8. Production branch remains unchanged.
9. Final artifact says `production_ready=false` and `render_r2_acceptance_required=true`.

## Stop / failure conditions

Stop this route and redesign before any deployment if any of the following is observed:

- the active production MCP path cannot expose enough observable evidence to prove exact correlation without modifying production semantics;
- crash injection cannot reliably occur after side effect but before committed WAL result;
- existing persistence abstractions cannot be isolated to disposable roots;
- proving an adversarial case would require editing repository source or using real customer/production data;
- successful recovery requires reexecuting a mutation side effect;
- source snapshot cannot be stably pinned across the run.

## Next gate after exact-checkout acceptance

Only after this producer and its acceptance artifacts pass should the project proceed to an isolated Render preview using production-like R2/object-store configuration. That later gate must prove deployment boot, active tool contract, R2 append/restore roundtrip, crash/recovery against deployed storage, and a disposable PVC demand-expansion scenario before the release evidence gate may consider `production_ready=true`.
