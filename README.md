# Customs Buyer Intelligence v6.4

Single hosted CBI v6.4 research system: ONE `FULL_AUDIT` / `EXHAUSTIVE` buyer investigation workflow with the Decision-Grade evidence-saturation discipline. Every substantive company, named decision maker or customs-derived buyer task starts with company/industry identity → Google Maps/Business → official website → company social accounts/management → each named decision maker's public social and contact routes. Legacy `ANSWER_FIRST`, `FAST_SCAN`, and the previously independent customs one-shot Skill are **not new investigation entrypoints**.

## Cloud and client entry

The user-facing portable and Codex plugin manifests both bind directly to ONE remote `mcp.json` endpoint: `https://cbi-v61-preview.onrender.com/mcp`. The historical service name contains v6.1 but the deployed Runtime reports v6.4. The repository-root `.mcp.json` retains a Windows-local launcher **only for isolated engineering, WAL and crash-recovery tests**, and is not referenced by any active plugin manifest; it must never be used as a chat-research fallback. The separate `customs-investigation-checklist.md` and `decision-grade-full-audit.md` are internal references of ONE `investigate-customs-buyers` Skill, not independent Skills.

## Default operation

1. Resolve legal/entity identity and verify minimal location/industry before assigning or resuming a Canonical Buyer.
2. Exhaust company Google Maps, official site, company social channels, and the named decision makers' own public social routes with evidence provenance. Distinguish VERIFIED / CANDIDATE / CONFLICTED / BLOCKED / UNKNOWN. No assumed Facebook or guessed owner.
3. Record actual SourceAttempts, Evidence, counterevidence and independent source clusters; run the existing twelve modules, EIV-ranked research objectives, six validated Peer branches, Pivot resolution and formal Decision Saturation / Closure.
4. For substantive directly invoked research, default to 28 minutes of **active useful research**, not idle padding. **The cloud Runtime currently does not independently attest active research duration.** Host is responsible for accurate records; if the window or Closure cannot be verified, return a durable `中断交接报告`, not a fabricated completion statement.
5. Recording verified FULL_AUDIT research receipts does not imply permission to write CRM/Excel, use paid data providers, start background monitoring, or perform any customer outreach. Those side effects remain separately authorized. Draft text is not a send.

The architecture is Host Research Agent → batch Evidence Compiler → claim-driven Governance Runtime → separately authorized Artifact Tool transaction. Commercial Value, Research Confidence, Outreach Readiness and CRM state remain distinct. Public-source search remains the default.

Core enforcement:

- twelve business domains and public Source Families retained as an extensible search playbook, not a mechanical completion checklist;
- claim-driven research objectives ranked by Expected Information Value under a budget that can pause but never close research;
- batch Evidence Compiler for 1–1000 observations with partial success, exactly-once concurrent replay, bounded payloads, raw-content/hash equality, Owner/Claim/Source binding, conflict preservation and Pivot generation;
- Decision Saturation only after critical Claims resolve, material conflicts/Pivots close, every discovered Peer is dispositioned, Anchor-eligible Peers are promoted or proven below threshold, promoted Anchors finish claim/EIV-driven six-branch audits and no above-threshold objective remains;
- monotonic Peer stages `DISCOVERED → QUALIFIED → ANCHOR_ELIGIBLE → PROMOTED_ANCHOR → FULLY_AUDITED`; positive qualification facts require claim-compatible Peer-owned Evidence, while contact coverage is not an Anchor-eligibility gate;
- Runtime-owned exact/tax/alias/address/external-ID canonical matching and atomic C-number allocation;
- distinct Buyer, Importer of Record, Exporter, Trading Intermediary, Declared Manufacturer, Probable Actual Manufacturer and Supplier Group roles;
- strict valid-Unicode-scalar rejection and NFC normalization before validation, query, hashing and persistence;
- independent `research_complete`, `network_complete`, `crm_sync_complete`, `outreach_prerequisites_complete` and `outreach_ready` states;
- self-describing MCP schemas plus `get_runtime_contract` so agents do not guess enums or nested fields;
- `plan_public_source_calls` exposes missing public work and remains planning-only; `execute_public_crawl` can execute bounded public website tasks through the self-hosted Crawl4AI/Playwright runtime, while registry/maps/provider work remains host-orchestrated and all resulting Evidence stays receipt-bound;
- conditional Evidence references: public Claims require concrete `http(s)` URLs, while user/customs/legacy/provider/local/calculation facts require their matching exact non-URL locators and may not carry fabricated URLs;
- fixed Claim Type, Freshness and A1-D Evidence Grade enums, plus `claim_key -> evidence_id -> URL/locator` binding for public positive Information;
- Commercial Value (`A+`–`NQ`), Research Confidence (`R0`–`R5`), Outreach Readiness and CRM state are independent; contact/CRM gaps do not cap Commercial Value;
- `append_crm_writeback_receipt` proves the declared unique main workbook through actual OOXML/hash verification, Artifact Tool identity, atomic/sparse/history/re-import gates, row/cell assertions and semantic Previous/Current Diff;
- append-only Runtime Pending Receipt Journal plus a process-independent host bundle queue with content-hash deduplication and explicit-only replay; MCP initialization never writes or synchronizes either queue;
- append-only, chain-hashed Information, SourceAttempt, ProviderReceipt, Evidence, Pivot, Peer, Closure and Outreach logs with dead-process lock recovery and atomic tail checks for Closure/outreach issuance;
- historical rows are never overwritten; new Buyer, cross-entity, supplier, referral, channel, low-confidence and conflict findings are retained and merged into a derived current view;
- information ingestion and outreach eligibility are separate: an ineligible Route remains available as a lead with its real Owner and relationship;
- explicit `PUBLIC_ONLY`, optional-provider and required-provider modes with provider allowlists, permission and paid-credit gates;
- Host-level authorized provider orchestration through `plan_provider_calls` and `append_provider_receipt`; the cloud MCP never impersonates or directly invokes another provider;
- self-hosted crawler execution requires no TinyFish, Firecrawl Hosted, Apify Cloud or other paid crawling API; private/local network targets, unsafe redirects and guarded browser subrequests fail closed, with bounded pages, retries and concurrency;
- same-Owner/same-Module/source-compatible Evidence binding;
- later, independent Pivot consumption; a material Pivot cannot be dismissed without a measured below-threshold remaining EIV, and terminal Pivot states cannot regress;
- no completion from a first positive, A/A+ grade, fixed time, query count, page count, depth or Anchor count;
- blocked/logged-in/paywalled sources remain incomplete, critical Claims cannot be hidden behind N/A, and declared Negative-exhaustion strategies must bind to distinct real attempt queries;
- Account-owned Route, history, authority, Stage, subject/body and one-time token gates;
- provider results never replace public Source Families, automatically imply WhatsApp/Zalo, or self-close research;
- draft-only `mailto:` action; no send tool and no fabricated provider receipt.

Production CRM, customer data and session logs are not stored in the plugin. The hosted Runtime uses its configured durable server paths/object-store replication. Historical Windows-local journal CLI paths remain for offline maintenance and migration only; they are **not** runtime routes advertised by the plugin. If the remote MCP is unreachable, a remote chat cannot claim a local fallback or completed evidence persistence. Replaying queued receipts always requires explicit synchronization, not merely an MCP initialization.

Release validation runs the six compatibility self-tests, unified Runtime/adversarial tests, MCP protocol tests, plugin/skill validators, privacy scanning, Windows UTF-8/path tests and cold-copy checks.
