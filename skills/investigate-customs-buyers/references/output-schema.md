# Buyer Intelligence Output Contract

The executable JSON Schema is `buyer-intelligence-schema.json`. This file explains how to interpret and present the result.

## Stable result envelope

Every run returns the same top-level sections, including on failure:

| Field | Required meaning |
|---|---|
| `status` | `complete`, `partial`, or `failed` |
| `mode` | `fast-scan` or `deep-dive` |
| `rules_version` | Rule-set version used for reproducibility |
| `input_snapshot` | Immutable raw input and SHA-256 |
| `record_identity` | Source, record date, bill and container identifiers |
| `normalized_shipment` | Supplier, buyer, product, quantity, route, and field scope |
| `data_quality` | Quality score, warnings, possible contamination, and scoring suspension |
| `entity_resolution` | Legal-entity match status, basis, confidence, and do-not-merge controls |
| `buyer_intelligence` | Buyer role, role confidence, product/trade observations, and escalation gate |
| `contacts` | Verified, associated, and unverified public business contacts |
| `contact_status` | Whether a usable company channel or verified procurement contact exists |
| `commercial_scoring` | Component scores, penalties, provisional range, and sales priority |
| `facts` | Supplied or independently confirmed factual claims |
| `inferences` | Transparent calculations and business inferences |
| `unknowns` | Missing or unresolved material fields |
| `recommended_actions` | Evidence-based next sales or verification actions |
| `exclusion_reason` | Why the record is excluded or deprioritized, otherwise `null` |
| `evidence` | Source objects and claim-level evidence |
| `errors` | Stage, stable code, safe message, retry count, and retryability |
| `completed_sections` | Stages that produced usable output |
| `missing_sections` | Stages that did not complete |

Do not remove empty required sections. Use `null`, empty arrays, and an `unknowns` entry where appropriate.

## Status rules

- `complete`: all required stages for the selected mode completed.
- `partial`: a useful record was parsed but a stage or requested Deep Dive enrichment failed.
- `failed`: the input could not produce a usable record.

Fast Scan is intentionally offline. Missing web enrichment in Fast Scan is not an error.

## Product classification

| Value | Interpretation |
|---|---|
| `EXACT` | Explicit target PVC foam board, Celuka/crust board, or expanded PVC sheet |
| `RELATED` | Adjacent material such as rigid PVC sheet or wall cladding |
| `INCIDENTAL` | Board appears only as part of a finished display, fixture, or other product |
| `NONE` | Clearly different product, including structural composite foam core |
| `UNKNOWN` | Description is missing, ambiguous, or internally conflicting |

Always include normalized category, confidence, reason codes, and matched features.

## Evidence model

Each material claim uses:

```json
{
  "claim_id": "claim-001",
  "claim": "The supplied row describes PVC foam board.",
  "classification": "supplied_fact",
  "evidence_grade": "D",
  "confidence": 0.97,
  "source_ids": ["customs-input"],
  "date_checked": "2026-07-30",
  "reason_codes": ["pvc_foam_board"]
}
```

Evidence grades:

- `A`: government, court/regulator, official filing, or first-party company source;
- `B`: official company social profile, attributable professional source, annual report, or reliable industry body;
- `C`: trade database, reputable directory, or other attributable third party;
- `D`: supplied record, calculation, or inference.

Grade each claim separately. Do not apply one source grade to the entire company.

## Entity output

Use `MATCHED`, `UNVERIFIED`, `NO_MATCH`, or `UNKNOWN`.

Possible affiliates without strong official linkage must retain:

```json
{
  "relationship": "unverified",
  "do_not_merge": true
}
```

Never transfer another entity's registry number, tax ID, website, contacts, shipment history, or legal record.

## Contact output

Contact verification:

- `VERIFIED`;
- `ASSOCIATED`;
- `UNVERIFIED`.

Email status:

- `OFFICIAL_COMPANY_EMAIL`;
- `VERIFIED_PERSONAL_BUSINESS_EMAIL`;
- `HISTORICAL_EMAIL`;
- `INFERRED_EMAIL`;
- `UNVERIFIED_EMAIL`.

Only the first two are usable for formal outreach. A company switchboard or general inbox is not a verified procurement decision-maker.

## Commercial score

Each component contains score, maximum, observation status, reason codes, and evidence references. The result also includes:

- `total_score`;
- `score_completeness`;
- `provisional`;
- `score_range`;
- `buyer_authenticity`;
- `product_fit`;
- `sales_priority`.

Unknown evidence produces a provisional range rather than automatic negative scoring. Severe record contamination suspends scoring and returns `UNSCORABLE`.

Configured grades:

| Minimum score | Grade |
|---:|---|
| 90 | A+ |
| 80 | A |
| 75 | A- |
| 68 | B+ |
| 60 | B |
| 40 | C |
| 0 | D |

This is sales priority, not a credit rating.

## Chinese report structure

Render a useful report even when JSON status is `partial` or `failed`:

1. Executive verdict.
2. Data quality and possible contamination.
3. Product, quantity, and route.
4. Entity, buyer role, and commercial score.
5. Verified contacts and contact gaps.
6. Facts, inferences, unknowns, and evidence boundaries.
7. Recommended next actions.
8. Errors and unfinished stages, when present.

Use `未显示/待完整数据核验` for unavailable record fields and `未找到已验证采购负责人` when no supported procurement contact exists.
