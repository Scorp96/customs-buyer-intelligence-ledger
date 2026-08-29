# Strategic Decision and Controlled Learning Contract v4.2

## Contents

1. Purpose and architecture
2. Evidence states
3. Relationship resolution
4. Procurement decision center
5. Brand, exporter and manufacturer chain
6. Commercial value portfolio
7. Related-party pricing
8. Supplier lock-in
9. Development routes
10. Three-layer CRM decision
11. Controlled learning
12. Acceptance tests

## 1. Purpose and architecture

The plugin is a versioned instruction, schema, tool, and deterministic execution bundle. It does not reason independently of the host model. The host model supplies contextual judgment; the plugin supplies repeatable operations and hard safety boundaries.

The design goal is assisted intelligence, not an uncontrolled self-modifying agent:

`customs input -> deterministic evidence proposal -> full intelligence dossier -> model audit -> reviewed CRM -> separate outreach appendix`

Never allow contact availability, outreach state, message-length rules, or draft tooling to reduce the intelligence dossier. A buyer can be deeply researched while outreach remains blocked.

## 2. Evidence states

Use categorical states unless a calibrated model exists: `confirmed`, `strongly_supported`, `probable`, `unresolved`, and `rejected`.

Never substitute percentages such as 90% or 95% for missing evidence. A number is allowed only when its model, inputs, calibration dataset, thresholds, and limitations are documented.

## 3. Relationship resolution

Keep commercial relationship and legal relationship separate. Official cross-links, shared branding, phone, domain, address, personnel or supplier pattern may support a commercial relationship. They do not by themselves prove ownership, subsidiary status, or common control.

Legal confirmation requires a registry filing, ownership/director record, official legal disclosure, trademark ownership link, or equivalent authoritative evidence. Entity merge is prohibited before legal confirmation.

## 4. Procurement decision center

Record importing/customs entity, commercial operator, brand controller, procurement decision center, payment entity, inventory owner, and supplier-qualification owner separately.

For a strongly supported branch-like relationship, “probably headquarters” is an inference, never a fact. Verify it through current company material, job roles, supplier onboarding, tender/procurement documents, payment instructions, or direct confirmation.

## 5. Brand, exporter and manufacturer chain

Separate brand token, trademark owner, brand operator, exporter, manufacturer of record, OEM factory, certificate holder, and packaging label. A customs supplier is not automatically the manufacturer. A product description containing a brand does not prove ownership.

Image, QR, label, certificate, factory and trademark evidence should be queued for manual visual review when automated access is incomplete.

## 6. Commercial value portfolio

Never collapse independent-buyer value, local-channel value, headquarters-OEM value, and regional-market-entry value into one score. Each dimension has its own evidence, grade, rationale and acceptance criteria.

One shipment does not prove regular demand, warehouse capacity, a sales channel, a sole incumbent, or an A-grade opportunity. A categorical A-level decision requires verified identity, strong relevant demand evidence, product fit, and an actionable decision/contact route. Withhold or downgrade the grade while these inputs remain unresolved.

## 7. Related-party pricing

When commercial relatedness is confirmed or strongly supported, declared customs value is not an arm's-length market benchmark by default. Verify relationship, FOB/CIF scope, line allocation, weight scope, specification, density, grade, packaging, date and a current comparable quotation.

## 8. Supplier lock-in

Decompose lock-in into legal/control relationship, brand control, headquarters procurement, local inventory, exclusive packaging, internal settlement, technical/after-sales dependency, and price-only dependency. Do not assign a numerical lock-in percentage without a complete weighted and validated model.

## 9. Development routes

For independent buyers, validate the category owner and use an additional-source evaluation route.

For branch-like or controlled local entities, use `reverse_to_headquarters`: identify supply-chain ownership, verify manufacturer and OEM openness, compare evidence-backed capabilities, and request a controlled specification trial. Do not accuse the incumbent or assume a price/quality problem.

## 10. Three-layer CRM decision

`plugin_raw_output` preserves the plugin candidate. `assistant_audit` records accepted, modified, rejected, pending, new inference and commercial decisions. `final_crm` contains only explicitly reviewed eligible fields.

Strategic fields require an accepted decision and source identifiers before CRM export. Rejected or unsupported information cannot re-enter through summaries, derived scores, outreach copy or route fields.

## 11. Controlled learning

Feedback is append-only and deduplicated. Two repeated corrections may create a candidate rule, but a candidate has no effect. Promotion requires approval, at least three independent regression cases, precision at least 0.90, false-positive rate at most 0.05, and a bounded effect.

Allowed effects are research priority, manual-check priority, and ranking hints. Prohibited effects include identity merge, legal confirmation, contact verification, procurement authority, CRM acceptance, automatic outreach and sending.

The plugin never edits its own code and never changes model weights online. A validated improvement becomes a normal versioned release with rollback capability.

## 12. Acceptance tests

A release fails if name similarity merges entities; a commercial link becomes legal ownership without authoritative evidence; headquarters procurement is stated as fact from a branch pattern; brand owner, manufacturer or current decision-maker is invented; related-party value becomes a market benchmark; fake exact scores are published; an unreviewed/rejected field enters CRM; feedback changes facts/code/weights/sending; or a branch-like importer receives a direct replacement message before route verification.
