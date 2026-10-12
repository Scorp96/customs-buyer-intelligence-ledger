# CBI v6.4 — server-gated P0 duplicate-create diagnosis

## Why another diagnostic is required

2026-10-12 production reads `get_portfolio_metrics` and the affected investigation's opportunity read model fail on `V63_DUPLICATE_PRODUCT_OPPORTUNITY_CREATE_EVENT`. The exact private session export tool responded `authoritative single-session export is disabled`. This must not be bypassed. Existing read-only offline diagnostic cannot be used on the actual source without an authorized isolated file.

The opt-in MCP tool `inspect_opportunity_projection_integrity` offers a narrower **sanitized** diagnostic, using the already authenticated, bound SessionStore in memory. It never returns raw events, client IDs, account names, payloads, snapshot bodies or correlation values. It is **disabled by default** and not a repair.

## Controlled operator acceptance

1. First independently confirm the active Render tenant, authenticated MCP route, Git SHA and service ID. Ensure no split-brain alternate CBI runtime is selected.
2. Obtain the exact investigation's current `last_safe_seq` and `last_safe_event_hash` from `get_investigation_health`. Do not use stale evidence from another session or another timestamp.
3. Only during a short approved operator window, configure three SERVER-SIDE settings together:
   - `CBI_V64_OPERATOR_PROJECTION_DIAGNOSTIC_ENABLED=1`;
   - `CBI_V64_OPERATOR_DIAG_SESSION_SHA256` = the lowercase SHA-256 of the **one** authorized canonical investigation ID (not the raw ID);
   - `CBI_V64_OPERATOR_DIAG_EXPIRES_AT` = RFC3339 UTC time no more than **15 minutes ahead**.
   Missing, mismatched, expired, timezone-free, or excessively long windows fail before a SessionStore read. A client-provided acknowledgement is *not* a substitute for operator authorization. Do not set this in the ordinary ChatGPT tool request.
4. Call the new read-only tool with **only** these fields:
   - `investigation_id` (exact canonical)
   - `expected_last_safe_seq` (positive integer)
   - `expected_last_safe_event_hash` (exact 64-character SHA-256)
   - `acknowledge_private_state=true`
5. Receipt: duplicate counts, classification (same-correlation replay candidate vs distinct-correlation conflict), source event count, and exact-tail match. No original event positions, unredacted WAL, Account IDs, or correlation identity data.
6. Disable the server flag when the operator window ends. Never expose this tool to a public unauthenticated MCP endpoint.

## Non-negotiable boundaries

- `safe_to_autorepair` is always `false`; no collapsing snapshots, recalculating production metrics, or removing events.
- `authoritative_wal_independently_reconciled` is always `false` until a separate exact WAL correlation proof is obtained.
- A raw session's private root must not be exposed over MCP, GitHub or CI.
- A create replay candidate is only a hypothesis until independently proven by existing WAL, request hash, correlation and durable exact-result snapshot.
- Any mismatch of session ID, seq/hash, a concurrent tail change, missing authorization, or model/profile snapshot validation failure means **stop**.
- The feature is server-disabled by default and not part of ordinary customer research/lead discovery.

## Release gate

- Full branch SHA regression on Windows/Linux + Python 3.10/3.11, including import/registration and server authorization boundaries.
- Stage on an isolated instance with *synthetic* SessionStore before live enablement.
- Explicit expiry/revocation mechanism and a hardened role/tenant authorization must be verified at the transport level before any production flag enablement.
- Independent restored backup/recovery fingerprint and true event/WAL binding are still required.
- Only then decide whether a separate reviewed read-side repair is safe. A 'READY' server status or aggregate metrics alone is never acceptance.

**Status: Code candidate; not activated or deployed on production.**
