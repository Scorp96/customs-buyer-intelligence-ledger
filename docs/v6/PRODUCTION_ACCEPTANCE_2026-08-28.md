# Customs Buyer Intelligence v6.1 — Production Acceptance Status

Original acceptance date: 2026-08-28  
Last updated: 2026-08-29  
Branch: `cbi-v6-20260828`  
Draft PR: `#1` — **do not merge yet**

## Current status

**V6.1 ARCHITECTURE / CRASH RECOVERY / BACKUP / NORMAL PERFORMANCE / EXACT LARGE-STATE GATES ARE STRUCTURALLY VALIDATED — PRODUCTION ACCEPTANCE REMAINS OPEN FOR PRIVATE GOLDEN AND LOCAL PACKAGING VALIDATION.**

The runtime and production MCP adapter satisfy the implemented architecture, durability, idempotency, Decision Saturation, commercial-opportunity, portfolio, backup/recovery, Windows launcher, normal-performance and exact large-state regressions in independent GitHub CI. This document deliberately does **not** declare Production Ready because the specification requires real Golden-case regression, including the named Arecibo case, and the final installed plugin/skill package must also pass its local product validation. Those private/local artifacts are not stored in GitHub.

`main` remains unchanged. PR #1 remains Draft.

## Current validated head and MCP entry

Validated code/runner head immediately before this documentation-only refresh:

```text
203a54f61ddc1e1582ee4af98b73d675f40725e6
```

`.mcp.json` launches the hardened production entry:

```text
mcp/server_v61_backup_recovery.py
```

The Windows launcher selects a usable Python >= 3.10 runtime rather than assuming one fixed installation path, and its installed-layout cold-start behavior is covered by a real Windows regression.

The Private Golden runner now also preserves production Runtime root semantics: when `--session-root` is omitted it constructs `UnifiedRuntime()` exactly as the production MCP entry does, so default/environment-driven session, canonical and pending-root derivation is not changed merely for acceptance execution. An explicit `--session-root` remains available only for intentionally explicit/custom Runtime layouts.

## Independent production-branch CI

Standard workflow run:

```text
GitHub Actions run 33225553252
```

| Environment | Result | unittest | MCP compatibility | MCP v6 protocol | MCP v6.1 adapter | Privacy |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Ubuntu 24.04 / Python 3.11 | PASS | 251 tests, 4 Windows-only skips | 58/58 | 30/30 | 16/16 | PASS |
| Windows Server 2025 / Python 3.11 | PASS | 251/251 | 58/58 | 30/30 | 16/16 | PASS |

The new Private Golden production-root regressions execute successfully on both platforms:

- `test_cli_session_root_is_optional_for_production_default`;
- `test_default_runtime_builder_matches_production_root_semantics`.

The Windows job also actually executes and passes the platform-specific regressions for:

- Windows 8.3 short-path alias protection in backup/recovery roots;
- live/dead process liveness probing;
- MCP launcher cold-start from an installed `%USERPROFILE%\plugins\customs-buyer-intelligence` layout;
- dynamic selection of a Python >= 3.10 runtime.

Both jobs also validate JSON manifests, agent YAML, compatibility parser, intelligence, outreach, strategic and v3 self-tests. The intelligence self-test intentionally contains an internal negative scenario named `empty_input_deep_dive_never_blank` whose case status is `failed`; the self-test's top-level status is `passed`. That negative fixture is not a CI failure.

## Normal 100-Evidence performance gate

Specification targets:

```text
100-Evidence Bundle < 5 s
simple state query < 0.5 s
Resume < 3 s
```

Measurements from run `33225553252`:

| Environment | 100-Evidence Bundle | State query | Resume | Result |
| --- | ---: | ---: | ---: | --- |
| Ubuntu | 0.023413 s | 0.062406 s | 0.192737 s | PASS |
| Windows | 0.139005 s | 0.207893 s | 0.510455 s | PASS |

Daily-backup mutation latency is recorded as a diagnostic only; it is **not** defined as a production SLO and is not substituted for the normal performance gates above.

## Exact v6.1 large-state acceptance — PASS with durable Canonical Account proof

The full-load acceptance was independently audited and hardened. Merely requesting 5,000 Canonical Accounts is not sufficient for a pass. The acceptance runner requires all three of the following to equal the requested count:

1. resolver results whose status is `CREATED`;
2. durable `CANONICAL_ACCOUNT_CREATED` events persisted in the canonical registry;
3. unique persisted Canonical Account IDs.

A negative regression deliberately patches the resolver to claim `CREATED` without persistence and verifies that the full profile fails closed.

Strict-count implementation commit:

```text
0e3836fd68ffd181c0bc469bb70eba64becd9baa
```

Exact full-load workflow:

```text
GitHub Actions run 33221892250
```

Observed counts:

| Dimension | Required | Observed |
| --- | ---: | ---: |
| Evidence | 10,000 | 10,000 |
| Pivots | 1,000 | 1,000 |
| Peers | 500 | 500 |
| Canonical Accounts requested | 5,000 | 5,000 |
| resolver `CREATED` results | 5,000 | 5,000 |
| persisted `CANONICAL_ACCOUNT_CREATED` events | 5,000 | 5,000 |
| unique persisted Canonical Account IDs | 5,000 | 5,000 |

Measured large-state timings:

```text
append 9,500 non-peer Evidence     10.854092 s
create/persist 5,000 accounts     655.014034 s
large-state load                    0.425034 s
large public-state query            1.291995 s
large Resume                       21.345263 s
```

The specification treats the large envelope as a loadability/scalability target and does not apply the normal 100-Evidence timing thresholds to these full-load measurements. The current branch retains the strict persisted-count runner and its fail-closed regressions. Commits after `0e3836fd...` changed launcher configuration/tests, removed the temporary full-load workflow, hardened the Private Golden acceptance runner's production-root fidelity, and refreshed acceptance documentation; they did not weaken the full-load runner or Runtime large-state semantics.

### Supplemental broader stress evidence

Dedicated stress run `33191266068` previously passed a larger synthetic envelope on scale-validation commit `9657dbede12b69c2838a5a282912d01644b303ea`:

| Dimension | Observed |
| --- | ---: |
| Canonical Accounts | 5,000 |
| simultaneous Investigations | 1,000 |
| Evidence | 100,000 |
| Source Attempts | 100,000 |
| Peers | 20,000 |
| active portfolio investigations | 1,000 |
| superseded in acceptance portfolio | 0 |
| quarantined in acceptance portfolio | 0 |

This broader stress run is supplemental evidence only; it is **not** used as a substitute for the strict 10k Evidence / 1k Pivot / 500 Peer / 5k durably persisted Canonical Account acceptance above.

## Backup and recovery — PASS on production branch

The production entry automatically creates validated logical snapshots:

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

The prior architecture blockers are no longer open code gaps:

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

It accepts only an allow-list of read-only Runtime calls and rejects mutation, Resume/initialization, CRM writeback, outreach preparation, migration and account creation. Selector resolution is limited to a unique `PRODUCTION + ACTIVE` Investigation. Zero matches, multiple matches, or a truncated active portfolio fail closed rather than guessing. The runner's real-runtime regression verifies byte-for-byte read-only behavior.

By default the runner must be executed **without** `--session-root`. That makes it instantiate `UnifiedRuntime()` exactly like the production MCP entry and therefore preserves any production `CBI_SESSION_ROOT`, `CBI_CANONICAL_ROOT`, `CBI_PENDING_ROOT`, or platform-default root semantics. Supply `--session-root` only when intentionally validating an explicitly custom Runtime layout rather than the production-default process environment.

Private manifests/results are protected by `.gitignore` patterns:

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

GitHub CI validates repository JSON/YAML, runtime protocols, privacy, Windows installed-layout cold-start, and self-tests. The final locally installed plugin/skill package still needs the official local product validator/installation validation to be executed against the exact checked-out head and its result recorded. This is intentionally separate from GitHub runtime tests because it depends on the local product installation environment.

Do not invent a validator command in this document; use the currently installed product's documented validator interface when executing this gate.

## Private Golden command contract

From the repository root, after syncing the exact production branch, the production-default read-only runner contract is:

```text
python scripts/run_private_golden_acceptance.py \
  --manifest ".cbi-private-golden.json" \
  --output "private-acceptance/private-golden-result.json"
```

On PowerShell the same arguments can be supplied on one line. If the production process intentionally uses `CBI_SESSION_ROOT` or related root environment variables, run the command from the same environment and still omit `--session-root`; `UnifiedRuntime()` will honor those production environment variables. Use the explicit `--session-root "<EXPLICIT_SESSION_ROOT>"` override only for an intentionally explicit/custom acceptance layout.

The manifest root is `{"cases": [...]}`. Each case requires a unique `case_id`, a read-only `tool`, an `arguments` object and one or more assertions. Supported assertion operators are `eq`, `ne`, `truthy`, `falsy`, `contains`, `not_contains`, `in`, `not_in`, `grade_at_least`, `number_at_least`, and `length_at_least`.

The runner exits `0` only when every private case passes.

## Merge gate

PR #1 must remain Draft and **must not be merged into `main`** until both remaining blockers are closed:

1. the real private Golden suite passes against the user's durable production state on the current hardened runtime;
2. the exact locally installed plugin/skill package passes the official local product validator/installation validation.

After those two local gates, if acceptance evidence/documentation changes the branch head, rerun the standard Windows + Linux CI on that final acceptance head, record the local Golden/validator evidence without committing private customer data, and only then consider changing the PR out of Draft or declaring Production Ready.
