---
name: investigate-customs-buyers
description: "Investigate customs buyers with an answer-first default and an explicit batch-writeback boundary. For ordinary lookups, search applicable public sources and immediately return the latest evidence-linked company, contact, phone, email, decision-chain and route findings without creating Runtime history, audit documents, CRM receipts or workbook writes. Only when the user explicitly requests batch writeback, formal audit, Closure, CRM sync or outreach should the exhaustive machine-audited route run: shipment integrity, entity and ultimate-buyer resolution, product boundary, company and trade profile, supplier chain, Buying Group, public contact Source Families, optional authorized providers, six-branch Peer expansion, conflict resolution and CRM readiness. Never invent facts, Negative proof, WhatsApp/Zalo ownership, provider calls or receipts, Closure IDs, routes, drafts or sends."
---

# Customs Buyer Intelligence v6.1

## Default mode: `ANSWER_FIRST`

Unless the user explicitly requests persistence, formal audit, CRM synchronization, Closure evaluation or outreach preparation, ordinary single-Buyer and sequential contact lookups use `ANSWER_FIRST`.

In `ANSWER_FIRST`:

1. Search and verify the user's requested company, person, email, phone, route, product or latest public fact using the public web/search/browser/registry/maps tools actually visible to the host.
2. Return the latest material findings as soon as the immediate question is answered. This is **response completion**, not `research_complete`, Network Closure, commercial readiness or CRM sync.
3. Do **not** call any Customs Buyer Intelligence MCP tool. The complete forbidden set in `ANSWER_FIRST` is: `get_runtime_contract`, `get_runtime_health`, `get_investigation_health`, `resolve_or_create_account`, `start_investigation`, `resume_investigation`, `submit_research_objective`, `compile_and_append_research_bundle`, `get_claims`, `get_account_state`, `get_investigation_state`, `get_next_research_objectives`, `get_portfolio_queue`, `append_information_record`, `get_information_history`, `plan_public_source_calls`, `plan_provider_calls`, `append_execution_receipt`, `append_provider_receipt`, `append_peer_receipt`, `append_peer_discovery`, `evaluate_peer`, `promote_anchor`, `get_material_pivots`, `close_pivot`, `append_crm_writeback_receipt`, `prepare_crm_writeback`, `evaluate_commercial_readiness`, `evaluate_commercial_value`, `evaluate_research_confidence`, `evaluate_outreach_readiness`, `evaluate_decision_saturation`, `evaluate_investigation_closure`, `prepare_outreach`, `render_outreach_action_card`, `queue_pending_receipt`, `get_pending_journal_status`, `sync_pending_receipts`, `queue_host_bundle`, `sync_pending_bundles`, `sync_pending_research_bundles`, and `migrate_v5_4_1_to_v6`.
4. Do **not** locate, open, compare, render, edit or export the production CRM workbook. Do not generate an audit workbook, audit report, history document, Decision Event, Evidence Ledger row, Source Attempt row, Closure row or CRM receipt.
5. Do not create a local staging file or hidden pseudo-history. The current task's concise answers are the temporary review queue.
6. Include enough provenance for later batching: the concrete source URL or exact user-provided locator, the observed date when relevant, the company/Owner relationship, and any material conflict or uncertainty. A homepage standing in for a contact page is not sufficient when a concrete contact page is available.
7. Prefer current verified content. Do not repeat the full historical dossier unless an older fact materially conflicts with the current finding. Never delete or contradict known history merely to make the latest answer look clean.
8. After a company/contact lookup, generate two evidence-based, ready-to-copy outreach drafts unless the user explicitly says not to: one development email and one instant-chat message. Drafting content is allowed in `ANSWER_FIRST`; calling an outreach Runtime tool, creating an executable link/button, or sending is not.
9. Think through product fit, likely commercial pain, recipient role, market tone, credible value, risk and the lowest-friction next question before drafting. Do not expose hidden chain-of-thought; express only the concise strategy basis and the resulting copy.
10. End with the explicit state: `仅回答｜草稿已生成｜未写回CRM｜未生成审计/Closure｜未生成一键发送｜未发送`.

Use this compact answer shape:

- **最新结论**: the directly useful result;
- **最新联系方式/人物/路线**: only verified items, each with its source;
- **边界**: unresolved ownership, role, freshness, channel or entity conflicts;
- **策略依据**: one concise sentence tying verified fit to the proposed opening angle;
- **邮件草稿**: a tailored subject plus an 80–110 English-word first email using only verified fit and safe value claims, ending with one low-friction question;
- **即时聊天草稿**: a concise WhatsApp/Zalo-style message, normally 35–70 words, in the recipient's practical business language when reliable, otherwise English; ask whether the recipient is the correct person when the role is unverified;
- **临时状态**: `仅回答｜草稿已生成｜未写回CRM｜未生成审计/Closure｜未生成一键发送｜未发送`.

The two drafts must be materially different for their channels, not the same paragraph with formatting changes. Never mention customs surveillance, shipment intelligence, incumbent suppliers, internal scoring, guessed specifications, unsupported certifications, prices or performance promises. When no verified Buyer-owned route exists, still provide copy for review but clearly mark the route as unverified and do not create a send link.

An executable one-click action remains a separate, explicit request. `ANSWER_FIRST` must not produce `mailto:`, `wa.me`, `zalo.me`, `tel:`, a send button, an Action Card or a reusable send token. If the user explicitly asks for `一键发送`, switch to the formal outreach-preparation path and apply the existing route, history, authority, Stage, expiry and Closure guards before rendering anything executable.

`继续`, `下一家`, `再查一个`, a target count such as ten Buyers, or accumulating many answers never authorizes persistence. Stay in `ANSWER_FIRST` until the user gives an explicit instruction such as `新增到表格`, `批量写回`, `正式入库`, `合并到最新CRM`, `生成审核文档`, `评估Closure`, or `准备外联`.

When the user explicitly requests batch writeback, enter `BATCH_COMMIT`: collect only the selected findings from the current task or files the user identifies, locate the latest declared production workbook, refresh stale critical sources where necessary, perform Canonical deduplication, preserve all existing history, append the new facts/evidence once, export once, and run one proportional post-write verification. Do not replay a separate full audit for every Buyer unless the user explicitly requests `FULL_AUDIT`.

If the user starts a different task before batch writeback, do not pretend the earlier temporary queue is automatically available. Read the referenced prior task or ask for the selected result list when it cannot be recovered.

## Persistent/full-audit runtime sequence — explicit request only

The following sequence does **not** run in `ANSWER_FIRST`. Run it only for an explicit `BATCH_COMMIT`, `FULL_AUDIT`, formal CRM/Closure request, or outreach-preparation request. For `BATCH_COMMIT`, perform only the persistence and verification steps needed for the selected findings; the complete twelve-module route remains reserved for `FULL_AUDIT` or a claim of exhaustive completion.

For one Buyer, default to `EXHAUSTIVE`. Use Fast Scan only for explicit preliminary/batch screening and never label it `research_complete`.

1. Parse the user's Chinese/English text, JSON, CSV, XLSX or screenshot evidence with the compatible 4.2.1 scripts. Treat user data as evidence to verify, not final truth.
2. Call `resolve_or_create_account` when identity is ambiguous, then call `start_investigation` before external research. Do not guess Canonical IDs. The returned Source Profile is a search playbook, not a mandatory checklist. Default the provider mode to `PUBLIC_ONLY`; add routes when useful, but never shrink away material claims.
3. Call `get_next_research_objectives` and rank work by Expected Information Value: probability × decision impact × evidence-quality gain × commercial weight ÷ search cost. Use `submit_research_objective` for selected work, then execute it with web/search/browser/registry/maps tools actually visible to the host. Planning performs no search and is never Evidence.
4. Submit real host results in batches of 1–1000 observations through `compile_and_append_research_bundle`. The Evidence Compiler normalizes records, assigns stable IDs and hashes, verifies any supplied SHA-256 against the supplied raw material, maps Claims, preserves conflicts, and creates Pivots. It rejects credentials, non-finite values and oversized rows/bundles. Partial success is valid; rejected rows must be corrected rather than silently dropped. Keep historical, third-party, supplier-owned, masked and low-confidence information, but never promote it into an Account-owned Route.
5. When the investigation explicitly enables connected providers, read [external-provider-orchestration.md](references/external-provider-orchestration.md). Inventory only tools actually visible in the current task, call `plan_provider_calls`, execute the returned provider calls at the Codex layer, and append each real result with `append_provider_receipt`. The local Runtime never invokes another plugin itself.
6. Record each discovered Peer with `append_peer_discovery`, compile Peer-owned identity/product/trade Evidence after discovery, and evaluate it with `evaluate_peer` using `fact_evidence_ids`. Bare booleans never prove eligibility. Peer stages are monotonic; call `promote_anchor` only at `ANCHOR_ELIGIBLE`. Contact coverage is useful but is **not** an Anchor-eligibility gate. A promoted Anchor becomes `FULLY_AUDITED` only after later Peer-owned Evidence evaluates all six branches. Fixed depth or total-Anchor counts never prove completion.
7. Use `get_material_pivots` and close each Pivot explicitly with `close_pivot`. `CONSUMED` requires a later objective containing the Pivot. `NOT_MATERIAL` requires a specific basis and finite `max_remaining_eiv` below the investigation threshold. Terminal Pivot states never regress. Resource or budget exhaustion produces `PAUSED_RESOURCE_LIMIT`, never completion.
8. Evaluate `Commercial Value` (`A+`–`NQ`), `Research Confidence` (`R0`–`R5`), `Outreach Readiness`, and `CRM state` independently. Contact or CRM gaps never cap Commercial Value. Do not merge these dimensions into one grade.
9. Call `evaluate_decision_saturation`, then `evaluate_investigation_closure`. Closure requires resolved critical Claims, no unresolved material Pivot, no material conflict, no undispositioned discovered Peer, no Anchor-eligible Peer awaiting promotion, no promoted Anchor awaiting full audit, and no remaining above-threshold EIV objective. Expired Closure tokens are never reused, and later Information, research, Peer, Provider or CRM events make them stale. CRM sync and outreach readiness do not block research Closure.
10. For CRM work, call `prepare_crm_writeback`, execute the declared unique workbook change only through an external Artifact Tool atomic transaction, and append exact proof with `append_crm_writeback_receipt`. Never mutate a v5 production store in place; use `migrate_v5_4_1_to_v6` to copy, migrate, verify, then switch externally.
11. Produce the complete human-readable dossier even when status is incomplete. Separate `FACT`, `INFERENCE`, `HYPOTHESIS`, `RECOMMENDATION`, and `UNKNOWN`.
12. Only after a valid Closure, call `prepare_outreach` with the Account-owned Route, exact history/authority digests, Subject, Body, Stage and expiry. A first-touch email must remain 80–110 English words and may use concrete dimensions, density, price, certification or performance claims only when present in the immutable authority digest. Render only its returned token with `render_outreach_action_card`.

Before constructing a receipt, call `get_runtime_contract` or inspect the fully nested MCP schema; never guess enums. If a research batch cannot reach MCP, write it to the process-independent host queue with `queue_host_bundle` or `scripts/host_pending_research_bundles.py`, then use `sync_pending_bundles` after recovery. Legacy append receipts may still use `queue_pending_receipt` and `sync_pending_receipts`. Equivalence is proven from immutable IDs, hashes and lineage, not assumed. Use `resume_investigation` after any transport restart; the transport session is never the owner of investigation state.

Read [unified-runtime-contract.md](references/unified-runtime-contract.md) before the first receipt or Closure call. Read [v3-operating-contract.md](references/v3-operating-contract.md), [strategic-decision-contract.md](references/strategic-decision-contract.md), and [outreach-contract.md](references/outreach-contract.md) when producing the final dossier and outreach appendix.

## Non-negotiable investigation depth

This section governs `FULL_AUDIT`, formal Closure and any claim that research is comprehensive or complete. It does not force `ANSWER_FIRST` to run the twelve modules before giving the user a useful current answer. An `ANSWER_FIRST` response must disclose its open boundaries and must never be described as exhaustive or complete.

Maintain the twelve business domains as a search playbook: history/account locks; customs integrity; legal/commercial entity; Importer of Record and Ultimate Buyer; product/HS/use boundary; company profile; trade/supplier continuity; Buying Group; contact coverage; network fission; evidence/conflict resolution; sales/CRM/outreach readiness. v6 completion is claim-driven Decision Saturation, not mechanical completion of every Source Family.

Run all six network branches for every Anchor: regional peers, industry peers, same-scale companies, same-supplier real buyers, same-product/HS/application buyers, and competing suppliers/alternatives.

Finding one positive item or one external-provider match never proves Decision Saturation. An ordinary `NEGATIVE` is non-terminal; use `NEGATIVE_EXHAUSTED` only after multiple independent applicable strategies have real raw proof. Use `NOT_APPLICABLE` only with a specific applicability reason. A fixed time, query count, page count, depth, Anchor count, high grade or apparently sendable Route never closes research. A login wall, 403, paywall, captcha, dynamic page or resource limit means `BLOCKED` or `PAUSED_RESOURCE_LIMIT`, not Negative, N/A or Complete.

## Evidence and contact boundaries

In `ANSWER_FIRST`, concrete inline source links or exact user-provided locators are transient provenance, not Runtime Evidence or receipts. If the user later requests `BATCH_COMMIT` or `FULL_AUDIT`, reapply the formal Evidence/Owner/Claim requirements below before persistence; never upgrade a prior chat statement into CRM truth without its recoverable source.

Information retention comes before classification. Never discard, hide, replace or omit a real finding merely because it is historical, third-party, supplier-owned, cross-entity, masked, low-confidence, conflicting or not a Buyer Direct Route. Preserve prior records unchanged; append new records; derive the current view with `get_information_history`. A new record may explicitly supersede an old record, but the old record remains in the timeline. Conflicting facts coexist with their dates, Owners, sources and lineage until resolved.

Bind every positive field to same-Owner, same-Module/Branch Evidence and the real Source Attempt. A Negative Attempt carries no Evidence but must retain an actual no-result snapshot or URL and content hash. Never use `AUDIT_QUERY:`, validator prose or self-authored text as raw proof.

Use the Runtime's fixed Claim Type, Freshness and Evidence Grade enums. `PUBLIC_URL` Evidence requires the concrete public page; non-public customs/user/legacy/provider/calculation evidence must use its exact permitted locator and an empty URL. Never invent a URL. Every public positive Information record binds one `claim_key` to already-appended same-claim Evidence IDs.

Commercial grading is claim-level, not narrative-level. Commercial Value uses verified company, product, trade, procurement and competitive facts only; it is independent of contacts, outreach and CRM. Research Confidence reflects authority, freshness, independent corroboration, conflicts and negative-exhaustion quality. Outreach Readiness separately requires a current, verified, Account-owned route and the relevant history/authority safety. A homepage standing in for a contact source, or a person name without Account relationship/role, does not prove a route.

Do not promote masked, guessed, reconstructed, historical, supplier-owned, logistics-owned or unrelated contacts **to Buyer Direct or executable outreach**. This restriction is a use classification, never an ingestion veto. A telephone number is not WhatsApp or Zalo unless the public source explicitly proves that channel. Keep legal entity, commercial operator, brand controller, payment entity, inventory owner and procurement center distinct; explicitly classify Buyer, Importer of Record, Exporter, Trading Intermediary, Declared Manufacturer, Probable Actual Manufacturer and Supplier Group.

An external data-provider plugin is an optional evidence source, not a copied database and not a substitute for the public Source Profile. Never install, connect, authenticate, accept new permissions, consume paid credits, or export bulk proprietary records unless the user explicitly authorizes that separate action. Preserve the provider name, exact tool and call ID, query, permission and billing notice, timestamps, raw locator/hash, Owner, conflicts, freshness and Evidence. A provider phone does not imply WhatsApp/Zalo; masked, guessed or third-party contacts remain non-routes.

Preserve 4.2.1's product, customs, formula, entity, report, Chinese-review and Fast Scan behavior. One shipment cannot prove an A-grade Buyer, repeat demand, normal monthly demand, warehouse/channel capability, sole supplier, specifications, density, structure or end use.

## Output and outreach

In `ANSWER_FIRST`, lead with the latest decision-useful content and keep the response compact. Do not generate a long dossier, audit appendix, workbook narrative or history comparison. Provide concrete source links, material conflicts, one concise strategy basis, the tailored email draft, the tailored instant-chat draft and the explicit no-write/no-send state.

In `FULL_AUDIT`, lead with the decision and material risks, then provide evidence-linked findings, counter-hypotheses, calculations, source boundaries, open gaps and executable next steps. State exact incomplete reasons; do not hide them behind a polished report.

Outreach remains draft-only. The first email is normally 80–110 English words with one verified fit, one verified value point and one low-friction question. Do not disclose customs intelligence, incumbent suppliers, unverified specifications or internal risk. Use the approved Mark Zhou / Guangzhou XingHuai New Materials Co., Ltd. signature. Never send, claim a provider-created draft, invent a draft ID, or bypass opt-out/history/Stage guards.

Session logs belong under `%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligence\sessions\`, and host-pending research bundles belong under `%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligence\host-pending-v6\`. Both stay outside plugin source and production workbooks.
