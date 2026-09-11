# CBI v6.5 Social + Global Radar Intake — Design Specification

**Date:** 2026-09-11
**Base:** `cbi-v6-cloud-runtime-20260901@1f920c2db63b1e17b4b12da8af73cbb1f1474b8c`
**Status:** Approved direction; isolated implementation branch only.

## Goal

Extend the current CBI v6.4 production lineage with one stable, evidence-preserving intake contract for candidates discovered by Social Buyer Intelligence (Instagram + TikTok) and the Global Keyword/Trend Radar. The intake must feed existing CBI research/validation rather than create a second scoring, route, WAL, CRM, or outreach system.

## Architectural invariants

1. CBI remains the final authority for Commercial Value, Research Confidence, Outreach Readiness and Decision Saturation.
2. Social/Radar may emit `B+`, `A-candidate`, or similar source-stage prioritization, but must never claim final CBI `A/A+` authority.
3. Direct facts and inferences stay separate. Every inference carries confidence and provenance.
4. All public contact routes discovered upstream are preserved; CBI may validate/enrich/prioritize them later.
5. The intake is append/evidence oriented. It must not directly write CRM or send outreach.
6. Existing v6.4 mutation/WAL semantics are not weakened or bypassed.
7. Cross-platform identity merges must be reversible and evidence-bound; name similarity alone is insufficient.
8. Production promotion remains gated by existing protected-branch CI and runtime acceptance.

## Intake bundle

Schema id: `cbi.social-radar-candidate.v1`.

Required top-level fields:

- `schema_version`
- `candidate_id`
- `observed_at`
- `source_stage`
- `canonical_identity`
- `profiles`
- `evidence`
- `inferences`
- `routes`
- `discovery`
- `source_score`
- `recommended_cbi_priority`

### `source_stage`

Allowed values:

- `SOCIAL`
- `GLOBAL_RADAR`
- `SOCIAL_AND_RADAR`

### `canonical_identity`

Carries normalized company/person identity hypotheses and explicit confidence. It is not legal-entity proof.

### `profiles`

Zero or more public source profiles. Initial platforms include:

- `INSTAGRAM`
- `TIKTOK`
- `WEB`
- `B2B`
- `INDUSTRY_MEDIA`
- `SEARCH_TREND`

### `evidence`

Direct observations only. Every row requires:

- `evidence_id`
- `evidence_type`
- `value`
- `source_url`
- `source_platform`
- `observed_at`
- `confidence`

### `inferences`

Derived interpretations only. Every row requires:

- `inference_id`
- `claim`
- `confidence`
- `basis_evidence_ids`
- `reason_code`

No inference may be promoted into `evidence` merely because it scores highly.

### `routes`

Preserve all discovered public business routes:

- email
- phone
- WhatsApp when explicitly public
- website
- platform profile/DM route
- named public business person route

Every route stores source, confidence, purpose and validation status.

### `discovery`

Carries how the candidate was found:

- market/country
- language
- keyword
- normalized semantic cluster
- source platform
- graph depth/path when social
- trend window when radar
- parent seed when applicable

### `source_score`

Explainable upstream score and components. This is advisory only.

## Global keyword/radar semantics

The Radar scheduler measures market-keyword-source combinations using:

- qualified-candidate yield
- B+ yield
- valid-route yield
- duplicate rate
- noise/reject rate
- block/error rate
- recency

Keyword families include product terms, generic terms, application terms, procurement-intent terms, local-language commercial vocabulary, and measured Rising/Related terms. Newly discovered expressions enter an observation pool first; they gain weight only after measured yield.

Instagram/TikTok vocabulary discoveries are valid Radar observations when source-bound and time-stamped.

## Intake validation states

- `ACCEPTED_FOR_RESEARCH`
- `REJECTED_SCHEMA`
- `REJECTED_NO_DIRECT_EVIDENCE`
- `REJECTED_IDENTITY_INSUFFICIENT`
- `DUPLICATE_CANDIDATE`
- `NEEDS_REVIEW`

Acceptance into research does not mean the buyer is commercially qualified.

## First implementation slice

1. JSON Schema for `cbi.social-radar-candidate.v1`.
2. Pure validator/normalizer with deterministic candidate fingerprint.
3. Tests for Instagram-only, TikTok-only, combined-social, Radar-only, and mixed Social+Radar bundles.
4. Negative tests proving inference cannot substitute for direct evidence and final `A/A+` cannot be asserted by the source bundle.
5. Adapter boundary returning a normalized bundle without any production mutation.

## Production boundary

The first slice is read/validate/normalize only. It does not add an MCP mutation, alter CRM, create outreach, or write production durable state. A later phase may map accepted bundles into the existing CBI Investigation/Evidence flow through existing guarded mutation semantics after isolated acceptance is GREEN.
