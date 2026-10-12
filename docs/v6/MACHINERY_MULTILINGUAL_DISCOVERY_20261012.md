# Machinery HS buyer discovery: localized query pack v2

**Status:** proposal in a draft PR. It is not an HS code ruling or a confirmed importer list.

## Reproduced gap

Production `plan_candidate_expansion({product_profile_id:"SOAP_MACHINERY",geography:"Indonesia"})` generated English/internal `SOAP_MACHINERY` queries without Indonesian terms because no locale was supplied. The existing v1 locale packs covered PVC/WPC etc. but did not include machine terms and had no id-ID pack.

## What changes

- Curated v2 products/applications/archetypes for machinery in Indonesian (id-ID), Vietnamese (vi-VN), Spanish for Mexico (es-MX) and Portuguese for Brazil (pt-BR).
- The machinery query planner chooses the locale conservatively only for **exact** known country names (Indonesia, Vietnam, Mexico, Brazil), never for unspecified neighboring countries or unrelated PVC/WPC profiles.
- An explicit caller-supplied locale overrides inference; `auto_market_locale=false` disables it.
- Within a limited query budget, round-robin native/local and English/commercial query bases so the first 2–8 queries don't silently drop either language.
- Legacy PVC/WPC auto behavior is intentionally unchanged; local terms remain planning seeds, not proof of buyer identity, actual purchase, HS classification, WhatsApp or production capacity.
- Source-task planner still yields tasks requiring independent public execution receipts, and receives no new ability to send outreach.

## Public language sources reviewed, not client proof

- Indonesia: https://www.fabrikasi.co.id/mesin-filling/ , https://gemindo.co.id/product/filling-machine/mesin-pengisi-cairan-otomatis-minyak-goreng-sabun-cair-pestisida-kecap-dll/ , https://marui.co.id/proses-pembuatan-skincare-dari-riset-hingga-produk-jadi/
- Vietnam: https://gmpgroups.com.vn/thiet-bi-san-xuat/day-chuyen-san-xuat-my-pham/ , https://ilab.com.vn/product-category/yekeey/
- Mexico Spanish: https://forzaprocessequipment.com/es/ , https://kosmixpro.com/es/industrias/
- Brazil Portuguese: https://www.honemachine.com/pt/products.html , https://www.maxwellmixing.com/pt/p-vacuum-emulsifying-mixer-machine-by-maxwell-2.html

These are **terminology observations** from public product information. They are not evidence that those companies bought SMARTORS machines.

## Acceptance criteria

1. Win/Linux × Py 3.10/3.11 required CI + backup/WAL regression pass on exact Git SHA.
2. `SOAP_MACHINERY` Indonesian query first page includes both Indonesian and generic machine phrases without executing a network request.
3. Vietnamese, Spanish and Portuguese variants match native diacritics; no duplicated queries.
4. Unknown countries fail to English-only rather than invent a locale; no uncontrolled expansion to all global locales.
5. PVC/WPC plans retain existing local behavior. Source-task call IDs, budgets, pagination and six-group fairness remain reproducible.
6. On **real** customs and company-source blind review, measure candidate recall and machine-vs-parts false positives before expanding to other countries. No claims of customer yield yet.

## Remaining gaps

- Target-country national HS 8–10 digit code confirmation and actual machine specifications are still independent tasks.
- Not all Smartors catalogue products are mapped by this pack; `SOAP_MACHINERY` covers only selected machine subfamilies.
- No scheduled recurring Google Trends watch or global 3-hour job is added here.
