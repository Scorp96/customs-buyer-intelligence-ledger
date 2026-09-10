---
name: customs-buyer-one-shot
description: "Use this skill whenever the user supplies a customs/import/export/shipment record, asks whether a customs company is a real buyer, asks for buyer intelligence plus 裂变/network expansion, or asks to investigate a customs buyer completely. Run the buyer investigation as one cloud/Host job and return one complete dossier: historical shipment backfill and dedupe, buyer/IOR/Ultimate Buyer resolution, product and supplier analysis, company profile, Buying Group and contact routes, all six network-fission branches with validation of promoted peers, commercial/confidence/readiness conclusions, outreach drafts, and—when the user wants ongoing updates—a cloud new-customs-record monitor. Do not require the user's Windows PC, local CLI, CMD, PowerShell, Python, Git checkout or local MCP for the normal user path."
---

# Customs Buyer Intelligence — ONE-SHOT CUSTOMS route

## Trigger and precedence

This skill takes precedence over the generic `ANSWER_FIRST` buyer/contact lookup route when any of the following is true:

- the user supplies a customs, import, export, B/L, shipment, consignee, supplier or trade-data row;
- the user asks `这个企业是真实买家吗`, `裂变`, `深度调查`, `穷尽搜索`, `完整调查`, `全部信息`, `海关历史`, or equivalent;
- the task is to qualify a customs-derived Buyer or build peers from a customs/supplier/product network;
- the user expects the whole buyer investigation rather than one narrow contact lookup.

A customs Buyer task is **not** complete after answering only whether the company is real, listing a few shipments, finding one contact, or naming a few peers. Finish the complete investigation below and send **one consolidated final answer**. Do not make the user repeatedly say `继续` merely to reach later modules.

## Normal execution location: cloud/Host, never the user's PC

Normal use is Host/cloud execution:

```text
user customs row
  -> Host public research
  -> one-shot buyer analysis
  -> complete dossier
  -> optional cloud delta monitor
```

Git is source/version control, not the research engine. Local CLI, `.mcp.json`, Windows Runtime, CMD, PowerShell and Python are engineering/acceptance/recovery surfaces only.

For the normal user path:

- do **not** ask the user to open a computer;
- do **not** send a ZIP/CMD/PowerShell package as a prerequisite;
- do **not** require a local Git checkout;
- do **not** require the user to start an MCP process;
- do **not** block public research merely because the CBI Runtime/MCP namespace is not exposed in the current Host session.

If CBI Runtime tools are exposed, use them for durable Evidence/Claim/Pivot/Peer/Closure governance when the user requested persistence or formal audit. If they are not exposed, continue the complete one-shot investigation with the Host's real web/search/browser/registry/maps tools and clearly label the result as Host/stateless research. Runtime unavailability is **not** permission to fall back to the user's PC.

## One-shot investigation contract

Treat the user's customs row as `USER_SUPPLIED_UNVERIFIED` evidence to verify. Preserve exact identifiers and distinguish shipment date, arrival date and indexed/update date.

Complete all of the following before the final answer, subject only to truthful source/tool limits.

### 1. Shipment integrity and historical customs backfill

Search both Buyer-side and supplier-side representations and applicable trade indexes. Recover as much historical shipment activity as public sources permit.

Deduplicate by the strongest available combination of:

- Master B/L;
- House B/L;
- container;
- shipment/arrival date;
- buyer/consignee/notify party;
- supplier/shipper;
- commodity/product;
- quantity and weight;
- origin/destination ports.

Do not count mirrored database representations as separate shipments. Report material gaps, paywalls and date-index limitations.

### 2. Real-Buyer / entity resolution

Resolve and keep distinct:

- legal entity;
- commercial operator;
- Importer of Record;
- consignee;
- notify party;
- Ultimate Buyer;
- brand controller;
- inventory owner;
- payment/procurement entity;
- trading intermediary;
- declared manufacturer versus probable actual manufacturer.

Answer explicitly whether the target is:

- verified active importer/buyer;
- likely channel/distributor/trader;
- terminal end user;
- IOR/logistics-only candidate;
- unresolved.

Never infer warehouse ownership, factory ownership, terminal use or buyer authority from an address or one shipment alone.

### 3. Product and demand structure

Separate product families and quantify only what the source supports. For PVC/WPC/building-material work, distinguish at minimum:

- PVC Foam Sheet / Board;
- PVC rigid/hard board;
- WPC products;
- fence/railing/decking;
- acrylic/other plastic sheet;
- unrelated commodities.

Assess recency, repeat pattern, shipment size, supplier continuity, supplier diversity, port pattern and visible volume. A single shipment never proves repeat demand or annual volume.

### 4. Company profile

Search official/current sources for:

- registration/status;
- operating brand;
- website/domain;
- business model;
- locations;
- warehouse/store/channel evidence;
- product catalogue;
- social/company pages;
- affiliated entities.

Mark unsupported attributes `UNKNOWN` rather than filling them from generic directories.

### 5. Buying Group and Buyer-owned routes

Search Owner, Founder, President, CEO, Purchasing, Procurement, Sourcing, Import, Operations, Supply Chain, Sales and General Routing as applicable.

For each person/route preserve:

- name;
- role;
- relationship to Account;
- source;
- freshness;
- email/phone/channel ownership.

Phone does not equal WhatsApp/Zalo unless the source proves that channel. Supplier/logistics/third-party contacts are not Buyer-owned routes.

### 6. Supplier and competitive structure

Map incumbent suppliers, supplier continuity, alternative suppliers, probable factories where independently supported, and notable product/sourcing changes.

Do not describe a trading exporter as the actual manufacturer without evidence.

### 7. Mandatory six-branch network fission

Run all six branches for the target and for every materially promoted Anchor:

1. `regional_peer` — regional peers;
2. `industry_peer` — industry/application peers;
3. `scale_peer` — similar-scale buyers;
4. `same_supplier_buyer` — real buyers sharing suppliers;
5. `same_product_hs_application_buyer` — same product/HS/application buyers;
6. `competing_supplier_alternative` — competing/alternative supplier network.

Do not stop at a raw name list. Validate the highest-value discovered peers with real evidence for identity, buyer role, relevant product/trade activity and commercial fit. Explicitly distinguish:

- `DISCOVERED`;
- `VALIDATED_BUYER`;
- `ANCHOR_CANDIDATE`;
- `HIGH_PRIORITY_TARGET`;
- `NOT_QUALIFIED`;
- `UNKNOWN/BLOCKED`.

A supplier's customer-list association by itself is discovery evidence, not sufficient proof of a high-value buyer.

### 8. Evidence conflicts and boundaries

Separate in the final reasoning:

- `FACT`;
- `INFERENCE`;
- `HYPOTHESIS`;
- `RECOMMENDATION`;
- `UNKNOWN`.

Preserve conflicting addresses, names, dates, roles and shipment representations until reconciled. Paywall, login wall, 403, captcha or dynamic-page failure is `BLOCKED`, not negative proof.

### 9. Commercial conclusions

Return these dimensions independently:

- `Commercial Value`: A+ / A / A- / B+ / B / B- / C / D / NQ;
- `Research Confidence`: use the Runtime scale when available, otherwise give a clearly labeled qualitative confidence level;
- `Outreach Readiness`: buyer-owned route readiness only;
- `Buyer Role`: importer/distributor/trader/end user/IOR candidate/etc.;
- `Product Fit`;
- `Key Unknowns`.

Contact gaps never reduce Commercial Value by themselves.

### 10. One consolidated dossier

The user should receive the result **once**, after the above work has been attempted. Use a compact but complete structure:

1. Executive conclusion — real buyer or not, role, grade and why;
2. Entity/company profile;
3. Historical customs summary and key shipment table;
4. Product/demand analysis;
5. Supplier/competitive structure;
6. Buying Group and verified contacts/routes;
7. Six-branch fission table with validated priority peers;
8. FACT / INFERENCE / UNKNOWN / risks;
9. Commercial Value / Confidence / Outreach Readiness;
10. recommended development angle;
11. tailored 80–110 English-word development email;
12. tailored instant-chat draft;
13. monitoring state when applicable.

Do not reveal internal chain-of-thought. Give concise evidence-based rationale and source citations/links.

## Cloud customs delta monitoring

When the user asks to monitor, track, watch for new customs data, says `旧数据做完历史，搜索到新数据发给我`, or otherwise clearly wants ongoing updates:

1. first finish historical backfill and dedupe;
2. establish a baseline containing the known shipment fingerprints and latest indexed state/date/count when available;
3. use the Host's cloud scheduling/automation capability when available;
4. search at a cadence appropriate to source update speed;
5. compare each run against the baseline;
6. notify only for a genuinely new shipment or a material correction to an existing shipment;
7. update the baseline conceptually with every notified record so the same shipment is not announced twice;
8. if nothing new is found, do not send a notification.

A new record should include, when available:

- shipment/arrival date;
- buyer role;
- supplier;
- product;
- quantity/weight;
- origin/destination ports;
- Master/House B/L;
- container;
- source;
- whether it changes Commercial Value, product fit or supplier strategy.

Cloud monitoring must not require the user's computer to remain online.

## Runtime and persistence boundary

This one-shot route controls **research completeness**, not automatic persistence.

Without an explicit persistence/CRM instruction:

- do not write CRM;
- do not send outreach;
- do not generate executable send links;
- do not claim Runtime Closure if Runtime tools were unavailable;
- do not fabricate Evidence IDs, Pivot IDs, Peer receipts or Closure tokens.

If the user explicitly requests formal `FULL_AUDIT`, CRM writeback, Closure or outreach preparation and Runtime tools are exposed, hand the verified Host findings into the existing v6.1 persistent route. The Host still performs actual public research; Runtime governs durable evidence and decisions.

## Stop conditions

Do not stop merely because:

- one positive shipment was found;
- the company is confirmed real;
- one decision maker was found;
- one supplier network was found;
- a high commercial grade appears likely;
- a fixed number of queries/pages/peers was reached.

Stop the one-shot investigation only when the material modules above have been attempted and remaining high-value questions are either resolved, explicitly `UNKNOWN/BLOCKED`, or cannot be pursued with the tools/sources available in the current Host session.

Then deliver the complete dossier once.