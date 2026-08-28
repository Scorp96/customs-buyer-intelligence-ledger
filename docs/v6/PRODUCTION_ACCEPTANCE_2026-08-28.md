# Customs Buyer Intelligence v6.1 — Production Acceptance Status

Date: 2026-08-28

Branch: `cbi-v6-20260828`

Baseline import commit: `c9588e0fbb5c24a4329a4d1270d091f3dc52178a`

Draft PR: `#1` — **do not merge** until the remaining production blockers are closed and the final acceptance matrix is rerun.

## Current status

**V6.1 CONTRACT HARDENING ACTIVE — CROSS-PLATFORM REGRESSION GREEN — PRODUCTION ACCEPTANCE NOT YET COMPLETE**

The implementation is now reproducibly green in independent GitHub runners on Windows and Linux. Several specification gaps have been closed or materially reduced, but remaining data-model/commercial/golden/load gates still prevent a Production Ready declaration.

## Independent cold-CI verification

The GitHub workflow checks out a clean merge ref and does not depend on the local Codex/Work Python environment.

| Environment | Result | Unit suite | MCP compatibility | MCP v6 protocol | MCP v6.1 production adapter | Privacy |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Ubuntu 24.04 / Python 3.11 | PASS | 136/136 | 58/58 | 30/30 | 10/10 | PASS |
| Windows Server 2025 / Python 3.11 | PASS | 136/136 | 58/58 | 30/30 | 10/10 | PASS |

CI also validates JSON manifests, validates `agents/openai.yaml` using an ephemeral CI-only PyYAML install, and runs parser/intelligence/outreach/strategic/v3 compatibility self-tests.

## Closed or materially hardened items

### PASS — Plugin entry point uses Decision Saturation semantics

The plugin manifest no longer tells the Host to stop because an Anchor/Pivot queue is merely saturated. It now requires Claim/Pivot/Anchor/EIV Decision Saturation and explicitly rejects fixed queue, fixed depth or Source Family coverage as closure authority.

### PASS — Production MCP public closure contract is Decision-Saturation-first

`.mcp.json` launches `mcp/server_v61.py`. On this production adapter, `start_investigation.network_policy.closure_strategy` is exposed as `DECISION_SATURATION`; a caller that explicitly sends `QUEUE_PIVOT_SATURATION` is rejected. The original compatibility server remains available to historical regression/migration code rather than being silently rewritten.

### PARTIAL/PASSING TESTS — Durable idempotency and optimistic version guards

The production adapter now supports:

- durable `idempotency_key` receipts;
- request/result hashes;
- exact replay of a committed result;
- same-key/different-request conflict rejection;
- `expected_state_version` stale-writer rejection;
- mutation metadata containing before/after state versions;
- replay precedence over a stale retry version.

Cold adapter protocol tests pass on Windows and Linux.

**Remaining strict-spec gap:** `idempotency_key` is still optional during the compatibility transition. The v6 specification ultimately requires it on every mutation API. The generic adapter journal also does not yet prove a zero-window transaction that atomically couples every legacy mutation with its adapter receipt; critical native paths have their own stronger deterministic/idempotent controls, but the uniform envelope is not yet a complete Source-of-Truth transaction layer.

### PASS — Complete Customs Party Role vocabulary is accepted/exposed

The v6.1 hardening layer exposes and validates BUYER, CONSIGNEE, IMPORTER_OF_RECORD, EXPORTER, SHIPPER, DECLARED_MANUFACTURER, PROBABLE_MANUFACTURER, TRADING_INTERMEDIARY, CUSTOMS_BROKER, NOTIFY_PARTY, FORWARDER and SUPPLIER_GROUP. A compatibility alias for `PROBABLE_ACTUAL_MANUFACTURER` is retained.

**Remaining model improvement:** shipment role, commercial/business role and buyer relationship are still not first-class independent dimensions everywhere.

### PASS — Freshness vocabulary now distinguishes Current Confirmed vs Current Likely

The public/runtime vocabulary now includes `CURRENT_CONFIRMED` and `CURRENT_LIKELY` while retaining legacy aliases for backward compatibility.

**Remaining audit:** older internal compatibility rules that still treat `CURRENT`/`RECENT` as equivalent need progressive migration before legacy aliases can be retired.

### STRUCTURALLY RESOLVED — Resume returns a LAST_SAFE_STATE payload

`resume_investigation` now includes last committed mutation, pending host bundles, current objectives, critical conflicts, material open pivots and portfolio priority. Basic regression is green. A populated production investigation still needs live regression after deployment.

### STRUCTURALLY RESOLVED — `get_account_state` exposes the full v6 view

The hardening layer adds structured identity, brands, products, trade, suppliers, buying group, contacts, routes, claims, conflicts, network, material pivots, next objectives and v6 CRM sync state. No absent information is fabricated; empty dimensions remain empty.

### PARTIAL — Canonical Route View now includes safe append-only Information Records

Outreach readiness no longer has to rely exclusively on compiled `contact.company_route` / `contact.named_route` observations. The hardening layer derives a Canonical Route View from current, verified, account-owned, BUYER_DIRECT append-only Information Records and keeps the route safety gates (not masked, not guessed, channel proof where needed, source lineage present).

This directly addresses the previously observed class of Information-History-vs-Outreach-Readiness drift.

**Remaining acceptance gate:** rerun the exact populated Western Woods/C001 route regression before declaring this bug class fully closed.

### PASS — Durable append-only runtime and crash/integrity controls remain green

Regression continues to cover hash-chain integrity, corrupt-tail quarantine, dead-process lock recovery, concurrent writers, closure tail-change protection and migration source preservation.

### PASS — Batch compiler / host queue / peer / CRM safety regressions remain green

Exactly-once bundle replay, host queue recreation/sync, peer staged promotion, Commercial/Research/Outreach separation, CRM receipt validation and guarded draft-only outreach remain green in cold CI.

## Open Production blockers

### P0-01 — Canonical Pivot state machine is still incomplete

The v6 implementation still stores/uses compatibility Pivot statuses such as `OPEN`, `NOT_MATERIAL` and `BLOCKED`. The target canonical states are `OPEN_MATERIAL`, `OPEN_OPTIONAL`, `CONSUMED`, `DUPLICATE`, `LOW_VALUE`, `BLOCKED` and `EXHAUSTED`.

Only `OPEN_MATERIAL` should block Decision Saturation. The current implementation still treats `BLOCKED` as part of `_material_pivots`, so this remains a real semantic gap rather than a naming-only issue.

### P0-02 — Uniform mutation envelope is not yet mandatory/atomic everywhere

The adapter implementation is tested and useful, but strict Production acceptance still requires mandatory `idempotency_key` for every mutation, one canonical persisted mutation envelope, atomic coupling between mutation commit and mutation receipt (or an equivalent recoverable write-ahead protocol), and typed replay/conflict semantics across every mutation family.

### P0-03 — Current Decision Chain evidence boundary needs a dedicated prerequisite model

A positive person association must not automatically prove current purchasing authority. Decision-chain support should require evidence-bound named person, current company association, current or sufficiently recent role, role/procurement relevance and authority scope/confidence.

This is required to prevent recurrence of the previously observed case where a record explicitly said “not yet verified current purchasing decision maker” while the aggregate Decision Chain Claim was nevertheless supported.

### P0-04 — Commercial Opportunity model is still under-featured

Commercial Value is correctly independent from CRM/contact readiness, but it still relies mainly on weighted Claims and does not expose the complete evidence-bound opportunity model required by v6: visible volume, purchase frequency, shipment size, supplier diversity/concentration, recency, recent supplier change, annualized visible volume, growth and replacement window.

Do **not** fix the Western Woods grade regression by lowering a score threshold. Add evidence-bound opportunity dimensions first, then rerun golden cases.

### P0-05 — Production portfolio lifecycle/dedup requires live reconciliation

Prior live state showed duplicate/placeholder/test investigations and multiple active states for the same canonical account. Source hardening in this branch has not yet proven that the deployed portfolio excludes TEST/MIGRATION/SUPERSEDED/ARCHIVED investigations or enforces one active investigation per canonical account + scope.

The required lifecycle should support the equivalent of ACTIVE, SUPERSEDED, ARCHIVED, TEST, MIGRATION_ONLY and QUARANTINED.

### P0-06 — Real golden cases have not yet been rerun on this exact hardened head

Current repository fixtures are synthetic regression metadata. Production acceptance still requires real persisted regression for at least Western Woods, Arecibo Home Center, Arecibo Home Design, Chimelis Home Center, Tesoro en Maderas II, Forza Distribution, Edwin Seda and Hangzhou Promise.

Previous live findings (Western Woods A- vs expected >= A, Arecibo canonical entities not present, Route/Decision-Chain drift) remain regression targets until explicitly rerun and closed.

### P1-01 — Full performance/scalability targets are not yet demonstrated

The current suite includes a 1,000-observation deterministic load test, but it does not yet prove the complete target envelope: 100 Evidence Bundle < 5 s local, simple state query < 500 ms, Resume < 3 s, 10k evidence / 1k pivots / 500 peers per large investigation, 5,000 canonical accounts, 1,000 simultaneous investigations, 100k evidence/source attempts and 20k peers.

A dedicated benchmark/load workflow is still required.

### P1-02 — Remote transport outage is distinct from local host-queue durability

Local/process-independent HostBundleQueue durability is strongly covered and green. A ChatGPT-to-remote-MCP transport failure still cannot invoke an MCP tool through the failed tunnel. If remote always-online queueing is a requirement, it needs a separately reachable authorized host-side persistence service or equivalent architecture.

## Merge gate

PR #1 remains Draft and must not be merged until, at minimum:

1. canonical Pivot state semantics are implemented and tested;
2. uniform mutation idempotency/atomicity is brought to the strict production contract;
3. Decision Chain prerequisite/evidence-boundary regression is green;
4. Commercial Opportunity factors are implemented without threshold gaming;
5. portfolio lifecycle/canonical-active-investigation rules are verified against real deployed state;
6. real golden cases are rerun on the hardened head;
7. crash/offline/load acceptance is completed at target scale;
8. Windows + Linux cold CI remains green after those changes.

Only then should the branch be considered for merge into `main` or a Production Ready declaration.
