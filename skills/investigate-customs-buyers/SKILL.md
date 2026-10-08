---
name: investigate-customs-buyers
description: "Unified CBI FULL_AUDIT (EXHAUSTIVE) for every CBI buyer/company/contact/customs investigation, integrating Decision-Grade Evidence Saturation and mandatory five-stage identity preflight. No ANSWER_FIRST or FAST_SCAN user-facing investigation route. Preserve append-only evidence and never auto-write CRM or send outreach."
---

# Customs Buyer Intelligence v6.4 — Single FULL_AUDIT

## Only investigation route: CBI FULL_AUDIT + Decision-Grade Evidence Saturation

Every CBI enterprise, buyer, person/contact, customs, first/next/continue-company request invokes ONE investigation route: `FULL_AUDIT` with Runtime `mode=EXHAUSTIVE`. Do not choose `ANSWER_FIRST`, `FAST_SCAN`, a separate one-shot research mode, or a polished early-answer substitute. Older records and protocol enums may retain legacy modes for compatibility only; they are not user-facing investigation choices.

**Identity-first mandatory preflight (ordered; do not skip or silently mark complete):**

1. **Company and industry**: resolve legal/business/brand name, country, line of business, genuine production and known aliases; keep conflicting identities separate.
2. **Google Maps / Business**: use map or business evidence for a geographically relevant factory/business, its grounded address, phone and linked website; record an explicit BLOCKED or UNVERIFIED result if the listing cannot be verified, not invented coordinates.
3. **Official website**: visit official home, About, Contact, Team, footer, mobile, PDF, jobs and related public pages as applicable; distinguish official business channels from scraped third-party information.
4. **Company decision-makers and official social media**: enumerate LinkedIn Company, Facebook, Instagram, X, local social platforms and company-linked people/mentions/comments/employee profiles. Reverse-follow each real website social-media link; the presence of a company account is NOT a named person account.
5. **Every relevant decision-maker's social media and route**: check Procurement/Purchasing/Import, Operations/Production, Engineering/Maintenance, Supply Chain, GM/Director/Owner as applicable. For EACH, record current role/freshness; exact LinkedIn/Facebook/Instagram/X or local-person profile; company-tagged posts; source-linked public email, phone and WhatsApp proof; identity conflicts. Do not hallucinate a personal Facebook or treat an unverified same-name account as confirmed.

No deep customs/installed-equipment/commercial rating may replace or prematurely close this preflight. To avoid wrong-entity persistence, minimal company identity can be verified before `start_investigation`; then call `resolve_or_create_account`/`start_investigation` with `mode=EXHAUSTIVE`, and submit preflight evidence/attempts through the actual Evidence Compiler. Resume existing canonical investigation on `继续` or `下一家`; do not restart already verified claims.

Stage outcomes are `VERIFIED`, `CANDIDATE_UNVERIFIED`, `CONFLICTED`, `BLOCKED`, or `NOT_FOUND_AFTER_DOCUMENTED_SEARCH`. A 403, login wall, crawler timeout or lack of unique Facebook result is NOT evidence that an account does not exist. Continue independent search indexes, official cross-links, directories and appropriately public sources, saving explicit attempts and their boundaries. Company routes never become named-person routes; ordinary phones never become WhatsApp without proof. Recheck job tenure before outreach.

**After preflight** perform the existing twelve-module exhaustive process: customs/IOR/Ultimate Buyer, product definition, manufacturing, historical shipment dedupe, actual equipment suppliers/competition, Buying Group, contact coverage, independent falsification, all six validated Peer branches, claim/EIV-driven pivots and sales readiness. Run at least one serious disconfirming path for each high-impact inference. Preserve independently sourced evidence clusters, unresolved conflicts and alternative strategies; vendor/public-provider pages are not independent if they copy the same underlying source.

**Research-window and closure contract**: for substantive direct investigations, spend a default minimum **28 minutes of ACTIVE useful research** (never idle or simulate elapsed time); after it, continue while high-value unanswered claims remain. If host/runtime cannot reliably sustain/measure the full window or material access is blocked, mark `INTERRUPTED` or `PAUSED_RESOURCE_LIMIT` and provide a **中断交接报告**, never claim completion. Only valid v6.4 Decision Saturation + formal Closure permits `research_complete`; mere source count, fixed depth, high grade, initial contacts, or a fluent report never closes the investigation.

**Side-effect boundary**: the full audit may create append-only investigation Evidence/Pivot/Peer state. CRM/workbook mutation, paid-provider calls, activation of recurring monitoring and external outreach/send remain separate explicit user permissions. Draft email + instant chat are review-only; do not produce executable send actions by default.

## Mandatory seller-identity and capability-fit gate (no legacy PVC contamination)

Before rating any buyer-to-seller fit, bind the *current* seller legal/brand identity and the actual current product catalogue to inspectable source evidence. **SMARTORS machinery / Guangzhou Smartors Machinery** must not inherit XingHuai PVC/WPC board profiles, thickness/spec matrices, seller signature or capability grades. CBI's historical private PVC/WPC capability bundle is maintained only for explicitly identified legacy sheet inquiries; it is not evidence for soap/detergent machinery. `get_capability_profile` and `evaluate_capability_fit` must be called with an explicit, matching `product_profile_id`; without a confirmed machinery profile or current verified machine specs, respond `UNCONFIGURED` / `NEEDS_VERIFICATION`, do not infer machines or create product-fit scores. Continue company/public contact evidence acquisition even when seller fit is unconfigured.

### Machinery discovery is not machine-fit acceptance

The `SOAP_MACHINERY` v1 profile is **buyer-market search taxonomy only**, not a bound SMARTORS seller capability profile. The profile includes explicitly verified *liquid* mixing, emulsifying, water-treatment, filling/capping application vocabulary, but never asserts that SMARTORS makes a complete solid-soap plodder/bar line. Select `product_profile_id=SOAP_MACHINERY` for discovery plans; don't select PVC, WPC, SPC, or ACRYLIC_PMMA to approximate a machine.

Until a separately reviewed model-level machine capability matcher has evidence for **model, batch/throughput, viscosity, utility requirements, power, material/contact grade, footprint, automation, installation, safety and after-sales**, `evaluate_capability_fit` remains `NEEDS_VERIFICATION` even for a capability bundle containing a real official seller listing. This prevents sheet dimension/density comparisons from masquerading as machinery engineering acceptance. Import records of parts prove at most maintenance activity; do not promote them to a confirmed new-line order.

Read [machinery scope and test gate](references/machinery-seller-scope.md) when the buyer, seller or equipment is machinery-related. A `plan_candidate_expansion` response only creates queries; every branch must have host-executed source attempts and durable evidence, not only a generated plan.

## One hosted cloud entry and evidence-saturation source of truth

Use **only** the hosted MCP address configured by the plugin's explicit `mcp.json` binding. The repository-root `.mcp.json` is an isolated legacy engineering/crash-recovery test fixture, **not referenced by the plugin manifest** and never an authorized CBI research fallback. Do not spawn local PowerShell, Windows, Python MCP, or a second CBI Runtime. Do not fall back to obsolete Render v6.3 acceptance or v5/main services. If the hosted MCP is unavailable, report a blocked/interrupted full audit and preserve externally verified leads without claiming a Runtime receipt.

Read [Decision-Grade evidence and interruption contract](references/decision-grade-full-audit.md) before a substantive FULL_AUDIT. For customs/shipment targets, read the unified [customs buyer evidence checklist](references/customs-investigation-checklist.md) in the *same* investigation. These references are not extra Skills or alternative investigation modes.

The host (ChatGPT) runs the public research and retains source genealogy. The CBI Runtime stores governed Evidence/Claims/Pivots; it does not invisibly search public sites for 28 minutes. The `min_active_research_minutes` field in the Runtime Contract is **policy metadata**, not a trusted server-side active-time measurement or automatic timer. Never equate `get_runtime_health=READY`, `get_runtime_contract`, or a successful deployment with a completed Buyer audit. If active research duration or completion cannot be independently demonstrated, return an explicit **中断交接报告** with last verified evidence and next objective, not `research_complete`.

The only default action authorization is read/research plus append-only governed Evidence recording for the requested FULL_AUDIT. Email/chat drafts are optional content for review, not sends. Existing CRM history, external messages, paid provider credits, recurrence, and monitor scheduling require separate explicit user consent.

## Unified FULL_AUDIT runtime sequence

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

This section governs ALL CBI investigations. An interrupted investigation may give durable interim findings but must never be described as exhaustive or complete.

Maintain the twelve business domains as a search playbook: history/account locks; customs integrity; legal/commercial entity; Importer of Record and Ultimate Buyer; product/HS/use boundary; company profile; trade/supplier continuity; Buying Group; contact coverage; network fission; evidence/conflict resolution; sales/CRM/outreach readiness. v6 completion is claim-driven Decision Saturation, not mechanical completion of every Source Family.

Run all six network branches for every Anchor: regional peers, industry peers, same-scale companies, same-supplier real buyers, same-product/HS/application buyers, and competing suppliers/alternatives.

Finding one positive item or one external-provider match never proves Decision Saturation. An ordinary `NEGATIVE` is non-terminal; use `NEGATIVE_EXHAUSTED` only after multiple independent applicable strategies have real raw proof. Use `NOT_APPLICABLE` only with a specific applicability reason. A fixed time, query count, page count, depth, Anchor count, high grade or apparently sendable Route never closes research. A login wall, 403, paywall, captcha, dynamic page or resource limit means `BLOCKED` or `PAUSED_RESOURCE_LIMIT`, not Negative, N/A or Complete.

## Evidence and contact boundaries

Every full audit records real public attempts and evidence in Runtime. Source links in previous chats are leads, not current receipts; never promote a prior chat assertion to Evidence without its recoverable source and correct owner.

Information retention comes before classification. Never discard, hide, replace or omit a real finding merely because it is historical, third-party, supplier-owned, cross-entity, masked, low-confidence, conflicting or not a Buyer Direct Route. Preserve prior records unchanged; append new records; derive the current view with `get_information_history`. A new record may explicitly supersede an old record, but the old record remains in the timeline. Conflicting facts coexist with their dates, Owners, sources and lineage until resolved.

Bind every positive field to same-Owner, same-Module/Branch Evidence and the real Source Attempt. A Negative Attempt carries no Evidence but must retain an actual no-result snapshot or URL and content hash. Never use `AUDIT_QUERY:`, validator prose or self-authored text as raw proof.

Use the Runtime's fixed Claim Type, Freshness and Evidence Grade enums. `PUBLIC_URL` Evidence requires the concrete public page; non-public customs/user/legacy/provider/calculation evidence must use its exact permitted locator and an empty URL. Never invent a URL. Every public positive Information record binds one `claim_key` to already-appended same-claim Evidence IDs.

Commercial grading is claim-level, not narrative-level. Commercial Value uses verified company, product, trade, procurement and competitive facts only; it is independent of contacts, outreach and CRM. Research Confidence reflects authority, freshness, independent corroboration, conflicts and negative-exhaustion quality. Outreach Readiness separately requires a current, verified, Account-owned route and the relevant history/authority safety. A homepage standing in for a contact source, or a person name without Account relationship/role, does not prove a route.

Do not promote masked, guessed, reconstructed, historical, supplier-owned, logistics-owned or unrelated contacts **to Buyer Direct or executable outreach**. This restriction is a use classification, never an ingestion veto. A telephone number is not WhatsApp or Zalo unless the public source explicitly proves that channel. Keep legal entity, commercial operator, brand controller, payment entity, inventory owner and procurement center distinct; explicitly classify Buyer, Importer of Record, Exporter, Trading Intermediary, Declared Manufacturer, Probable Actual Manufacturer and Supplier Group.

An external data-provider plugin is an optional evidence source, not a copied database and not a substitute for the public Source Profile. Never install, connect, authenticate, accept new permissions, consume paid credits, or export bulk proprietary records unless the user explicitly authorizes that separate action. Preserve the provider name, exact tool and call ID, query, permission and billing notice, timestamps, raw locator/hash, Owner, conflicts, freshness and Evidence. A provider phone does not imply WhatsApp/Zalo; masked, guessed or third-party contacts remain non-routes.

Preserve 4.2.1's product, customs, formula, entity, report and Chinese-review behavior; legacy Fast Scan data may be read but new CBI enterprise investigations are EXHAUSTIVE only. One shipment cannot prove an A-grade Buyer, repeat demand, normal monthly demand, warehouse/channel capability, sole supplier, specifications, density, structure or end use.

## Output and outreach

For interim FULL_AUDIT updates, lead with the latest verified decision-useful findings, concrete source links, conflicts and a current interrupted/in-progress state; the complete dossier and Closure remain pending until verified.

In `FULL_AUDIT`, lead with the decision and material risks, then provide evidence-linked findings, counter-hypotheses, calculations, source boundaries, open gaps and executable next steps. State exact incomplete reasons; do not hide them behind a polished report.

Outreach remains draft-only. The first email is normally 80–110 English words with one verified fit, one verified value point and one low-friction question. Do not disclose customs intelligence, incumbent suppliers, unverified specifications or internal risk. Use the currently verified seller's legal brand and company identity from the task; do not inherit a historical PVC seller identity into machinery investigations. Never send, claim a provider-created draft, invent a draft ID, or bypass opt-out/history/Stage guards.

Session logs belong under `%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligence\sessions\`, and host-pending research bundles belong under `%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligence\host-pending-v6\`. Both stay outside plugin source and production workbooks.
