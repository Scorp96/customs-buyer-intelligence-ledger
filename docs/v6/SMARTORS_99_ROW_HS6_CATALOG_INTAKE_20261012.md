# Smartors 99-item machinery HS6 audit intake (not an official customs ruling)

## Source lineage / exact input
Supplied user workbook: `Smartors_机械产品_HS编码与海关获客审核_2026-10-12 (1).xlsx`, sheet `02_产品映射`, 99 non-empty product rows. Source workbook SHA-256:
`2ef050c15cc73b30df005dea6490c663fca9f1f2c33f4c9b4937fca5efb06f94`.

A separate controlled export, `Smartors_99项机械HS6候选_可导入检索种子_2026-10-12.json`, is generated from the 99-row sheet, **not a new verified factory catalogue**. Export SHA-256:
`0620f15d13ffec61a67b407ca48171fa78b30aa92762bb606d3542c0db029e2a`.

## Input schema (list of entries)
- `catalog_row_id`: `SMARTORS-20261012-0001` through `...0099` (immutable audit row identity)
- `catalog_group`, `catalog_page`, `product_name_chinese`, `product_name_english`
- `hs6_candidate`: string of **six decimal digits** or `null`. Exactly 85 non-null values, 14 pending function/engineering parameters.
- `candidate_confidence`: HIGH/MEDIUM/LOW/UNDETERMINED; **not a ruling**.
- `engineering_classification_conditions`: what has to be technically checked for classification.
- `search_aliases_english`: term list (max 10) derived from audited English description/keywords.
- `source_document_sha256`: original *audit workbook* SHA-256; this is not necessarily the manufacturer's official PDF hash.
- Optional notes are retained as data but not elevated to authoritative classifications.

## Use in an authorized clone (no production writes)
```sh
python scripts/validate_machinery_catalog_seeds_v64.py \
  --input-json /path/to/Smartors_99项机械HS6候选_可导入检索种子_2026-10-12.json \
  --expected-rows 99 --expected-coded 85 --target-country Indonesia --query-limit 50
```
The validator checks each ID, English/Chinese name, candidate code shape, audit file SHA format, mandatory technical classification reasons and uniqueness. It reports a **read-only** query plan with round-robin category coverage.

## Strong evidence separation
- WCO HS 2022 gives international *heading/subheading descriptions*, not a binding conclusion for this exact machine.
- Country-specific 8-10-digit tariff may depend on destination, latest tariff version and complete physical functionality. The input deliberately does not populate it.
- An exact machine identity requires itemised BOM, main operation, component boundaries, source manufacturer/model and technical evidence, not merely catalogue prose.
- No genuine customs transaction/IOR/Ultimate Buyer, procurement grade or contact route can be deduced from these query seeds.
- An import record of bottle caps, consumables, spare parts or unrelated mixing machines is **not** proof of buying the advertised machine.
- `SOAP_MACHINERY` remains a discovery taxonomy; SellerCapability remains UNCONFIGURED until model proof is bound.

## Test / release
- Synthetic tests reproduce 99 entries, 85 HS6 candidates and 14 pending, ensure no false 10-digit code or buyer certification.
- Fail closed on bad HS6, duplicate IDs, missing source hash or unsupported verification booleans.
- Initial query budget distributes across available catalogue categories rather than concentrating on the first group.
- Requires full exact-SHA CI on Win/Linux Py3.10/3.11 and separate runtime data ingestion acceptance. No production MCP file upload API is added here.

**Status:** offline intake + planning only; source JSON exists as a user-facing file, not yet a deployed product-source profile in CBI.
