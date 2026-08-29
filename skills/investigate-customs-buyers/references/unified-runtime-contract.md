# v6.1 Unified Runtime Contract

The Governance Runtime is authoritative for durable Claim state, Peer stage, Decision Saturation, Closure IDs, CRM transaction receipts and executable draft cards. It does not perform web search, does not call another provider, does not write Excel and never sends a message.

## Answer-first boundary

Ordinary Buyer/company/contact/email/phone/person/route lookups stay in `ANSWER_FIRST`. Use host-visible public research, answer immediately with concrete source links and boundaries, and provide one tailored development email plus one instant-chat draft. Do not call any CBI MCP tool, create history, open CRM, issue Closure or render an executable link unless the user explicitly requests persistence, full audit, CRM or outreach preparation.

## Architecture

1. Host Research Agent executes real search/navigation/provider work.
2. Evidence Compiler accepts 1–1000 observations, validates and normalizes them, assigns IDs/hashes, binds Owner/Claim/Source, preserves conflicts and emits Pivots.
3. Governance Runtime derives Claims, EIV, Peer stages, independent business dimensions and Decision Saturation from append-only events.
4. Artifact Tool performs the external atomic workbook transaction and returns a verifiable receipt.
5. Portfolio Scheduler/Budget Controller ranks accounts and work. Budget exhaustion pauses; it never closes research.

## Claim and saturation policy

Claim states are `UNSEEN`, `SEARCHING`, `SUPPORTED`, `STRONGLY_SUPPORTED`, `CONFLICTED`, `REFUTED`, `NEGATIVE_EXHAUSTED`, `BLOCKED`, `NOT_APPLICABLE`, and `STALE`.

The Source Profile is a search playbook, not a mandatory checklist. Next work is ranked by:

`EIV = probability × decision impact × evidence-quality gain × commercial weight ÷ search cost`.

Decision Saturation requires every critical Claim to be decision-capable, no material conflict, no open material Pivot, no undispositioned discovered Peer, no Anchor-eligible Peer awaiting promotion, no promoted Anchor awaiting a full audit and no remaining above-threshold EIV objective. A first positive, fixed time/pages/queries, score or budget can never close research. `FAST_SCAN` cannot issue saturation.

`NEGATIVE` is a search observation. `NEGATIVE_EXHAUSTED` requires real raw proof from at least two independent applicable strategies. A 401/403/429, login wall, paywall, captcha, anti-bot or resource limit is blocked, not Negative or N/A.

## Independent dimensions

- Commercial Value: `A+`, `A`, `A-`, `B+`, `B`, `B-`, `C`, `D`, `NQ`.
- Research Confidence: `R0`–`R5`.
- Outreach Readiness: `BLOCKED`, `IDENTITY_ONLY`, `COMPANY_ROUTE_READY`, `NAMED_ROUTE_READY`, `FOLLOW_UP_READY`, `SEND_READY`.
- CRM state is separate.

Contact or CRM gaps do not cap Commercial Value. Outreach still requires a current verified Account-owned route and safe history/authority state.

## Evidence and information

- User/customs rows are evidence to verify, not final truth.
- Positive observations need exact Owner, Claim, Source, locator, captured content hash, authority, freshness and boundary. A supplied hash and supplied raw material must match exactly.
- Public Evidence uses a concrete HTTP(S) URL. Non-public Evidence uses its permitted exact locator and no fabricated URL.
- Full raw page content is hashed but not persisted in the session; a bounded excerpt may be retained.
- `AUDIT_QUERY:`, validator prose and self-authored strings are not raw proof.
- History and conflicts are append-only. Current state is a projection, never a destructive overwrite.
- Masked, guessed, historical, supplier-owned and third-party contacts remain leads and never become Account-owned executable routes.
- A phone number is not WhatsApp or Zalo without explicit channel proof.
- Credential fields, credential-like URL parameters and non-finite numbers are rejected recursively. One observation is limited to 2 MiB and one bundle to 32 MiB.

## Peer model

Peer stages are monotonic: `DISCOVERED → QUALIFIED → ANCHOR_ELIGIBLE → PROMOTED_ANCHOR → FULLY_AUDITED`. Entity, product/business fit and novelty require claim-compatible Peer-owned Evidence compiled after discovery; relationship uses the branch-bound discovery Evidence; canonical-new is derived from the registry. Contact coverage is retained but is not required for Anchor eligibility. Every promoted Anchor addresses all six network branches with later Peer-owned Evidence or an explicit below-threshold not-material decision.

## Durability and recovery

- Investigation logs are append-only SHA-256 chains with serialized readers/writers, flush, filesystem synchronization, dead-process sentinel recovery and atomic evaluated-tail appends for Closure/outreach.
- API calls are stateless. Use `resume_investigation` after process or transport loss.
- Bundle and observation hashes make replay idempotent; partial success is explicit.
- The host queue lives outside the Runtime transport and can persist bundles while MCP is unavailable.
- Integrity failure produces `QUARANTINED_READ_ONLY`; never silently rewrite or truncate Evidence.

## CRM and migration

Call `prepare_crm_writeback` for a deterministic plan. Only Artifact Tool may write the declared workbook. The final receipt must prove the actual file, before/after hash, atomic/sparse/history guards, semantic diff, row/cell assertions and post-commit re-import.

Never mutate v5 production data in place. `migrate_v5_4_1_to_v6` rejects empty or overlapping roots, resolves the canonical/pending directories belonging to the supplied session root, copies to a distinct root, appends v6.1 extension events, verifies every chain, rechecks the source manifest and returns `switched=false`. Activation is an external step after acceptance.

## Outreach

Research Closure and CRM sync are independent. A valid v6.1 Closure is short-lived, non-reusable after expiry and single-use. Later Information, research, Peer, Provider or CRM events make it stale. `prepare_outreach` binds it to the exact Account-owned route, Evidence, history, authority, subject, body, stage and expiry, restores the 80–110-word first-touch and concrete-claim authority checks, and issues through an atomic tail check. `render_outreach_action_card` opens a local email draft only. No Runtime tool sends.

## Compatibility

Legacy v5.4.1 receipt, information, provider, pending and CRM APIs remain available for historical lineage. Their Source Family completion and old commercial-cap semantics are compatibility behavior, not v6 policy. Call `get_runtime_contract` before any persistent operation instead of guessing schemas or enums.
