# v4.2 Intelligence-First Operating Contract

The outreach-specific evidence, suppression, content-firewall, language/time, draft, and send boundaries are defined in [outreach-contract.md](outreach-contract.md). Research status and outreach readiness remain independent.

The strategic relationship, procurement decision-center, brand/OEM, related-party pricing, four-dimensional commercial value, three-layer CRM, and controlled-learning boundaries are defined in [strategic-decision-contract.md](strategic-decision-contract.md).

## Purpose

This contract defines what the engine may claim, how it records incomplete research, what the human-facing dossier must explain, and what may enter CRM. It supplements the JSON schema.

The full intelligence dossier is the primary product. Outreach is a separate appendix. `DRAFT_BLOCKED` and `NO_OUTREACH_RECOMMENDED` affect only the outreach layer and must never reduce research coverage, suppress findings, or replace the dossier with a scorecard.

## Two independent status axes

- `status`: execution result. Values: `complete`, `partial`, `failed`.
- `research_status`: research coverage. Values: `fast_scan_complete`, `research_complete`, `incomplete_research`.

A successful Fast Scan may be `status: complete` and `research_status: fast_scan_complete`. It must not be mislabeled incomplete merely because online research was intentionally not run.

For a single buyer, Fast Scan is an intermediate parsing stage unless the user explicitly asks for a preliminary scan. The final answer defaults to Deep Dive. Batch mode may stop at clearly labeled Fast Scan output.

## Claim classes

- `FACT`: directly supported by the supplied record or a cited source. A user-supplied customs row is evidence of what the row states, not independent proof that every field is correct.
- `INFERENCE`: derived from facts using a reproducible rule or calculation.
- `HYPOTHESIS`: one plausible explanation among alternatives. Weight/specification fits always remain hypotheses until corroborated.
- `RECOMMENDATION`: an action, prioritization, or sales judgment.
- `UNKNOWN`: unavailable, contradictory, contaminated, blocked, or not researched.

## Field states

Every material field records raw value, normalized value, confidence, status, evidence, rejection reason, scope, and CRM eligibility. Permitted states include `confirmed`, `plausible`, `unresolved`, `contradictory`, and `contaminated`.

External company claims additionally record exact source URL, visible/source text, publication date when available, retrieval date, freshness, official confirmation, independent-source count, and negative/conflicting evidence. Legal identifiers and current legal status require grade A1 confirmation; directories remain plausible leads.

## Source grades

- `A1`: current official registry or government source.
- `A2`: current official company-controlled channel.
- `B1`: customs/trade record or strong independent primary record.
- `B2`: reputable independent reporting or professional source.
- `C1`: current structured directory/listing.
- `C2`: historical, weak, or secondary directory/listing.
- `D`: user assertion, search snippet, inference, or unverified lead.

Evidence grade measures source quality, not truth certainty. Multiple pages copied from one database remain one independence group.

## Product taxonomy safeguards

The engine distinguishes PVC foam board, free-foam, Celuka/crust, co-extruded, WPC, laminated board, KT/PS/paper foam board, PVC edge band, solid PVC sheet, structural/marine foam core, and mixed/ambiguous products. A shared token such as `board`, `foam`, or `PVC` is insufficient for an exact match.

Dimensions characteristic of edge banding and PS/paper sandwich boards override generic foam-board tokens. Marine structural core is never treated as ordinary furniture/signage PVC foam board.

## Route safeguards

Place of receipt, port of lading, transshipment port, FROB movement, destination, country of export, and manufacturing origin are separate fields. Port geography alone cannot establish manufacturing origin. Container declarations and TEU are checked for consistency; a 40-foot container is normally two TEU, but the rule remains a consistency check rather than a fabricated container type.

## Calculation safeguards

Calculations publish formula, inputs, result, unit, scope, business meaning, assumptions, verification method, and reproducibility. Packages never silently become pieces or sheets. Where package-to-sheet conversion or density is unknown, the engine may emit `best_fit`, `alternative_1`, and `alternative_2` scenarios only when the inputs support those scenarios; all remain `HYPOTHESIS` until corroborated.

Never infer a sheet-count range when thickness or product dimensions are absent. Never infer `1220×2440`, `3–10 mm`, Celuka/free-foam structure, density, end use, warehouse capacity, sales channel, repeat purchasing, or sole-supplier dependency from a generic PVC foam-board description or one shipment.

## Entity safeguards

Customs name, legal entity, trade name, branch, affiliate, notify party, supplier, freight forwarder, broker, importer of record, and end buyer are not merged without evidence. Alias similarity is a candidate signal, never sufficient proof. Conflicting identifiers are quarantined.

## Contact safeguards

Every contact records value, person, role, company, source type, source reference, source date, discovery date, last verification, confidence, verification status, recommended use, risk note, evidence grade, and source IDs.

An email in a bill of lading may be current for that shipment but is not automatically a current sales or procurement channel. Generic logistics, broker, HR, accounting, or shipping contacts cannot be promoted to procurement decision-maker. Shared emails across unrelated entities are marked for verification-only use.

Blocked dynamic social pages are not silently skipped. They create `manual_visual_check_required` work with a target and inspection instructions. A screenshot path alone is not visual evidence; an observation with path, date, and crop/page coordinates is required.

`official_current`, current position, and procurement authority are separate determinations. A current official generic email is a valid company channel but not a procurement contact. A WhatsApp link or successful URL open does not prove registration or ownership. Current-contact status requires a company-controlled source observed within the freshness target.

## Review layers

Each audited field retains `plugin_output`, optional `assistant_review`, `final_decision`, `changed`, and `change_reason`. A correction without a reason fails the Deep Dive quality gate. Review does not upgrade a claim unless the final evidence supports the upgraded status.

## Entity relationships

Brand/operator/affiliate relationships store entity A, entity B, relationship type, status, confidence, evidence, independent-source count, missing evidence, and merge permission. Two complementary sources may support a relationship but do not authorize a legal merge. Legal merging requires an official legal disclosure, registry relationship, trademark owner, or equivalent A1 basis.

## Trade-history audit

Repeat purchasing is based on dated, de-duplicated, product-specific rows. Each row preserves bill/declaration/item identifiers, raw product, quantity/UOM, weight, provider, provider count unit, data level, sources, and duplicate status. Provider totals are never added or directly compared unless their counting units and de-duplication methods match.

## Map and link labels

A Google Maps search URL is labeled `地图搜索入口`; it is not a confirmed Google Business Profile. Confirmed business-profile pages, official sites, official social accounts, directories, trade databases, registry entry points, and manual-check links use distinct labels.

## Competitive matrix

Competitive capability rows require evidence, a stated gap, and an acceptance criterion. A numeric score is withheld while any scored row is unknown or unsupported. The engine never invents the user's factory capability merely to complete a comparison.

## Research waterfall

The 21-step coverage ledger is exhaustive as a checklist but adaptive in execution. Fast Scan marks online steps `not_applicable_fast_scan`. Deep Dive records each step as checked, checked-no-hit, blocked, login-required, dynamic-unreadable, or not-checked. It stops redundant queries when adequate evidence exists and uses bounded retries/circuit breakers.

## Persistent contamination

The local SQLite index records bill numbers, containers, addresses, and emails with entity and input hashes. Reuse across unrelated buyers or countries produces a conflict flag. High-severity bill/container collisions suspend scoring. Contaminated fields are never exported to CRM.

## CRM policy

Only confirmed or plausible, non-ambiguous, non-contaminated fields are exportable. `blocked_fields` preserves omissions and reasons. A CRM row can be `ready_with_limits`; this never means research is complete.

## Quality gate

Deep Dive is `research_complete` only when the required official-channel checks, social/manual handling, source-linked contact use, claim labels, scope separation, route explanations, reproducible calculations, contamination exclusion, and executable next action pass. Otherwise it remains `incomplete_research`, even if the process itself succeeded.

Research completeness and outreach eligibility are independent. A missing email may block outreach but cannot fail or shorten an otherwise complete dossier. The human-facing value gate also requires material findings, reverse possibilities, calculation meaning, buyer-role and product-form alternatives when unresolved, dated continuity evidence or an explicit single-record limitation, direct verification links, supplier/exporter/manufacturer separation, XingHuai fit and gaps, reviewed CRM fields, and prioritized actions. Raw JSON object dumps do not satisfy this gate.

## Required report sections

The Markdown report has 18 fixed intelligence sections: commercial conclusion; data correction and immutable input; correct route; product facts/inferences/unknowns; quantity/weight/value calculations; buyer identity; buyer role and decision center; dated trade continuity; supplier/exporter/manufacturer chain; official site/social/maps/legal/contact evidence; contact priority and all email routes; XingHuai fit; competition and entry route; categorical grades and stage; reviewed CRM; prioritized actions; unresolved/manual work; and facts/inferences/hypotheses/recommendations/evidence boundary. Append outreach as `18.1` only after the dossier.

Render Chinese prose and Markdown tables. Structured JSON remains an audit artifact, not a user-facing substitute for analysis.

## Auditability

The output includes input and rules hashes plus a stage hash chain. This detects accidental post-run changes; it is not a cryptographic signature or proof of source authenticity.
