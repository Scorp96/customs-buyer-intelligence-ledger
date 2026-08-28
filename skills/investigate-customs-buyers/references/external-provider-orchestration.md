# External Provider Orchestration

Use this reference only when an investigation explicitly enables connected data providers. The default is `PUBLIC_ONLY`.

## What this plugin can and cannot reproduce

It can reproduce the workflow layer: provider discovery, capability planning, exact tool selection, normalized receipts, Owner and Evidence binding, deduplication, freshness/conflict handling, Pivot generation, cost/permission gates, CRM safety and fail-closed Closure.

It cannot reproduce or redistribute Apollo.io, ZoomInfo, Lusha, Demandbase, Maersk or any other provider's proprietary database, scoring model, real-time service, authentication or licensed API. Those capabilities exist only when the corresponding provider plugin or API is actually installed, connected, authorized and available to the current task.

The Runtime does not call another plugin. Codex performs cross-plugin orchestration:

1. Inspect the tools actually visible in the current task. Do not infer installation from a screenshot, catalog entry or prior task.
2. Start the investigation with one provider mode and an explicit allowlist.
3. Call `plan_provider_calls` with only visible provider tools and their actual connection state.
4. Execute each returned provider tool at the Codex layer.
5. Normalize the real result and call `append_provider_receipt` once per tool call.
6. Treat every new alias, person, address, domain, phone, supplier or company as a Pivot that must be consumed later.
7. Continue the complete public Source Profile and six-branch network route. A provider result never marks a public Source Family complete.

## Modes

- `PUBLIC_ONLY`: default. Provider planning returns `PROVIDER_USE_DISABLED`.
- `CONNECTED_PROVIDERS_OPTIONAL`: use only explicitly allowed, already connected providers. Missing or blocked providers are reported but do not by themselves prevent public-source Closure.
- `CONNECTED_PROVIDERS_REQUIRED`: every declared required capability needs a successful Positive or Negative provider receipt. Permission, connection or credit blocks yield an incomplete status.

Paid-credit authorization must be present both in the investigation's immutable provider policy and in the individual plan request. This prevents a later step from silently expanding cost authority.

## Provider classes

- `CONTACT_ENRICHMENT`: account, company, person, role, email or phone enrichment.
- `ABM_INTENT`: Buying Group, account intent and enterprise signal enrichment.
- `GTM_ORCHESTRATION`: CRM context, GTM workflow and account-research aggregation.
- `LOGISTICS_TRACKING`: container, booking, port, node and transit facts.
- `TRADE_DATA_INFRA`: trade flow, customs, entity and source-lineage data.

These classes describe data boundaries, not provider ownership. For example, logistics facts cannot become decision-maker Evidence, and a contact-enrichment match cannot prove customs continuity or Ultimate Buyer by itself.

## Provider inventory input

Each inventory row must contain:

```json
{
  "provider": "Provider display name",
  "provider_class": "CONTACT_ENRICHMENT",
  "status": "CONNECTED",
  "capability_tools": {
    "decision_maker_search": "exact_visible_tool_name",
    "email_enrichment": "exact_visible_tool_name"
  },
  "requires_paid_credit": false,
  "permissions": ["read company data", "read contact data"]
}
```

Valid availability values are `NOT_INSTALLED`, `INSTALLED_NOT_CONNECTED`, `CONNECTED`, `PERMISSION_BLOCKED`, `CREDIT_BLOCKED`, and `UNAVAILABLE`. Do not label a tool `CONNECTED` unless it is visible and its connection is confirmed in the current task.

## Provider receipt requirements

`append_provider_receipt` accepts only a result bound to an unexpired `plan_id` and exact `planned_call_id`. Preserve:

- provider receipt ID, investigation and Account;
- provider class, requested capability and target module;
- exact provider, tool name and actual tool-call/execution ID;
- exact query, start/completion times, result and count;
- raw result URL, snapshot or `provider-receipt://` locator plus SHA-256;
- same-Owner Evidence IDs and Evidence objects;
- returned contact and company objects;
- generated and consumed Pivots;
- permissions, billing/credit notice, freshness, conflicts and blocked reason.

A Positive result requires Evidence. A Negative result requires a real empty-result receipt. Permission, connection, regional or credit failures are `BLOCKED`, never Negative or N/A.

## Contact safety

A returned contact may be stored as a lead while remaining `route_eligible: false`. Route eligibility requires all of the following:

- the contact belongs to the investigated Account;
- the provider marks it verified;
- it is not masked, reconstructed or guessed;
- it has same-receipt Evidence;
- email or international phone syntax is valid;
- WhatsApp or Zalo has explicit channel proof and a matching Evidence claim.

Supplier, logistics, carrier, consultant, marketplace and unrelated contacts never become Buyer Direct. Conflicting provider/public values remain separate until the evidence-conflict module resolves them.

## Cost, permissions and privacy

Do not install a provider, start OAuth, widen permissions, accept a trial, consume credits or purchase a subscription as an implied step. Ask for explicit authorization for that distinct external action. Keep only task-relevant normalized facts and receipts; do not bulk-copy a provider's database or bypass its terms, rate limits or access controls.

No provider tool may send outreach through this plugin. All outreach remains Closure-bound, draft-only and human-reviewed.
