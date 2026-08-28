# Customs Buyer Intelligence v6.1 — Production Acceptance Status

Original acceptance date: 2026-08-28  
Last updated: 2026-08-29  
Branch: `cbi-v6-20260828`  
Draft PR: `#1` — **do not merge yet**

## Current status

**V6.1 ARCHITECTURE / CRASH RECOVERY / BACKUP / SCALE GATES ARE STRUCTURALLY VALIDATED — PRODUCTION ACCEPTANCE REMAINS OPEN FOR PRIVATE GOLDEN AND LOCAL PACKAGING VALIDATION.**

The runtime and production MCP adapter now satisfy the implemented architecture, durability, idempotency, Decision Saturation, commercial-opportunity, portfolio, backup/recovery and load regressions in independent GitHub CI. This document deliberately does **not** declare Production Ready because the specification requires real Golden-case regression, including the named Arecibo case, and those private production records are not stored in GitHub.

`main` remains unchanged. PR #1 remains Draft.

## Current production head and MCP entry

Runtime/acceptance head validated before this documentation-only refresh:

```text
08e5f079c741d1aefc4f67735c465a4d2760acfe
```

`.mcp.json` launches:

```text
mcp/server_v61_backup_recovery.py
```

This entry layers validated backup/recovery guards over the existing v6.1 production mutation/WAL/reconciliation stack.

## Independent production-branch CI

Standard workflow run:

```text
GitHub Actions run 33220250679
```

| Environment | Result | unittest | MCP compatibility | MCP v6 protocol | MCP v6.1 adapter | Privacy |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Ubuntu 24.04 / Python 3.11 | PASS | 241 tests, 3 Windows-only skips | 58/58 | 30/30 | 16/16 | PASS |
| Windows Server 2025 / Python 3.11 | PASS | 241/241 | 58/58 | 30/30 | 16/16 | PASS |

Both jobs also validate JSON manifests, agent YAML, compatibility parser, intelligence, outreach, strategic and v3 self-tests.

The intelligence self-test intentionally contains an internal negative scenario named `empty_input_deep_dive_never_blank` whose case status is `failed`; the self-test's top-level status is `passed`. That negative fixture is not a CI failure.

## Normal 100-Evidence performance gate

Specification targets:

```text
100-Evidence Bundle < 5 s
simple state query < 0.5 s
Resume < 3 s
```

Production-head measurements from run `33220250679`:

| Environment | 100-Evidence Bundle | State query | Resume | Result |
| --- | ---: | ---: | ---: | --- |
| Ubuntu | 0.023923 s | 0.065816 s | 0.186384 s | PASS |
| Windows | 0.340653 s | 0.168886 s | 0.437428 s | PASS |

Daily-backup first-mutation latency was observed separately and is **not** defined as a production SLO. On this small CI fixture it measured 0.014678 s on Ubuntu and 0.178598 s on Windows; the second same-day mutation reused the daily snapshot rather than creating another copy.

## Exact scalability acceptance

Dedicated exact-scale workflow run `33191266068` completed successfully on scale-validation commit `9657dbede12b69c2838a5a282912d01644b303ea`.

Validated counts:

| Dimension | Required | Observed |
| --- | ---: | ---: |
| Canonical Accounts | 5,000 | 5,000 |
| simultaneous Investigations | 1,000 | 1,000 |
| Evidence | 100,000 | 100,000 |
| Source Attempts | 100,000 | 100,000 |
| Peers | 20,000 | 20,000 |
| active portfolio investigations | 1,000 | 1,000 |
| superseded in acceptance portfolio | 0 expected | 0 |
| quarantined in acceptance portfolio | 0 expected | 0 |

Additional provenance:

```text
Evidence Compiler investigation samples : 1,000
SourceAttempt API samples                : 1,000
Peer discovery API samples               : 1,000
cold hash-chain aggregate                : 6.818774 s
canonical registry query                 : 0.122093 s
portfolio query                          : 119.102838 s
sample state reconstruction              : 0.046186 s
```

This run proves the required durable-state scale envelope. It does not claim a single-record mutation-throughput SLO that the specification does not define.

## Backup and recovery — PASS on production branch

The production entry now automatically creates validated logical snapshots:

```text
daily before the first production mutation
before migration
before CRM commit preparation
before schema upgrade
```

Recovery supports:

```text
latest valid snapshot
+ proven append-only live tail replay
```

Safety properties covered by regression include:

- snapshot file inventory and SHA-256 validation;
- valid-prefix capture when a live append-only chain has a corrupt tail;
- corrupt or divergent live tails do not overwrite the snapshot state;
- restore is staged into a separate target and never overwrites the live root;
- canonical, pending-journal and host-queue target roots are explicitly isolated from live environment aliases;
- invalid pending/host sidecars prevent activation instead of being trusted;
- Windows 8.3 short-path aliases cannot bypass protected-root overlap checks;
- append-only replay occurs only when ancestry is mechanically provable;
- the adapter WAL is not represented as a fake globally atomic snapshot; adapter reconciliation remains based on durable domain state.

The snapshot contract is intentionally described as **per-component serialized logical state**, not as one globally transactional nanosecond snapshot. Recovery authority comes from validated hash-chain ancestry.

## Mutation, crash and offline durability — PASS structurally

Production mutation APIs require idempotency on the hardened public adapter and persist request/result lineage. The WAL/reconciliation inventory has explicit regression for every guarded production mutation family. Where exact recovery is mechanically provable, the original result is reconstructed without duplicate mutation; where proof is absent, recovery remains fail-closed rather than guessing.

Covered families include account/start/objective/information/bundle/provider planning/receipts/peer lifecycle/pivot/closure/outreach/migration/batch sync/host queue and pending journal paths.

Additional verified behavior:

- MCP process/session kill does not make the durable Investigation unrecoverable;
- legacy Resume is byte-for-byte read-only;
- host research bundle persistence survives MCP process death and replays exactly once after restart;
- concurrent identical mutations cannot steal another idempotency correlation;
- stale writer/version conflicts remain rejected;
- unknown/unproven PREPARED mutations remain fail-closed.

## v6 semantic gates — PASS structurally

The prior architecture blockers in this document are no longer open code gaps:

- canonical seven-state Pivot view is exposed and only `OPEN_MATERIAL` blocks Decision Saturation;
- `BLOCKED` Pivot is terminal and does not masquerade as an open material research path;
- current Decision Chain support requires evidence-bound current association/role/procurement relevance rather than a bare company association;
- Commercial Value is independent of CRM/contact readiness;
- ten Commercial Opportunity factors are exposed with Evidence lineage; unknown factors remain unknown rather than fabricated negatives;
- one active Investigation per canonical account + scope is enforced in the production portfolio view;
- synthetic/placeholder sessions are excluded from the production portfolio;
- Canonical Route View binds safe append-only Information Records and compiled route Evidence without promoting masked/guessed/cross-owner routes;
- Peer promotion remains staged; contact coverage is not a prerequisite for Anchor Eligibility;
- Research Objective Planner is Claim/EIV-driven rather than a fixed website checklist;
- Evidence Compiler supports bundle processing and source-type normalization;
- batch ingestion supports partial success and idempotent replay;
- Claim Closure + Decision Saturation terminates when material unresolved work is actually exhausted.

## P0 acceptance matrix

The specification states that all P0 criteria must be satisfied before Production Ready. The current distinction is between **structurally/chaos verified** and **private real-case verified**.

| Criterion | Current status | Evidence boundary |
| --- | --- | --- |
| AC-P0-01 — session kill then `resume_investigation` succeeds | PASS | process-kill/resume and read-only Resume regressions |
| AC-P0-02 — Runtime offline, Host can durable-queue Research Bundle | PASS | MCP-death host persistence + restart exactly-once replay regression |
| AC-P0-03 — Arecibo can become Anchor Eligible from trade/entity/product Evidence without Zalo/Instagram completion | **PENDING PRIVATE GOLDEN** | generic semantic regression passes, but the specification explicitly names the real Arecibo case |
| AC-P0-04 — Commercial Grade unaffected by CRM Sync | PASS | commercial-dimension and A+/CRM-independent regressions |
| AC-P0-05 — Notify Party does not enter Buyer Decision Chain | PASS structurally | party-role/current-authority boundaries; Edwin Seda remains a private Golden assertion |
| AC-P0-06 — Brand transition does not auto-merge canonical entities | PASS structurally | canonical/non-merge regressions; Arecibo Home Center vs Home Design remains a private Golden assertion |
| AC-P0-07 — Planner returns Objectives, not checklist calls | PASS | Claim/EIV objective planner regressions |
| AC-P0-08 — Evidence Compiler handles `source_type` | PASS | compiler/protocol/bundle regressions |
| AC-P0-09 — Batch ingestion supports partial success | PASS | partial-success/idempotent bundle regressions |
| AC-P0-10 — Claim Closure + Decision Saturation can terminate | PASS | saturation/closure regressions, including race/freshness invalidation |

Because AC-P0-03 is an explicitly named real-case criterion, **Production Ready remains blocked until the private Golden run passes.**

## Remaining production acceptance blockers

### BLOCKER 1 — Real private Golden suite on the current hardened runtime

The repository intentionally contains only synthetic Golden metadata. The required private read-only regression must cover at least:

```text
Western Woods
Arecibo Home Center
Arecibo Home Design
Chimelis Home Center
Tesoro en Maderas II
Forza Distribution
Edwin Seda
Hangzhou Promise
```

The local runner is:

```text
scripts/run_private_golden_acceptance.py
```

It accepts only an allow-list of read-only runtime calls and rejects mutation, Resume/initialization, CRM writeback, outreach preparation, migration and account creation. Private manifests/results are protected by `.gitignore` patterns:

```text
.cbi-private-golden*.json
private-golden/
private-acceptance/
```

No private Golden manifest or result may be committed to GitHub.

Minimum semantic assertions include:

- Western Woods Commercial Value >= A;
- Arecibo Home Center and Arecibo Home Design remain distinct canonical entities;
- Arecibo Anchor Eligibility is not blocked merely by incomplete Zalo/Instagram/contact coverage when trade/entity/product Evidence is sufficient;
- Tesoro en Maderas II reaches the expected A+ / Anchor-Eligible semantics before Full Audit when the durable Evidence supports them;
- Edwin Seda is not promoted into buyer Decision Chain without current decision-authority Evidence and remains appropriately classified as intermediary/broker where that is what the Evidence supports;
- the remaining named Golden cases preserve identity/product/trade/network boundaries without fabricated certainty.

### BLOCKER 2 — Local plugin/skill packaging validation evidence

GitHub CI validates repository JSON/YAML, runtime protocols, privacy and self-tests. The final locally installed plugin/skill package still needs the official local product validator/installation validation to be executed against the exact checked-out head and its result recorded. This is intentionally separate from GitHub runtime tests because it depends on the local product installation environment.

Do not invent a validator command in this document; use the currently installed product's documented validator interface when executing this gate.

## Private Golden command contract

From the repository root, after syncing the exact production branch, the read-only runner contract is:

```text
python scripts/run_private_golden_acceptance.py \
  --session-root "<REAL_SESSION_ROOT>" \
  --manifest ".cbi-private-golden.json" \
  --output "private-acceptance/private-golden-result.json"
```

On PowerShell the same arguments can be supplied on one line. The manifest root is `{"cases": [...]}`. Each case requires a unique `case_id`, a read-only `tool`, an `arguments` object and one or more assertions. Supported assertion operators are `eq`, `ne`, `truthy`, `falsy`, `contains`, `not_contains`, `in`, `not_in`, `grade_at_least`, `number_at_least`, and `length_at_least`.

The runner exits `0` only when every private case passes.

## Merge gate

PR #1 must remain Draft and **must not be merged into `main`** until both remaining blockers are closed:

1. the real private Golden suite passes against the user's durable production state on the current hardened runtime;
2. the exact locally installed plugin/skill package passes the official local product validator/installation validation.

After those two local gates, rerun the standard Windows + Linux CI on the final documentation/acceptance head, record the local Golden/validator evidence without committing private customer data, and only then consider changing the PR out of Draft or declaring Production Ready.
