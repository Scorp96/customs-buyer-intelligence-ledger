# Customs Buyer Intelligence v6.1 — Production Acceptance Status

Original acceptance date: 2026-08-28  
Last updated: 2026-08-29  
Branch: `cbi-v6-20260828`  
Draft PR: `#1` — **do not merge yet**

## Current status

**V6.1 ARCHITECTURE / CRASH RECOVERY / BACKUP / NORMAL PERFORMANCE / EXACT LARGE-STATE GATES ARE STRUCTURALLY VALIDATED — PRODUCTION ACCEPTANCE REMAINS OPEN FOR PRIVATE GOLDEN AND LOCAL PACKAGING VALIDATION.**

The production branch has independently passing Ubuntu and Windows CI for the implemented architecture, mutation/WAL recovery, host-offline durability, Decision Saturation, commercial-opportunity factors, portfolio hardening, backup/recovery, Windows installed-layout launcher behavior, normal performance, strict large-state acceptance, and the read-only Private Golden runner boundary.

This document deliberately does **not** declare Production Ready. The specification requires real regression against the user's durable production Golden cases, including the named Arecibo case, and the final locally installed plugin/skill package must also pass the official local product validation. Those private/local artifacts are not stored in GitHub.

`main` remains unchanged. PR #1 remains Draft.

## Current validated code head before this documentation refresh

The latest code/test head immediately before this documentation-only refresh is:

```text
b9de780608d1d9f4f716dd291c75fcce825dd145
```

Standard GitHub Actions run:

```text
33226557138
```

Result:

```text
Ubuntu 24.04 / Python 3.11   PASS
Windows Server 2025 / Python 3.11   PASS
```

Both jobs passed the unittest regression suite, 100-Evidence structural smoke acceptance, MCP compatibility self-test, MCP v6 protocol test, MCP v6.1 production-adapter protocol test, privacy scan, compatibility parser self-test, intelligence self-test, outreach self-test, strategic self-test and v3 compatibility self-test.

The code changes immediately preceding that run are limited to the read-only Private Golden assertion surface and its tests:

```text
556591a5acd3118202efa768e5b814108c2b7b5c
  Add semantic list assertions to Private Golden runner

b9de780608d1d9f4f716dd291c75fcce825dd145
  Test semantic Private Golden list assertions
```

No Runtime mutation semantics, production durable state, CRM data or `main` branch were changed by those commits.

Because this file update is itself a new documentation-only commit, the exact final branch head must receive standard Windows + Linux CI before it is treated as the final acceptance head.

## Production MCP entry

`.mcp.json` launches:

```text
mcp/server_v61_backup_recovery.py
```

The Windows launcher dynamically selects a usable Python >= 3.10 runtime instead of assuming one fixed installation path. Installed-layout cold-start and Windows-specific path/liveness behavior are covered by regression.

## Private Golden runner boundary

The Private Golden runner is:

```text
scripts/run_private_golden_acceptance.py
```

It is restricted to an allow-list of read-only Runtime calls. It does not permit mutation, Resume/initialization, CRM writeback, outreach preparation, migration or account creation.

When `--session-root` is omitted, it constructs `UnifiedRuntime()` with the same production-default/environment-driven root semantics as the production MCP process. An explicit `--session-root` remains available only for intentionally explicit/custom acceptance layouts.

Selector resolution may identify an Investigation by account name, account ID and/or investigation scope, but only through the public `PRODUCTION + ACTIVE` portfolio view. It fails closed when:

- zero Investigations match;
- more than one Investigation matches;
- the active portfolio exceeds the 1,000-row public auto-resolution limit;
- a selected row is not a production/active row.

The runner's real-Runtime regression verifies that selector-based read-only execution does not mutate the Investigation session bytes.

### Semantic assertion support

The runner supports scalar/path assertions:

```text
eq
ne
truthy
falsy
contains
not_contains
in
not_in
grade_at_least
number_at_least
length_at_least
```

It also supports unordered semantic list assertions:

```text
list_item_subset
no_list_item_subset
```

These recursively compare value-only subsets and allow private Golden manifests to express facts such as:

- an unordered public `network.peers` list contains a named Peer with required semantic fields;
- a forbidden role/fact is absent for a named party;
- nested public Runtime objects contain the expected durable semantics without hard-coding list indexes or private Investigation IDs.

The semantic assertion implementation is read-only and does not inspect repository-private customer files or bypass the Runtime public state boundary.

## Normal 100-Evidence performance gate

Specification targets:

```text
100-Evidence Bundle < 5 s
simple state query < 0.5 s
Resume < 3 s
```

The previously recorded production-branch measurements remain passing on both Ubuntu and Windows. Later Private Golden assertion-only commits do not modify Runtime performance code.

Daily-backup mutation latency is diagnostic only and is not substituted for the normal performance SLO gates.

## Exact v6.1 large-state acceptance — PASS with durable Canonical Account proof

Strict-count implementation commit:

```text
0e3836fd68ffd181c0bc469bb70eba64becd9baa
```

Exact full-load workflow:

```text
33221892250
```

Required and observed counts:

| Dimension | Required | Observed |
| --- | ---: | ---: |
| Evidence | 10,000 | 10,000 |
| Pivots | 1,000 | 1,000 |
| Peers | 500 | 500 |
| Canonical Accounts requested | 5,000 | 5,000 |
| resolver `CREATED` results | 5,000 | 5,000 |
| persisted `CANONICAL_ACCOUNT_CREATED` events | 5,000 | 5,000 |
| unique persisted Canonical Account IDs | 5,000 | 5,000 |

The full-load gate requires actual durable Canonical Account persistence, not merely resolver claims. A negative regression verifies that a resolver claiming `CREATED` without durable persistence cannot pass the strict profile.

A broader supplemental stress run also passed 100,000 Evidence, 100,000 Source Attempts, 20,000 Peers, 1,000 simultaneous/active Investigations and 5,000 Canonical Accounts. It is supplemental evidence and does not replace the strict 10k/1k/500/5k acceptance above.

## Backup / recovery and mutation durability

The production entry uses hardened validated logical snapshot backup and append-only recovery.

Validated backup trigger classes include:

```text
daily before the first production mutation
before migration
before CRM commit preparation
before schema upgrade
```

Recovery properties covered by regression include:

- snapshot inventory and SHA-256 validation;
- valid-prefix capture when a live append-only chain has a corrupt tail;
- divergent/corrupt live tails do not overwrite snapshot authority;
- restore is staged into a separate target and never overwrites the live root;
- canonical, pending-journal and host-queue roots remain isolated from protected live aliases;
- invalid sidecars block activation instead of being trusted;
- Windows 8.3 path aliases cannot bypass protected-root overlap checks;
- append-only tail replay requires mechanically proven ancestry.

The production mutation adapter maintains a complete guarded mutation inventory. Exact automatic reconciliation is permitted only where durable proof can reconstruct the original result. Ambiguous/no-event/legacy-snapshotless cases fail closed instead of guessing or replaying a mutation.

The validated mutation families include account/start/objective/information/bundle/provider planning/receipts/peer lifecycle/pivot/closure/outreach/migration/batch sync/host queue and pending journal paths.

## v6.1 semantic gates — structurally validated

The source-level architecture now covers the principal historical bug classes:

- only canonical `OPEN_MATERIAL` Pivots block Decision Saturation;
- `BLOCKED` / terminal Pivots do not masquerade as open material work;
- Decision Chain authority requires evidence-bound current association, sufficiently current role and role/procurement relevance rather than bare company association;
- Commercial Value is independent of CRM/contact readiness;
- Commercial Opportunity factors retain Evidence lineage and unknown factors remain unknown instead of fabricated negatives;
- production portfolio lifecycle filtering enforces one active Investigation per canonical account + scope and excludes synthetic/placeholder sessions by default;
- Canonical Route View joins safe append-only Information Records and compiled route Evidence without promoting masked/guessed/cross-owner routes;
- Peer Anchor Eligibility does not require contact coverage;
- Planner output is Claim/EIV-driven instead of a fixed source checklist;
- batch ingestion supports partial success and idempotent replay;
- full account state exposes identity, brand, product, trade, supplier, buying-group, contact, route, claim, conflict, network/peer, material-pivot and next-objective views.

These structural regressions do **not** substitute for the named real Golden cases.

## P0 acceptance matrix

| Criterion | Current status | Evidence boundary |
| --- | --- | --- |
| AC-P0-01 — session kill then Resume succeeds | PASS | process-kill/resume and durable last-safe-state regressions |
| AC-P0-02 — Runtime offline, Host durable-queues Research Bundle | PASS structurally | local/process-independent host queue + exactly-once restart replay; remote tunnel availability is a separate transport boundary |
| AC-P0-03 — real Arecibo can become Anchor Eligible without Zalo/Instagram completion | **PENDING PRIVATE GOLDEN** | generic semantic regression passes; the specification explicitly names the real Arecibo case |
| AC-P0-04 — Commercial Grade unaffected by CRM Sync | PASS | independent commercial-dimension regressions |
| AC-P0-05 — Notify Party does not become Buyer Decision Maker | PASS structurally | party-role/current-authority boundaries; Edwin Seda remains a private Golden assertion |
| AC-P0-06 — Brand relationship does not auto-merge canonical entities | PASS structurally | canonical/non-merge regressions; Arecibo entities remain a private Golden assertion |
| AC-P0-07 — Planner returns Objectives, not checklist calls | PASS | Claim/EIV planner regressions |
| AC-P0-08 — Evidence Compiler handles source-type normalization | PASS | compiler/protocol/bundle regressions |
| AC-P0-09 — Batch ingestion supports partial success | PASS | partial-success/idempotent bundle regressions |
| AC-P0-10 — Claim Closure + Decision Saturation can terminate | PASS | saturation/closure regressions including race/freshness invalidation |

## BLOCKER 1 — Real private Golden suite

The real read-only regression must run against the user's durable production state on the exact final branch head and cover at least:

```text
Western Woods / C001
Arecibo Home Center
Arecibo Home Design
Chimelis Home Center
Tesoro en Maderas II
Forza Distribution
Edwin Seda
Hangzhou Promise
```

Minimum specification-level expectations include:

- Western Woods Commercial Value >= A;
- Arecibo Home Center, Arecibo Home Design and Chimelis Home Center do not become an unsupported direct legal merge;
- the real Arecibo Peer can reach Anchor Eligible when trade/entity/product/relationship evidence is sufficient, without Zalo/Instagram/source-checklist completion being a prerequisite;
- Tesoro en Maderas II reaches A+ and Anchor-Eligible semantics when its durable Evidence supports those facts, even before Full Audit;
- Edwin Seda is not promoted into Buyer Decision Chain without current decision-authority proof and remains classified as intermediary/broker when that is what the Evidence supports;
- the remaining named cases preserve evidence-bound identity, product, trade, supplier and network semantics without fabricated certainty.

Historical live findings are **regression targets**, not current facts. They must be re-measured on the exact final production head rather than assumed to remain broken or assumed fixed from synthetic CI.

Private manifests/results are gitignored and must not be committed.

Production-default command:

```text
python scripts/run_private_golden_acceptance.py --manifest ".cbi-private-golden.json" --output "private-acceptance/private-golden-result.json"
```

Run this from the same production environment and omit `--session-root` so the Runtime honors the production default or `CBI_SESSION_ROOT` / `CBI_CANONICAL_ROOT` / `CBI_PENDING_ROOT` environment configuration. Use an explicit `--session-root` only for an intentionally custom acceptance layout.

The runner exits `0` only when every private case passes.

## BLOCKER 2 — Official local installed plugin/skill validation

GitHub CI validates repository manifests, agent YAML, Runtime protocols, privacy, Windows installed-layout cold-start and repository self-tests. The exact locally installed plugin/skill package still requires the official local product validator / installation validation against the exact final checkout.

No official local package-validator execution interface is exposed through this repository or the current plugin-management connector. Do **not** invent a validator command; use the locally installed product's documented validation interface and record the result without committing private customer data.

## Merge gate

PR #1 must remain Draft and **must not be merged into `main`** until both local blockers are closed:

1. the real private Golden suite passes against the user's durable production state on the exact final head;
2. the exact locally installed plugin/skill package passes the official local product validation.

After those gates are closed, rerun standard Windows + Linux CI on the exact final acceptance head if any acceptance evidence/documentation changed the branch, record the local evidence without committing private customer data, and only then consider changing the PR out of Draft or declaring Production Ready.
