# CBI v6.4 machinery + HS candidate + customs-buyer evidence preflight

## Objective

Find **large and small potential machinery importers** without mistaking a broad HS match, a manufacturer, an agent, a freight forwarder, a bottle or spare-part consignment, or an unrelated customs record for a verified machinery purchaser.

The supplied SMARTORS HS workbook has 99 catalogue rows, 85 HS6 candidates and 14 items awaiting engineering specs. It does NOT establish a verified national ten-digit customs code, proven seller model specifications, or any real buyer transactions. Keep it separate from the durable customer/event store.

## Architecture (three independent evidence layers)

1. **Product authority**: exact model, primary mechanical function, delivery bill of materials, whether integrated line vs separate machines. WCO HS six-digit code is a hypothesis until classified. National tariff extension needs target country's official reference and version. Never concatenate a guessed eight/ten-digit code.
2. **Shipment/import authority**: customs record or bill of lading, exact date, B/L or shipment identifier, buyer legal entity and goods description that identifies an entire machine. Parts, consumables, packaging stock and similar-industry imports cannot be auto-promoted into complete machine purchases. A purchase order/invoice alone is not border-crossing evidence.
3. **Buyer and seller authority**: independently resolve BUYER vs IMPORTER_OF_RECORD vs CONSIGNEE vs FORWARDER/SUPPLIER and Ultimate Buyer; verify seller model capability separately from a product-discovery taxonomy. Phone/email/WhatsApp route verification never changes Commercial Value or proof of historical purchase.

## Safe preflight function

`unified_runtime.machinery_trade_evidence_v64.assess_machinery_trade_buyer` takes structured `hs`, `shipment`, `buyer` and `seller_capability` objects, and returns structured *claim completeness* and blockers without writes. The function **does not perform network verification**, so all evidence-complete cases are explicitly `CLAIMED_...REQUIRES_INDEPENDENT_SOURCE_CHECK`, not `VERIFIED`. The Runtime/Host must inspect actual source documents and bind immutable Claim/Evidence/Owner references before asserting actual purchasing status.

### Intake example (synthetic, not a real buyer)

```python
from unified_runtime.machinery_trade_evidence_v64 import assess_machinery_trade_buyer
result = assess_machinery_trade_buyer(
    hs={"hs6_candidate": "842230", "destination_country": "USA"},
    shipment={"source_type": "CUSTOMS", "source_locator": "https://example.test/fixture",
              "bill_of_lading": "SYNTHETIC-001", "shipment_date": "2026-08-18",
              "buyer_account_id": "SYNTHETIC-ACCOUNT",
              "goods_kind": "COMPLETE_MACHINE",
              "goods_description": "industrial filler",
              "machine_identity_status": "EXACT_MATCH",
              "machine_identity_locator": "https://example.test/fixture"},
    buyer={"canonical_account_id": "SYNTHETIC-ACCOUNT",
           "legal_entity_name": "Synthetic Example", "trade_role": "IMPORTER_OF_RECORD",
           "identity_evidence_locator": "https://example.test/entity"},
)
assert result["actual_import_independently_verified"] is False
```

## Discovery and qualification ordering

- **D1 / discovery**: widen from candidate six-digit codes, multilingual machine aliases, application and relevant countries; retain firms with industrial need even without direct imports. Record which website/registry/industry source produced each prospect.
- **D2 / product relevance**: check machine vs parts/consumables; reject supplier, freight or unrelated business from the *verified buyer* class without discarding their relation to the supply graph.
- **D3 / border-crossing evidence**: independently verify customs/BOL source, date, unique identifiers, legal importing party and product identity. Preserve uncertainty when databases mirror a shipment.
- **D4 / real buying group**: differentiate IOR, consignee, actual owner/end user and procurement authority; separately find company and named personal routes.
- **Value / buyer segmentation**: never infer annual spend from one shipment. Repeat frequency, capacity, destinations and supplier patterns can justify A+/A/B+ only when evidence-bound; lack of WhatsApp is not evidence of low commercial value.

## Release and failure conditions

- This module is a standalone **preflight utility**, not yet wired to public Runtime MCP, live portfolio scoring or automatic importer discovery.
- Must add an integration-level check against actual immutable Runtime observations before producing `VERIFIED_MACHINE_BUYER` or adding any product opportunity.
- All 16 pure-function tests must pass on Python 3.10/3.11 for Windows and Linux; do not merge without production required CI.
- Missing HS8/HS10, incomplete model specs, blocked paywalls, inferred WhatsApp numbers and user-supplied unverified claims remain UNKNOWN. No automatic sales outreach/CRM writes or SellerCapability claiming.
- Positive source evidence must be rechecked against the target company; fail/stop on mismatch, duplicate B/L or ambiguous Ultimate Buyer.

## Evidence standard

Primary: WCO HS nomenclature (for six-digit headings), target-country customs authorities (for national subheadings), original shipment/BOL and official corporate registry/website. Secondary indexes may be discovery hints, with freshness/paywall/document boundaries. **No independent source verification occurs inside this module**.
