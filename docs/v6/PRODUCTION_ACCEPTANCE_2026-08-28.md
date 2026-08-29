# Customs Buyer Intelligence v6.1 — Production Acceptance Status

Original acceptance date: 2026-08-28  
Last updated: 2026-08-29  
Production-acceptance branch: `cbi-v6-20260828`  
Exact-head full-load pointer: `cbi-v6-full-acceptance`  
Draft PR: `#1` — **do not merge yet**

## Current status

**V6.1 ARCHITECTURE, CRASH RECOVERY, BACKUP/RESTORE, NORMAL PERFORMANCE, CANONICAL-IDENTITY HARDENING, BRAND/LEGAL-ENTITY SEPARATION, PORTFOLIO HARDENING AND STRICT LARGE-STATE ACCEPTANCE PATHS ARE STRUCTURALLY VALIDATED. PRODUCTION READY IS NOT DECLARED UNTIL THE EXACT FINAL HEAD AND THE TWO PRIVATE/LOCAL GATES ARE CLOSED.**

This document defines the acceptance contract and evidence boundaries. It deliberately does not claim that the commit containing this document has already passed its own final CI. The authoritative exact final PR head, standard CI run, exact-head full-load run, Private Golden status and installed-package validation status are recorded in PR #1 after those checks execute.

`main` remains unchanged by this acceptance work. PR #1 remains Draft until all mandatory gates close.

## Exact-final-head rule

A production-acceptance result is authoritative only when its recorded `head_sha` equals the final PR #1 head exactly.

The final sequence is:

1. finish all code, workflow, package-metadata and acceptance-document changes on `cbi-v6-20260828`;
2. run the standard CI matrix on that exact head;
3. fast-forward `cbi-v6-full-acceptance` to the same exact SHA, without force;
4. require the strict full-load workflow on that pointer to pass on the same `GITHUB_SHA`;
5. run the real read-only Private Golden suite against the user's durable production state on that exact checkout;
6. run the official local installed plugin/skill validation against that exact checkout;
7. record all run IDs/results in PR #1 without committing private customer data;
8. only then consider taking PR #1 out of Draft.

Any later commit to the PR head invalidates prior exact-head standard CI and exact-head full-load authority for release promotion, even when the changed file is documentation only.

## Latest semantic hardening before this provenance refresh

The most recent production semantic hardening immediately before this documentation/package refresh is:

```text
d898dfa909b4247c6d78911789765ee0ff201398
Fail closed on cross-country strong identity conflicts
```

That change extends the v6.1 Evidence-Bound Canonical Registry so an explicit country contradiction vetoes automatic identity binding when the candidate relationship is formed by:

```text
EXACT_ACCOUNT_ID
TAX_ID
EXTERNAL_ID
```

If both sides explicitly state countries and the countries do not overlap, the resolver returns `AMBIGUOUS_MATCH` with `STRONG_IDENTITY_CONFLICT_REQUIRES_REVIEW` / `COUNTRY_CONFLICT` instead of silently merging. This does not block two same-name companies in explicitly different countries from existing as separate legal entities when no strong identifier asserts they are the same entity.

## Canonical Account / Brand hardening

The v6.1 production Runtime uses the Evidence-Bound Canonical Registry and Brand hardening overlay. Structural regressions cover these rules:

- free-form `aliases` are preserved for history/display but have no automatic legal-entity merge authority;
- explicit `legal_aliases` are also review signals, not automatic Canonical merge keys;
- Brand relationship data remains separate from Legal Entity identity and cannot infer legal merger authority;
- address overlap is supporting evidence only and cannot independently merge Canonical Accounts;
- primary legal-name matching requires explicit country overlap;
- a same-name collision with a missing country fails closed for review rather than auto-merging or silently creating a duplicate;
- an explicit `requested_account_id` is an exact identity constraint, never a fuzzy hint;
- if a requested ID does not exist, another similarly named Account cannot be substituted for it;
- the supported low-information creation path is retained when a caller explicitly supplies a genuinely new Account ID and no competing identity signal exists;
- contradictory Tax IDs block name-, External-ID- or exact-ID-based automatic binding;
- equal Tax IDs or equal External IDs cannot override an explicit country contradiction;
- exact Account ID itself cannot override an explicit country contradiction without review;
- same legal name with explicitly different countries may remain separate when no strong identifier conflicts with that separation.

These rules are designed to prevent Brand, DBA/trade-name, affiliate, same-address and cross-country identifier collisions from becoming unsupported Legal Entity merges.

## Production MCP entry and runtime dependency boundary

`.mcp.json` launches:

```text
mcp/server_v61_backup_recovery.py
```

The Windows launcher runs with `-NoProfile` / `-NonInteractive`, dynamically selects an actual Python >= 3.10 interpreter, rejects unsupported runtimes and launches the installed production entry from the fixed user plugin root.

The current acceptance branch intentionally removes the former `requirements.txt` and `requirements-dev.txt` application dependency sets. Production Runtime acceptance therefore does not depend on FastAPI, httpx, pydantic, uvicorn, pytest or pytest-asyncio being installed. Standard CI installs pinned `PyYAML==6.0.2` only ephemerally to parse/validate the agent YAML; that CI-only package is not a hidden production Runtime dependency.

## Standard independent CI

The standard workflow validates the supported Python floor instead of testing only one interpreter:

```text
Ubuntu  × Python 3.10
Ubuntu  × Python 3.11
Windows × Python 3.10
Windows × Python 3.11
```

The pipeline includes:

- JSON manifest validation;
- agent YAML validation;
- full unittest regression suite;
- enforced 100-Evidence performance acceptance;
- MCP compatibility self-test;
- MCP v6 protocol test;
- MCP v6.1 production-adapter protocol test;
- privacy scan;
- compatibility parser self-test;
- intelligence self-test;
- outreach self-test;
- strategic self-test;
- v3 compatibility self-test.

GitHub Actions dependencies are pinned to immutable commit SHAs corresponding to `actions/checkout` v7.0.1 and `actions/setup-python` v7.0.0 rather than floating major-version tags.

## Normal performance gate

The standard CI smoke profile enforces, rather than merely reports, the specification targets:

```text
100-Evidence Bundle < 5 s
simple state query < 0.5 s
Resume < 3 s
```

The workflow uses:

```text
python scripts/run_v6_load_acceptance.py --profile smoke --enforce-targets
```

A threshold failure exits non-zero and therefore fails CI.

## Strict full-load acceptance

`scripts/run_v6_load_acceptance.py` defines the specification full targets as:

```text
Evidence            10,000
Pivots               1,000
Peers                  500
Canonical Accounts   5,000
```

The full profile passes only when all requested/observed counts are exact and all 5,000 Canonical Accounts are both reported as `CREATED` and durably persisted as 5,000 `CANONICAL_ACCOUNT_CREATED` events with 5,000 unique persisted Account IDs. It also validates public-state counts and durable Resume.

A historical strict full-load run (`33221892250`) passed these exact counts on an earlier validated head. That run remains useful regression evidence but is not sufficient release authority after later Canonical-identity changes.

### Exact-head full-load pointer

`.github/workflows/cbi-v6-load-acceptance.yml` retains manual `workflow_dispatch` for explicit smoke/full runs and additionally accepts `push` only on:

```text
cbi-v6-full-acceptance
```

Push-triggered acceptance is intentionally hard-coded to the specification full target of 5,000 Canonical Accounts. The workflow asserts:

```text
git rev-parse HEAD == GITHUB_SHA
```

before running the full profile. The pointer branch is not a development branch and is not a PR base; it exists only so the final PR commit object can be tested through GitHub Actions without creating another code/documentation commit. It must advance by ordinary fast-forward only.

## Backup / recovery and mutation durability

The production entry uses hardened logical snapshots plus mechanically proven append-only recovery.

Validated backup trigger classes include:

```text
daily before the first production mutation
before migration
before CRM commit preparation
before schema upgrade
```

Covered recovery properties include:

- snapshot inventory and SHA-256 validation;
- valid-prefix capture when a live append-only chain has a corrupt tail;
- divergent/corrupt live tails cannot overwrite snapshot authority;
- restore is staged into a separate target and never overwrites the live root;
- Canonical, pending-journal and host-queue roots remain isolated from protected live aliases;
- invalid sidecars block activation instead of being trusted;
- Windows 8.3 path aliases cannot bypass protected-root overlap checks;
- append-only tail replay requires mechanically proven ancestry;
- guarded production mutations have an explicit recovery inventory;
- exact automatic reconciliation is used only when durable proof can reconstruct the original result;
- ambiguous, no-event and legacy snapshotless cases fail closed instead of guessing or replaying a mutation.

## Other v6.1 semantic gates

Structural regressions also cover:

- only canonical `OPEN_MATERIAL` Pivots block Decision Saturation;
- terminal Pivots do not masquerade as unresolved material work;
- Decision Chain authority requires evidence-bound current association, current-enough role and role/procurement relevance rather than bare company association;
- Commercial Value is independent of CRM/contact readiness;
- Commercial Opportunity factors retain Evidence lineage and unknown factors remain unknown instead of fabricated negatives;
- production portfolio filtering enforces one active Investigation per canonical account + scope and excludes synthetic/placeholder sessions by default;
- Canonical Route View joins safe append-only Information Records and compiled route Evidence without promoting masked, guessed or cross-owner routes;
- Peer Anchor Eligibility does not require contact coverage;
- Planner output is Claim/EIV-driven instead of a fixed source checklist;
- batch ingestion supports partial success and idempotent replay;
- full account state exposes identity, brand, product, trade, supplier, buying-group, contact, route, claim, conflict, network/peer, material-pivot and next-objective views.

Synthetic/structural tests do not substitute for the named real Golden cases.

## Private Golden runner boundary

The read-only runner is:

```text
scripts/run_private_golden_acceptance.py
```

It permits only an allow-list of read-only Runtime calls. It does not permit mutation, Resume/initialization, CRM writeback, outreach preparation, migration or account creation.

When `--session-root` is omitted it constructs `UnifiedRuntime()` with the production-default/environment-driven root semantics. Selector resolution is restricted to one unique `PRODUCTION + ACTIVE` Investigation and fails closed on zero matches, multiple matches, an active portfolio larger than the 1,000-row auto-resolution boundary, or a selected non-production/non-active row.

The runner supports scalar/path assertions plus recursive semantic assertions (`subset`, `not_subset`, `list_item_subset`, `no_list_item_subset`, `peer_stage_at_least`) without mutating the underlying production session.

## P0 acceptance matrix

| Criterion | Current status | Evidence boundary |
| --- | --- | --- |
| AC-P0-01 — session kill then Resume succeeds | PASS structurally | process-kill/resume and durable last-safe-state regressions |
| AC-P0-02 — Runtime offline, Host durable-queues Research Bundle | PASS structurally | local/process-independent host queue + exactly-once restart replay; remote tunnel availability is a separate transport boundary |
| AC-P0-03 — real Arecibo can become Anchor Eligible without Zalo/Instagram completion | **PENDING PRIVATE GOLDEN** | generic semantic regression passes; specification explicitly names the real case |
| AC-P0-04 — Commercial Grade unaffected by CRM Sync | PASS | independent commercial-dimension regressions |
| AC-P0-05 — Notify Party does not become Buyer Decision Maker | PASS structurally | party-role/current-authority boundaries; Edwin Seda remains a private Golden assertion |
| AC-P0-06 — Brand relationship does not auto-merge canonical entities | PASS structurally | production Brand mixin + alias/address/country/exact-ID/strong-ID Canonical regressions; named Arecibo entities remain private Golden assertions |
| AC-P0-07 — Planner returns Objectives, not checklist calls | PASS | Claim/EIV planner regressions |
| AC-P0-08 — Evidence Compiler handles source-type normalization | PASS | compiler/protocol/bundle regressions |
| AC-P0-09 — Batch ingestion supports partial success | PASS | partial-success/idempotent bundle regressions |
| AC-P0-10 — Claim Closure + Decision Saturation can terminate | PASS | saturation/closure regressions including race/freshness invalidation |

## BLOCKER 1 — Real private Golden suite

The real read-only regression must run against the user's durable production state on the exact final PR head and cover at least:

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

Minimum acceptance expectations include:

- Western Woods Commercial Value >= A when supported by the current durable Evidence;
- Arecibo Home Center, Arecibo Home Design and Chimelis Home Center do not become an unsupported direct Legal Entity merge;
- the real Arecibo Peer can reach at least Anchor Eligible when trade/entity/product/relationship evidence is sufficient, without Zalo/Instagram/source-checklist completion being a prerequisite;
- Tesoro en Maderas II reaches A+ and at least Anchor-Eligible semantics when its current durable Evidence supports those facts, even before Full Audit;
- Edwin Seda is not promoted into Buyer Decision Chain without current decision-authority proof and remains intermediary/broker when that is what current Evidence supports;
- the remaining named cases preserve evidence-bound identity, product, trade, supplier and network semantics without fabricated certainty.

Historical live findings are regression targets, not presumed current facts.

Private manifests/results remain gitignored and must not be committed.

Production-default command:

```text
python scripts/run_private_golden_acceptance.py --manifest ".cbi-private-golden.json" --output "private-acceptance/private-golden-result.json"
```

The runner exits 0 only when every private case passes.

## BLOCKER 2 — Official local installed plugin/skill validation

Repository CI validates source/manifests/protocols/privacy and installed-layout launcher behavior. The exact locally installed plugin/skill package still requires the official local product validator / installation validation against the exact final checkout.

No validator command is invented in this repository. Use the locally installed product's documented validation interface and record the result without committing private customer data.

## Repository governance note

The production-acceptance and full-load pointer branches are currently unprotected. That does not invalidate Runtime test results, but before final promotion repository administrators should configure appropriate protection/required-check policy for the merge target so CI cannot be bypassed by an accidental direct push. This is governance hardening, not a substitute for any Runtime acceptance gate.

## Merge gate

PR #1 must remain Draft and **must not be merged into `main`** until all mandatory release evidence is recorded for the exact final head:

1. standard Ubuntu/Windows × Python 3.10/3.11 CI passes;
2. strict exact-head 10k/1k/500/5k full-load acceptance passes through the full-load pointer;
3. the real Private Golden suite passes against the durable production state;
4. the exact locally installed plugin/skill package passes the official local product validation.

After those gates close, record the evidence in PR #1 without committing private data and only then consider changing the PR out of Draft or declaring Production Ready.
