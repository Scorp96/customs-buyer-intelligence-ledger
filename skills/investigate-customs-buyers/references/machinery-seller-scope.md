# Machinery seller identity and FULL_AUDIT acceptance gate

## Source and name boundaries

- Buyer discovery family: `SOAP_MACHINERY` (version-pinned discovery taxonomy; NOT a seller capability assertion).
- Current seller brand: SMARTORS. The Chinese website identifies 广州骏烁机械设备有限公司; company footer says Guangzhou Smartors Machinery Co., Ltd.; About Us separately says Guangzhou Junshuo Machinery Equipment Co., Ltd. Resolve these as brand/English aliases, not independently verified registered legal names until supported by a registry or user-authorized business certificate.
- Official evidence: https://www.gzsmartors.com/ ; https://www.gzsmartors.com/col.jsp?id=120 ; https://www.gzsmartors.com/nd.jsp?fromMid=780&id=8 .
- Officially marketed product families include vacuum homogenizing emulsifiers, high-shear liquid-washing mixers, RO water treatment, and liquid/paste/powder filling systems. Nothing here proves an entire solid-soap plodder/bar production line.
- `SOAP_MACHINERY` is a discovery taxonomy for investigating soap/detergent buyers, not a guarantee any seller has every machine its buyers use. Its variants cover those supported marketing categories, not invented equipment specs.

## Required before declaring technical fit

1. Verified current seller legal/brand identity and traceable model-level product listing.
2. Verified buyer need for a **specific** machine: process or product, throughput/batch volume, viscosity/product behavior, automation, power/utility requirements, packaging formats if relevant, sanitary/material constraints, shipping/installation and service constraints.
3. The exact seller model and its specification sheet/test record match buyer-required parameters. Record deviations and quotations separately.
4. Independent procurement demand evidence (purchase order, tender, dated buyer request or confirmed project); parts import alone is not a new-line purchase.
5. Only a dedicated machinery capability matcher with model-level verified fields may report `SUPPORTED`. The historical sheet matcher must return `NEEDS_VERIFICATION` for `SOAP_MACHINERY`; an unbound seller profile must return `UNCONFIGURED`.
6. Geographic buyer identity, Importer of Record, consignee, end-user facility and affiliates are separate. The origin of imported equipment is not the buyer's company country.

## Six-branch and preflight evidence

Preflight in sequence: legal entity/industry; Maps business; official site; company social and leaders; each decision-maker's current role plus verifiable personal routes. Then Customs, Ultimate Buyer, trade continuity, technical need, and branches:
`regional_peer`, `industry_peer`, `scale_peer`, `same_supplier_buyer`, `same_product_hs_application_buyer`, `competing_supplier_alternative`.
Save the executed source family, URL, retrieval outcome, subject, directness, time and evidence hash; a planning result is never an execution receipt. Failed website access (403/429/timeout/login) is `BLOCKED`, never no-data or negative proof.

## Research window and closure

The 28-minute research floor is a host research policy, NOT presently an attested server-side active-duration measurement. Do not claim it has passed merely because a session or workflow ran for 28 wall-clock minutes, or because multiple passive calls succeeded. Without trustworthy dated active acquisition evidence, an honest `INTERRUPTED` handoff is required; a terminal Decision Saturation status does not override this policy. Retain the exact investigation ID, last_safe_seq, evidence cluster IDs, unresolved critical claims and best next objective. Never auto-send outreach or auto-write CRM.

## Release and production verification

- New machine profile is registered and produces search/branch plans without PVC terms.
- An unbound seller profile remains UNCONFIGURED; a contrived `VERIFIED` seller profile cannot sneak through the sheet technical matcher as SUPPORTED.
- Legacy PVC/WPC profile content pins remain unchanged; WAL and backup regression pass.
- PR CI passes Linux+Windows on supported Python versions.
- One named production business investigation is resumed idempotently and acquires real source/peer evidence, not just a plan; validate accurate route ownership, no fabrications, and no spurious closure.
- Production release is NOT equivalent to FULL_AUDIT end-to-end acceptance. Roll back or block release on any evidence/authority/safety regression.
