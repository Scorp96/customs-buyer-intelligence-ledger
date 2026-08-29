# Customs Buyer Intelligence v6 Target Architecture

## Production topology

```text
Host Research Agent
  executes visible public search/browser/provider work
                 │ research objectives + raw observations
                 ▼
Evidence Compiler
  normalize → validate → hash → bind Owner/Claim/Source → detect conflict → emit Pivot
                 │ append-only compiled bundle (partial success)
                 ▼
Governance Runtime
  Canonical + Claims + EIV + Peer lifecycle + Decision Saturation + safety policy
                 │ deterministic writeback plan / immutable receipt
                 ▼
Artifact Tool Transaction
  dynamic headers + sparse patch + history guard + semantic diff + post-import verification

Portfolio Scheduler + Budget Controller
  ranks accounts/objectives; budget exhaustion pauses and never closes research

Independent Host Queue
  persists bundles while MCP/tunnel is unavailable and replays idempotently
```

## Ownership boundaries

| Layer | Owns | Must not claim |
|---|---|---|
| Host Research Agent | Real search/navigation/provider execution | Runtime closure or Evidence acceptance |
| Evidence Compiler | Structural normalization, IDs, hashes, Claim/Evidence/Pivot mapping | That a source is true beyond its captured boundary |
| Governance Runtime | Durable state, policy, conflicts, scores, saturation and tokens | That it executed web search or wrote Excel |
| Artifact Tool | Atomic workbook transaction | Research truth beyond supplied, verified records |
| Portfolio Scheduler | Priority and resource allocation | Completion from budget exhaustion |

## State model

Claim states are `UNSEEN`, `SEARCHING`, `SUPPORTED`, `STRONGLY_SUPPORTED`, `CONFLICTED`, `REFUTED`, `NEGATIVE_EXHAUSTED`, `BLOCKED`, `NOT_APPLICABLE`, and `STALE`.

Completion is Decision Saturation. It requires:

- every critical Claim in a decision-capable terminal state;
- no material unresolved conflict;
- no open material Pivot;
- no promoted Anchor awaiting full six-branch audit;
- no remaining research objective above the configured EIV threshold;
- `EXHAUSTIVE` mode.

Fixed time, page count, query count, first positive, target grade and resource budget are never completion conditions.

## Independent business dimensions

- Commercial Value: `A+`, `A`, `A-`, `B+`, `B`, `B-`, `C`, `D`, `NQ`.
- Research Confidence: `R0` through `R5`.
- Outreach Readiness: `BLOCKED`, `IDENTITY_ONLY`, `COMPANY_ROUTE_READY`, `NAMED_ROUTE_READY`, `FOLLOW_UP_READY`, `SEND_READY`.
- CRM State: `NOT_SYNCED` or verified synchronized state.

Commercial Value uses company, product, trade, procurement and competitive facts. Contact and CRM gaps do not cap it. Outreach continues to require current Account-owned proof and human-controlled draft rendering.

## Peer model

Peer stages are `DISCOVERED → QUALIFIED → ANCHOR_ELIGIBLE → PROMOTED_ANCHOR → FULLY_AUDITED`.

Entity, product/business fit, relationship Evidence, canonical-new status and commercial novelty control eligibility. Contact coverage is retained as useful information but is not required for Anchor promotion. Promoted Anchors must address all six network branches by Claim/EIV saturation or an explicit not-material decision.

## Durability and recovery

- Session events use an append-only SHA-256 chain, serialized writer lock, flush and filesystem synchronization.
- API calls are stateless; `resume_investigation` reconstructs state from the log.
- Each compiled observation has a stable content hash. Bundle replay is idempotent.
- The host pending queue is stored outside plugin source and does not require a running MCP server.
- Integrity failure returns `QUARANTINED_READ_ONLY`; the system does not silently repair or rewrite evidence.

## Compatibility

Existing v5.4.1 APIs remain available. Their old source-family and commercial-cap outputs are legacy adapter behavior only. v6 callers use the Claim, EIV and independent-dimension APIs. `ANSWER_FIRST` remains the default for ordinary lookups and performs no Runtime writes.

