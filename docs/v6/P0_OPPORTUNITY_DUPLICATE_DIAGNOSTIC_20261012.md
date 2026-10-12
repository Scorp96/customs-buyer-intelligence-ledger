# P0 — duplicate v6.3 Product Opportunity create-event diagnostic (2026-10-12)

## Observed production failure

- Read-only `get_portfolio_metrics({})` failed with `V63_DUPLICATE_PRODUCT_OPPORTUNITY_CREATE_EVENT`.
- A targeted `get_product_opportunities` and `get_expansion_state` for the affected investigation also failed.
- `get_investigation_health` returned an accessible 28-event chain; this does **not** prove that the duplicate events' semantic contents are valid.
- Current writer `ExistingProductionStoreBackend.create_product_opportunity` already implements request-hash and CAS guards. The production duplicate may predate these checks, but timing/root cause are **not verified**.

## What is implemented in this PR

- `diagnose_opportunity_create_events(events)` is a pure, read-only diagnostic.
- Every create event is revalidated using the existing proof/hash/profile-pin projector gates.
- Only duplicates with identical correlation ID, WAL request hash, verified snapshot hash and content, investigation, owner and product profile are **candidate exact replays**. This is **not** independent proof of idempotent execution.
- Duplicates from different correlations, distinct snapshots, different investigations/accounts/products, or malformed proof are blocked as conflicts or invalid.
- Output defaults to hashed opportunity identities and omits private correlation, account, profile and session identifiers; optional private fields are intended only for an authorized local reviewer.
- The existing production projector remains fail-closed. No silent dedup, WAL rewrite, metric adjustment, customer write or contact outreach is introduced.

## Operator run (only on authorized isolated export)

1. Freeze the impacted investigation's append-only snapshot in an **isolated read-only** location using an already authorized operator export path. Independently record the source's `last_safe_seq`, `last_safe_event_hash`, snapshot generation and SHA-256.
2. Export only normalized `V63_PRODUCT_OPPORTUNITY_CREATED` and any relevant promotion events to a private local JSON array (as produced by `_normalize_v63_opportunity_event` on the isolated copy). Do **not** place private rows in GitHub issues or public CI artifacts.
3. Run from an exact-SHA checkout:

   ```sh
   python scripts/audit_v63_duplicate_creates.py --normalized-events-json /path/to/private/isolated-v63-events.json
   ```

4. Preserve a private receipt: Git SHA, input-file SHA-256, source event count and tail hash, output status/count, duplicate record sequence numbers, correlation IDs, request-hash and result-snapshot hash comparisons, plus independent immutable WAL correlation evidence.
5. Review write-side request identities, timestamp/order and producer version to determine whether the guard existed when duplicate creates were appended.

## Release gates / stop conditions

- `NO_DUPLICATE_CREATE_EVENTS`: this dataset has no duplicate; investigate wrong snapshot or wrong scope, **not** 'production repaired'.
- `REPLAY_CANDIDATES_NEED_INDEPENDENT_WAL_PROOF`: **STOP** until append-only chain plus WAL correlation and request/result receipts independently verify each replay.
- `CONFLICT` / `INVALID_EVENT_PROOF`: **STOP**; do not coalesce or force production metrics.
- Only after proof may a separately reviewed read-side strategy be proposed and tested with exact legacy fixtures, concurrent writers, promotions, scoping and regression gates. Do not change the event chain.
- Production acceptance also requires exact SHA CI on Windows/Linux Python 3.10/3.11, a current isolated backup restore, Render deploy identity, post-deploy MCP health plus full metrics and customer-independent blind-review samples.

**Status:** a diagnostic/test delivery, **not** a production incident repair.
