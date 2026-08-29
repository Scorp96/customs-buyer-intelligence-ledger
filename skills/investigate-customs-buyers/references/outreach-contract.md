# Outreach Execution Contract v4.2

## Contents

1. Purpose and non-goals
2. Evidence ledgers
3. Eligibility and state machine
4. Buyer-problem hypotheses
5. External-content firewall
6. Message construction
7. Contact-role adaptation
8. Language and time
9. Risk, suppression, and follow-up
10. Draft and send boundary
11. Output order
12. Acceptance rules

## 1. Purpose and non-goals

Run outreach only after customs parsing, entity resolution, data-quality audit, buyer intelligence, contact discovery, and evidence review. Optimize for the correct account, contact route, relevance, and safe next step—not message volume.

Never attempt to evade spam filters. Never auto-send, auto-batch, rotate accounts, use tracking pixels, disguise subjects, or continue after refusal/unsubscribe.

Default to `CREATE_DRAFT`. Every single-buyer investigation must finish with `SENDABLE_DRAFT`, `DRAFT_BLOCKED`, or `NO_OUTREACH_RECOMMENDED`; report-only output is forbidden. The deterministic engine creates a plan and draft only. Sending requires a separate email connector action and a fresh, explicit user confirmation after preview.

The terminal state belongs to the outreach appendix only. It must never replace, abbreviate, reorder ahead of, or lower the quality of the intelligence dossier.

## 2. Evidence ledgers

Maintain two separate ledgers:

- `buyer_evidence_ledger`: public buyer facts and explicitly approved buyer claims.
- `seller_capability_ledger`: XingHuai identity, product, process, performance, certification, and supply capabilities.

Each claim must include claim, claim type, source, source date, confidence, verified status, external-use status, and reason. Only `FACT + verified=true + allowed_for_external_use=true` may enter customer-facing copy.

Seller capability states are `VERIFIED`, `CONDITIONAL`, `UNVERIFIED`, `EXPIRED_EVIDENCE`, and `NOT_SUPPORTED`. Only `VERIFIED` claims may enter the first message. Do not convert conditional or historical test evidence into a current all-product claim.

Approved fixed identity:

- Guangzhou XingHuai New Materials Co., Ltd.
- Mark Zhou
- Mobile / WhatsApp: +86 180 2710 1852
- Website: www.xinghuai.com

Do not use `www.xhhbjc.com`.

Do not claim current ISO/fire certification, `fireproof`, `100% waterproof`, universal lead-free status, marine structural grade, or universal thickness/density/decor/matching-accessory capability without a verified current ledger entry.

## 3. Eligibility and state machine

Support:

- `RESEARCH_ONLY`
- `OUTREACH_PREVIEW`
- `CREATE_DRAFT` (default)
- `SEND_CONFIRMED`

States include `RESEARCH_ONLY`, `PREVIEW_READY`, `DRAFT_READY`, `SEND_REQUIRES_CONFIRMATION`, `SENT`, `FOLLOW_UP_DUE`, `REPLIED`, `DO_NOT_CONTACT`, `SUPPRESSED`, and `BLOCKED`.

Pass the eligibility gate only when:

1. enterprise identity grade is A or B;
2. the entity is an actual buyer/importer/distributor/manufacturer/brand operator—not logistics-only;
3. product fit is `EXACT` or `RELATED`;
4. at least one current A1/A2 business email is available;
5. the selected contact is not rejected, departed, a broker-only contact, or an inferred email;
6. at least one externally usable verified seller product capability matches;
7. language and timezone can be stated with evidence or a disclosed fallback;
8. no refusal, unsubscribe, suppression, or 72-hour duplicate-first-contact block applies.

Return explicit block reasons such as `buyer_identity_unresolved`, `customs_broker_only`, `product_mismatch`, `only_inferred_email`, `capability_unverified`, `already_unsubscribed`, `duplicate_contact_window`, and `legal_or_compliance_risk`.

## 4. Buyer-problem hypotheses

Research what procurement problem the buyer may face before drafting. Separate:

- `CONFIRMED`: directly stated by a usable source;
- `SUPPORTED_INFERENCE`: supported but not explicitly confirmed;
- `UNVERIFIED_HYPOTHESIS`: plausible and still unverified.

Never tell a buyer that it has a quality, supply, price, or capacity problem unless that problem is confirmed and allowed for external use. Convert supported or unverified problems into conditional positioning:

> We can support an additional-source evaluation where stable specifications or backup capacity are required.

Do not write:

> We can solve your current quality problem.

Use buyer type to select one product direction and at most two value points. Mature incumbent supply usually supports `additional_source`, `controlled_trial`, or `source_diversification` positioning—not competitor disparagement.

## 5. External-content firewall

Block from all external messages:

- customs database/provider references;
- bill, declaration, manifest, container, and exact shipment identifiers;
- exact import date, quantity, weight, value, price, or frequency;
- current/historical supplier names and inferred supplier weaknesses;
- inferred density, thickness, structure, sheet count, or packing conversion;
- buyer risk, credit, legal, or conversion scores;
- broker details, residential/private-person information, or sensitive personal data;
- internal competitive strategy;
- wording such as “we saw your imports” or “we know you buy from…”.

Buyer product facts may enter copy only when publicly confirmed by the buyer, explicitly stated in an inquiry/reply, or specifically approved by the user. Seller statements still require a verified seller-ledger claim.

## 6. Message construction

Answer five questions:

1. Who is Mark Zhou?
2. What does XingHuai manufacture?
3. Why is the message relevant to this buyer?
4. What concrete business value is offered?
5. What one response is expected?

Keep deep research backstage and the first contact human and short. Use three short content paragraphs plus signature:

1. identity and, when needed, internal-forwarding request;
2. one verified buyer/product match and one verified value point;
3. one low-pressure CTA.

Default English first-contact target: 80–110 words, one screen, maximum one website link, no catalog, no large attachment, no images, no short links, no tracking pixel, no false urgency, no multiple exclamation marks, and no capability list.

Block a first message that reads like a research report or technical questionnaire: do not say “I reviewed your public catalog,” do not list four or more specifications, and do not ask multiple questions. Do not invent a buyer pain point. Use a confirmed public observation naturally, or use neutral category relevance when no externally usable observation exists.

Subject target: 30–60 characters, product-relevant and literal. Block deceptive `Re:`/`Fwd:` prefixes and marketing terms such as Best Price, Lowest Price, Promotion, Limited Time, Guaranteed, and Urgent.

## 7. Contact-role adaptation

- General mailbox: request forwarding to the responsible category owner.
- Sales/Account Executive/Marketing: request an internal referral; never relabel as procurement.
- Management contact: ask whether they oversee the category or who does.
- Verified purchasing/import manager: ask which single specification or evaluation step comes first.
- Technical/product development: ask for performance criteria and sample-validation process.
- Broker/freight-forwarder/notify-only contact: block as a sales target.

Keep original titles and show `purchasing authority unverified` when that is the evidence state.

For multiple emails, discover and display every address with source, date, role, verification, route class, and reason. Use `DIRECT_PROCUREMENT`, `FORMAL_GENERAL`, `ALTERNATIVE_REFERRAL`, `VERIFY_ONLY`, or `DO_NOT_USE`. Select one primary route and create separate draft links for eligible alternatives. Never omit a found address from the audit, but never treat exhaustive discovery as permission to send to HR, historical, inferred, broker, or departed-person addresses. Never default to CC/BCC or simultaneous multi-address sending.

## 8. Language and time

Select language in order: official website, official social, contact’s public language, local business language, industry norm, English fallback. A country default is only a fallback and must be labeled as such. Chinese translation is for Mark’s review and is not part of the customer message.

Use IANA timezones. For multi-timezone countries, require a verified city or explicit timezone. Display the investigation timestamp in UTC, Beijing time, and buyer-local time. Calculate the next recommended buyer-local window and its exact Beijing equivalent. Check weekends and daylight saving. State `public holiday not checked` unless a current calendar was actually queried.

Preferred email window: buyer-local Tuesday–Thursday 08:30–10:30. This is a recommendation, not an automatic schedule.

## 9. Risk, suppression, and follow-up

The deliverability/contact score is a heuristic; never promise inbox delivery.

- 0–29: `LOW`
- 30–59: `REVISE`
- 60–79: `HIGH`
- 80–100: `BLOCK`

Always block inferred email in To, broker-only email, unidentified account, product mismatch, unsubscribe, explicit refusal, first-contact duplication within 72 hours, automatic batch send, sensitive personal data, spam-filter evasion, or sending without preview.

Do not default to a WhatsApp/social reminder 30–90 minutes after email. Recommend a second channel only when it is a current public professional route, relevant, legally appropriate, and manually approved. Never contact multiple unverified people simultaneously.

Follow-up limits: first contact plus at most three follow-ups, generally Day 3–5, Day 8–12, and Day 21–30. Use the original email thread. Stop all channels after refusal or unsubscribe.

## 10. Draft and send boundary

`CREATE_DRAFT` must create a visible UTF-8 Markdown `mailto:` link on every surface when the route is eligible. Leave To blank when no current verified address exists. When the mailto URL is too long, request an email draft connector instead.

Default to WeCom / Tencent Enterprise Mail compatibility through `mailto:`. Never label a draft as Gmail, Outlook, WeCom, or another provider and never expose a provider draft ID unless that exact connected provider returned a successful creation receipt in the current run. A generated `mailto:` URL is an open-draft action, not proof that a server-side draft was created.

Treat `render_outreach_action_card` as an optional native UI enhancement. Never preflight it and never interrupt research to report that it is unavailable. If it exists, call it after the complete result is ready. If it does not exist, silently render the same terminal state, primary Markdown `mailto:` link, and separate eligible-alternative links. Tool availability must not change the investigation or terminal state.

All connector mutations—create, edit, send, delete—require user confirmation under the connector’s policy. Never expose a direct-send shortcut that bypasses preview. `SEND_CONFIRMED` validates readiness; it does not silently send.

## 11. Output order

Return the complete intelligence dossier first. Then append the outreach execution section in this order:

1. exact recommended buyer-local and Guangzhou time, difference, DST, working-day and holiday-check status;
2. recipient priority, title as sourced, contact evidence/date/grade/current status/use;
3. exhaustive email-route ledger and omission check;
4. draft/mailto status;
5. To and subject;
6. customer-language message;
7. Chinese review translation;
8. separate eligible-alternative draft links;
9. optional WhatsApp/social message;
10. optional phone script;
11. first follow-up;
12. reply-handling order;
13. prohibited external information;
14. measurable objective and acceptance criteria.

Also return structured `outreach` JSON, including ledgers, gate, strategy, language, timezone, message, other channels, firewall, risk, quality, follow-up, and human-review state.

## 12. Acceptance rules

A message cannot be `READY` unless:

- relevance, clarity, credibility, buyer value, CTA, and compliance total at least 90;
- no firewall violation exists;
- exactly one clear CTA exists;
- exactly one core match and at most one value point appear;
- the first message passes the human-style gate and does not disclose the research process;
- buyer problems are not asserted beyond evidence;
- all seller capabilities used are verified and allowed externally;
- the recipient is current A1/A2, or To is intentionally blank for manual routing;
- every discovered email has a route classification and no address is silently omitted;
- eligible alternatives are separate sequential drafts, never a default multi-send;
- the five message questions are answered (missing any two forces `BLOCK`);
- no automatic send is possible.

Forward tests must include general mailbox, exhaustive multi-email routing, HR/historical/inferred separation, omission detection, non-procurement roles, broker/left-company contacts, incumbent supplier, no email, Beijing/buyer-local time, Philippines/Puerto Rico/Peru/DST, advertising/furniture/wall-system/industrial buyers, inferred specs, unverified seller capability, customs/supplier leakage, AI-style research disclosure, technical-questionnaire density, overlength subject/body, duplicate window, unsubscribe/refusal, no-preview send, long mailto, contact-language override, weekend, and holiday-not-checked behavior.
