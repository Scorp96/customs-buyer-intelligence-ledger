# Customs Buyer Intelligence v6.1 — Production Acceptance Status

Date: 2026-08-28

Branch: `cbi-v6-20260828`

Baseline import commit: `c9588e0fbb5c24a4329a4d1270d091f3dc52178a`

Acceptance hardening commits:

- `55c5f6d5f4a996b0281dc7a1183e6a1aa9aa1a15` — align plugin entry prompt with Decision Saturation.
- `f5e4bd39744839de9f81ff24e9b420199afb6f1f` — add independent Windows/Linux CI.

Draft PR: `#1` — **do not merge** until the open contract/runtime blockers below are closed and the full acceptance matrix is rerun.

## Current status

**V6.1 REGRESSION GREEN — PRODUCTION CONTRACT HARDENING OPEN**

This branch is materially stronger than the previous runtime, but it is **not yet declared Production Ready**. Passing regression proves that the implemented invariants are stable; it does not prove that every v6 specification requirement is implemented.

## Independent cold-CI verification

A new GitHub Actions workflow checks out a clean tree and runs without relying on the local Codex/Work environment.

| Environment | Result | Unit suite | MCP compatibility | MCP v6 protocol | Privacy |
| --- | --- | ---: | ---: | ---: | --- |
| Ubuntu 24.04 / Python 3.11 | PASS | 133/133 | 58/58 | 30/30 | PASS |
| Windows Server 2025 / Python 3.11 | PASS | 133/133 | 58/58 | 30/30 | PASS |

The CI also validates JSON manifests, validates `agents/openai.yaml` with an ephemeral CI-only PyYAML install, and runs the compatibility parser, intelligence, outreach, strategic and v3 self-tests.

## Confirmed strengths

### PASS — Durable append-only runtime and crash/integrity controls

The current regression covers append-only hash-chain integrity, corrupt-tail quarantine, dead-process lock recovery, concurrent session writers, closure tail-change protection and migration source preservation.

### PASS — Batch Evidence Compiler and exactly-once replay

The regression covers partial success, deterministic observation identity, concurrent identical bundle replay, host bundle synchronization and pending receipt synchronization.

### PASS — Claim-driven / EIV / Decision Saturation core

The v6 extension declares `completion_policy = DECISION_SATURATION`; budget exhaustion pauses rather than closes research; unresolved critical Claims, material Pivots, unresolved Peers and high-EIV objectives block saturation.

### PASS — Peer staged promotion

Peer state is monotonic and evidence-bound. Contact coverage is not required for Anchor eligibility. Promoted Anchors require six-branch post-promotion evidence before `FULLY_AUDITED`.

### PASS — Commercial / research / outreach separation

The v6 commercial-value evaluator is independent from CRM/contact caps. Outreach has separate account-owned/current/verified Route gates.

### PASS — CRM and outreach safety foundations

Research does not itself authorize CRM commit or message sending. CRM writeback is receipt-bound and outreach remains guarded/draft-oriented.

## Open Production blockers

### P0-01 — Public start contract still exposes legacy Queue/Pivot closure

The v6 runtime extension uses `DECISION_SATURATION`, but the public MCP `start_investigation.network_policy.closure_strategy` schema still fixes the value to `QUEUE_PIVOT_SATURATION` through the v5 compatibility surface.

Required outcome:

- `DECISION_SATURATION` is the production/default contract.
- any legacy queue-saturation field is explicitly compatibility-only and cannot become v6 completion authority.

### P0-02 — Mutation idempotency is not a uniform public contract

The specification requires every mutation API to require an `idempotency_key`. Current implementation has strong deterministic IDs, request hashes, locks and exactly-once behavior in several critical paths, but the MCP schemas do not expose one mandatory mutation envelope across every mutation tool.

Required outcome:

- one canonical mutation envelope;
- required `idempotency_key`;
- persisted request/result hash and mutation receipt;
- deterministic replay of the original result.

### P0-03 — Explicit optimistic-concurrency / state-version contract is absent

The runtime serializes per-investigation mutations with file locks and has strong concurrent regression coverage. That is useful protection, but the public mutation contract does not expose `expected_state_version` / event-version conflict semantics required by the v6 design.

Required outcome:

- derived `state_version` increments are explicit;
- mutation can provide expected/base version;
- stale writers receive a typed version-conflict result and must reload/rebase.

### P0-04 — Pivot state model remains split between v5 and v6 semantics

The public compatibility `PIVOT_SCHEMA` still exposes only `OPEN | CONSUMED`, while v6 materiality/closure logic uses richer semantics such as material/not-material/blocked behavior.

Required canonical states:

- `OPEN_MATERIAL`
- `OPEN_OPTIONAL`
- `CONSUMED`
- `DUPLICATE`
- `LOW_VALUE`
- `BLOCKED`
- `EXHAUSTED`

Only `OPEN_MATERIAL` may block Decision Saturation.

### P0-05 — Customs Party Role schema is incomplete

The compatibility role set currently includes Buyer, Importer of Record, Exporter, Trading Intermediary, Declared Manufacturer, Probable Actual Manufacturer and Supplier Group, but does not expose the complete v6 shipment-role vocabulary.

Still required:

- `CONSIGNEE`
- `SHIPPER`
- `CUSTOMS_BROKER`
- `NOTIFY_PARTY`
- `FORWARDER`

The long-term model should avoid overloading one enum: shipment role, business role and relationship-to-buyer should remain distinguishable.

### P0-06 — Route readiness still reads only v6 compiled route observations

`evaluate_outreach_readiness` derives valid Routes from positive compiled `contact.company_route` / `contact.named_route` observations. It does not currently fold append-only legacy/current Information Records into one Canonical Route View.

This can reproduce the previously observed class of inconsistency where Information History contains a current verified Buyer-owned route but Outreach Readiness does not see it.

Required outcome:

- one Canonical Route View over compiled Evidence + append-only Information/legacy lineage;
- owner, currentness, verification, mask/guess, opt-out and channel proof remain mandatory.

### P1-01 — `resume_investigation` is durable but not yet a complete `LAST_SAFE_STATE`

Current resume returns durability, last safe seq/hash, counts and open material-pivot count. The target contract also requires current objectives, pending host bundles, critical conflicts, material open Pivot detail and portfolio priority so the Host can continue without reconstruction.

### P1-02 — `get_account_state` is still a summary, not the complete account state

Current response contains account plus Commercial Value, Research Confidence, Outreach Readiness, Decision Saturation and a minimal CRM state. The target v6 account state also requires structured brands, products, trade, suppliers, buying group, contacts, routes, Claims, conflicts, network, material Pivots and next objectives.

### P1-03 — CRM state enum is not aligned with v6 operational states

Current account state emits `SYNCED` / `NOT_SYNCED`. Target states are:

- `NOT_REQUESTED`
- `PENDING`
- `NO_CHANGE_REQUIRED`
- `COMMITTED`
- `FAILED`
- `CONFLICT`

### P1-04 — Freshness semantics remain too coarse for Current Authority

The current models use `CURRENT` / `RECENT` variants. The v6 target distinguishes `CURRENT_CONFIRMED` from `CURRENT_LIKELY`, which is important for current decision authority, account-owned Routes and supplier status.

### P1-05 — Commercial Opportunity model is under-featured

The current Commercial Value evaluator is Claim-weight based and correctly removes CRM/contact caps, but it does not yet expose the complete opportunity-factor model expected by v6:

- volume;
- frequency;
- supplier diversity/concentration;
- recency;
- growth;
- supplier change/replacement window;
- shipment size / annualized visible volume.

Do not fix this by merely lowering grade thresholds. Add evidence-bound opportunity dimensions first, then rerun golden regression.

## Acceptance interpretation

The clean Windows/Linux CI result establishes that the current implementation is reproducible across two operating systems and that the existing 133 + 58 + 30 regression/protocol gates are green.

It **does not** close the blockers above because several are missing public-contract/data-model requirements rather than regressions in already implemented behavior.

## Merge gate

PR #1 must remain draft until, at minimum:

1. public closure contract is Decision-Saturation-first;
2. mutation idempotency/version semantics are explicit and tested;
3. Pivot and Customs Party schemas are unified;
4. Canonical Route View removes Information-vs-Outreach drift;
5. LAST_SAFE_STATE and full Account State contracts are implemented;
6. commercial opportunity factors are evidence-bound;
7. golden cases and crash/offline/load acceptance are rerun;
8. Windows + Linux cold CI remains green after the changes.

Only after those gates should the branch be considered for merge into `main`.
