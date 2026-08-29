# Customs Buyer Intelligence v6.1

Personal Codex plugin for answer-first public buyer research plus explicit, batch-only CRM persistence. Ordinary company/contact lookups now search and answer immediately without creating Runtime history, audit documents, Closure records or workbook writes. The current task acts as the temporary review queue. Only an explicit user instruction such as `新增到表格`, `批量写回`, `正式入库`, `合并到最新CRM`, `生成审核文档`, `评估Closure` or `准备外联` activates the corresponding persistent workflow.

The explicit full-audit route is now the v6 production architecture: Host Research Agent → batch Evidence Compiler → claim-driven Governance Runtime → Artifact Tool transaction, with a Portfolio Scheduler/Budget Controller and a process-independent host recovery queue. Completion is Decision Saturation, not a mandatory Source Family checklist. Commercial Value, Research Confidence, Outreach Readiness and CRM state are independent. Public sources remain the default; connected providers stay opt-in and separately authorized. The 4.2.1 parser, formulas, entity/product analysis, Fast Scan, Deep Dive report, Chinese review and draft-only `mailto:` experience remain compatible.

The six phase-one engineering documents are in `docs/v6/`: current architecture audit, target architecture, migration plan, API specification, data model and test plan.

Default workflow:

- `ANSWER_FIRST`: research and return the latest verified content with concrete sources; no Runtime persistence, CRM/history/audit document, Closure or send action;
- every company/contact result also includes two tailored, ready-to-copy drafts: one development email and one instant-chat message; these are content only, not executable actions;
- `BATCH_COMMIT`: only after explicit instruction, collect the selected recent results, locate the latest production workbook, Canonical-deduplicate, preserve history, append once, export once and verify once;
- `FULL_AUDIT`: only when explicitly requested, run the complete twelve-module, six-branch, receipt-bound route;
- an item count such as ten Buyers never triggers automatic writeback.

`ANSWER_FIRST` never generates `mailto:`, `wa.me`, `zalo.me`, `tel:`, a send button or an Action Card. An explicit one-click-send request enters the existing guarded outreach workflow; route ownership, history, authority, Stage, expiry and Closure still have to pass before anything executable is rendered.

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
- `plan_public_source_calls` exposes missing public work but explicitly performs no search and creates no Evidence; the host executes visible web/browser/registry/maps tools and appends real receipts;
- conditional Evidence references: public Claims require concrete `http(s)` URLs, while user/customs/legacy/provider/local/calculation facts require their matching exact non-URL locators and may not carry fabricated URLs;
- fixed Claim Type, Freshness and A1-D Evidence Grade enums, plus `claim_key -> evidence_id -> URL/locator` binding for public positive Information;
- Commercial Value (`A+`–`NQ`), Research Confidence (`R0`–`R5`), Outreach Readiness and CRM state are independent; contact/CRM gaps do not cap Commercial Value;
- `append_crm_writeback_receipt` proves the declared unique main workbook through actual OOXML/hash verification, Artifact Tool identity, atomic/sparse/history/re-import gates, row/cell assertions and semantic Previous/Current Diff;
- append-only Runtime Pending Receipt Journal plus a process-independent host bundle queue with content-hash deduplication and explicit-only replay; MCP initialization never writes or synchronizes either queue;
- append-only, chain-hashed Information, SourceAttempt, ProviderReceipt, Evidence, Pivot, Peer, Closure and Outreach logs with dead-process lock recovery and atomic tail checks for Closure/outreach issuance;
- historical rows are never overwritten; new Buyer, cross-entity, supplier, referral, channel, low-confidence and conflict findings are retained and merged into a derived current view;
- information ingestion and outreach eligibility are separate: an ineligible Route remains available as a lead with its real Owner and relationship;
- explicit `PUBLIC_ONLY`, optional-provider and required-provider modes with provider allowlists, permission and paid-credit gates;
- Codex-level cross-plugin orchestration through `plan_provider_calls` and `append_provider_receipt`; the local MCP never impersonates or directly invokes another provider;
- same-Owner/same-Module/source-compatible Evidence binding;
- later, independent Pivot consumption; a material Pivot cannot be dismissed without a measured below-threshold remaining EIV, and terminal Pivot states cannot regress;
- no completion from a first positive, A/A+ grade, fixed time, query count, page count, depth or Anchor count;
- blocked/logged-in/paywalled sources remain incomplete, critical Claims cannot be hidden behind N/A, and declared Negative-exhaustion strategies must bind to distinct real attempt queries;
- Account-owned Route, history, authority, Stage, subject/body and one-time token gates;
- provider results never replace public Source Families, automatically imply WhatsApp/Zalo, or self-close research;
- draft-only `mailto:` action; no send tool and no fabricated provider receipt.

Production CRM, customer data and session logs are not stored in the plugin. Session logs default to `%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligence\sessions\`; canonical and pending journals are sibling data directories, outside plugin source. If the MCP Tunnel itself is completely unreachable, a remote chat cannot call any local fallback tool. The bundled local Journal CLI can still queue receipts, but the server never replays them merely because MCP initializes; synchronization requires an explicit `sync_pending_receipts` call. A truly transparent remote fallback would require a separately authorized always-online cloud queue.

Release validation runs the six compatibility self-tests, unified Runtime/adversarial tests, MCP protocol tests, plugin/skill validators, privacy scanning, Windows UTF-8/path tests and cold-copy checks.
