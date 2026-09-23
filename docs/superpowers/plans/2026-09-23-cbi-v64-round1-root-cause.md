# CBI v6.4 Render — Round 1 Root Cause Record

Date: 2026-09-23
Scope: Round 1 only — source tracing, isolated regression reproductions, and patch plan.
Repository: `C:\Users\scorp\plugins\customs-buyer-intelligence`
Isolated worktree: `C:\Users\scorp\Documents\Codex\2026-08-21\worktrees\fix-cbi-v64-opportunity-security-runtime-hardening-20260923`

## Required Round 1 fields

```text
ROUND_1_VERDICT: PASS_TO_PATCH

BASE_SHA: 11db255b23a4783b4aa99182518886abee2a8306

BRANCH: fix/cbi-v64-opportunity-security-runtime-hardening-20260923

FILES_INVOLVED:
- mcp/server_v61.py
- unified_runtime/demand_expansion.py
- unified_runtime/v63_projection.py
- unified_runtime/production_integration_bindings_v63.py
- unified_runtime/existing_production_store_backend_v63.py
- mcp/crawler_tool_v64.py
- unified_runtime/crawler_execution_bridge.py
- unified_runtime/browser_escalation.py
- unified_runtime/mcp_schema_v63.py
- unified_runtime/recursive_expansion.py
- unified_runtime/expansion_planner.py
- unified_runtime/source_execution.py
- unified_runtime/core.py
- unified_runtime/v6.py
- tests/test_v64_round1_regressions.py

ROOT_CAUSE_PRODUCT_OPPORTUNITY: CONFIRMED in source and isolated reproduction; exact production duplicate count remains unknown.

DUPLICATE_EVENT_COUNT: UNKNOWN in production. Synthetic regression fixtures contain two create events for the repeated ID.

DUPLICATE_EVENT_SEQS: UNKNOWN. The available sanitized WAL/runtime output contains no durable event sequence or event hashes.

WAL_CORRELATION: One sanitized create_product_opportunity COMMITTED_ERROR row had request_sha256=4708749ebfc13f8a06f8c6a877168839b2660389219a1b3976eebce02c5f2de9 and state_version_before=25. Correlation ID and event sequence were not exposed; direct linkage from this row to the exact production event pair is not proven.

FAULT_ISOLATION_ROOT_CAUSE: CONFIRMED. A global locator index rebuild projects every changed investigation before applying account/product filters; a duplicate in one session aborts the rebuild and prevents unrelated queries.

FILTER_ORDER: Projection and duplicate validation precede account/opportunity/product filters in project_product_opportunities; the locator index rebuild also precedes selection of matching sessions.

DERIVED_FALSE_NEGATIVE_ROOT_CAUSE: PARTIAL. get_demand_anchors ignores top-level identity selectors and maps absent seeds to READY with anchors=[]. Supplying a bad seed reaches derive_demand_anchor and propagates the projection exception; no exception-swallow path was found. Passing an explicit empty anchor list to evaluate_market_acceptance yields M0 / NO_VERIFIED_PROCUREMENT, which means no procurement was verified in that supplied list, not that the buyer has no procurement.

CRAWLER_REDIRECT_GUARD_ROOT_CAUSE: PARTIAL. Both current crawler implementations contain request-route interception plus seed/final URL validation; an isolated Crawl4AI hook test confirms a private IPv4 URL is aborted before route continuation. No live Render/browser redirect probe was run. Guard failures are not given a dedicated error class and can be reported as retryable SOURCE_UNAVAILABLE.

CRAWLER_ERROR_LEAK_ROOT_CAUSE: CONFIRMED. Backend exceptions and page errors are copied into CrawlPage.error and then returned verbatim in failed_urls; no response sanitizer is present on that path.

SCHEMA_MISMATCHES: CONFIRMED. Most read-only descriptors advertise only the generic base properties with required=[] and additionalProperties=true, while handlers require tool-specific shapes. See the table below.

RECURSIVE_EXPANSION_BINDING_ROOT_CAUSE: CONFIRMED. The descriptor advertises top-level opportunity_id, while the service forwards the request unchanged and prepare_recursive_expansion reads promoted_anchor.opportunity_id, account_id, product_profile_id, and stage.

PLANNER_EXPLOSION_ROOT_CAUSE: CONFIRMED. plan_candidate_expansion consumes query_limit/source_task_limit but ignores top-level limit; discovery generation builds 54 candidate queries and source planning materializes the Cartesian product (7,668 tasks) before truncating to 1,000.

TESTS_ADDED: tests/test_v64_round1_regressions.py

TESTS_FAILING_BEFORE_FIX: 10 methods executed; 20 assertion/subtest failures, 0 errors. Eight methods fail; the isolated private-route-hook probe and empty-anchor/M0 semantics check pass. The red tests are intentionally left failing for the next patch round.

PRODUCTION_DATA_CHANGED: NO

NEXT_PATCH_PLAN:
1. Preserve append-only history; establish exact create-event multiplicity, payload equality/conflict, event sequence, and correlation in an isolated read of the authoritative production event chain before deciding whether duplicate retries are identical or conflicting.
2. Add a pre-append business-identity check in create_product_opportunity. Exact same verified identity/payload should replay or return a conflict without a second durable create event; different immutable identity data must fail closed. Do not delete or rewrite old events.
3. Make the derived locator tolerate/quarantine a corrupt investigation while continuing to index healthy investigations. Keep the corruption visible and fail closed when the queried scope itself is corrupt. Apply account/product scope before expensive projection where the durable locator permits it.
4. Give anchor reads an explicit input/status contract: resolve identity-scoped requests or return BLOCKED/INVALID_INPUT; do not report ignored identity selectors as READY-empty. Preserve M0 only for a complete, explicitly evaluated anchor set.
5. Add typed REDIRECT_TARGET_BLOCKED and safe non-retryable behavior for URL-guard denials; add a real-browser redirect test with an instrumented private-endpoint listener and DNS-rebinding coverage. Sanitize errors through an allowlist before returning receipts.
6. Replace generic read-only schemas with domain-specific schemas and validation. Make recursive expansion resolve the canonical opportunity snapshot by investigation/opportunity identity, then construct the nested anchor from durable fields rather than trusting caller-supplied stage/ownership.
7. Respect caller limit, bound work before materialization, use lazy enumeration plus deterministic paging/cursor and expose candidate counts separately from returned rows.
8. Extend health/acceptance checks to cover v6.3 opportunity projection integrity and require fresh Render runtime identity and deployed SHA before any production acceptance claim.
```

## Repository and runtime evidence

The plugin checkout was clean on branch `cbi-v6-cloud-runtime-20260901` at base `11db255b23a4783b4aa99182518886abee2a8306`. Round 1 ran in the new branch named above, created from that exact SHA. Production baseline SHA is **UNKNOWN / UNVERIFIED**.

The current CBI runtime-health read returned `runtime_version=6.4.0`, `build_id=CBI-V6.4-SELF-HOSTED-CRAWLER-PRODUCTION-V1`, `local_runtime=true`, and `tunnel_reachability_proven=false`. It reported 183 checked sessions, 167 canonical accounts, 831 committed WAL rows, and 83 committed-error WAL rows. This establishes local runtime state only; it does not identify the Render deployment or its commit. The health implementation validates session/hash chains, canonical registry, pending journal, and the v6 host queue; it does not validate the v6.3 opportunity locator/projection. The crawler health booleans are static configuration claims, not a measured redirect test.

Read-only tool results: C364 and C363 opportunity reads both returned `V63_DUPLICATE_PRODUCT_OPPORTUNITY_CREATE_EVENT:OPP-C364-PVC-20260921`; the C364 expansion-state read returned the same projection failure; `get_demand_anchors(account_id=C364)` returned `READY` and an empty anchor list. The WAL audit returned a sanitized `COMMITTED_ERROR` row for `create_product_opportunity` with the request hash and state-version details recorded above. The audit did not supply a durable event count, event sequence/hash, or correlation ID. No production mutation or Render deploy was made.

## Call chains traced

### Opportunity reads and fault isolation

```text
MCP get_product_opportunities
  mcp/server_v61.py:_v63_get_product_opportunities_handler (line 1018)
  -> Runtime.get_product_opportunities (unified_runtime/demand_expansion.py:261)
  -> _v63_query_opportunity_events (production_integration_bindings_v63.py:329)
  -> _ensure_v63_locator_index (production_integration_bindings_v63.py:269)
  -> _v63_locator_session_row (production_integration_bindings_v63.py:228)
  -> _read_v63_durable_events (production_integration_bindings_v63.py:204)
  -> project_product_opportunities (v63_projection.py:53)
  -> duplicate check (v63_projection.py:67-72)
  -> account/opportunity/product filters (v63_projection.py:86-95)
  -> join derived view and return
```

The query filters are too late in two places: the locator rebuild scans all changed sessions before choosing matching sessions, and the projector validates every create event before filtering its rows. `_v63_locator_session_row` catches only orphan-promotion errors; duplicate-create errors escape. This makes C364 corruption contaminate C363 and other product queries. The isolated regression invokes the real lazy locator rebuild against temporary synthetic sessions and reproduces the same cross-scope failure.

`get_expansion_state` (demand_expansion.py:359) calls `get_product_opportunities`. `get_portfolio_metrics` (line 508) also loads opportunities unless a caller supplies a list, so both inherit the same failure. `plan_contact_exhaustion` (line 492), `evaluate_route_reuse` (line 500), and `evaluate_sales_readiness` (line 541) call `_v63_resolve_opportunity` (line 293), which resolves from `get_product_opportunities`; they are likewise blocked by the projection failure. `derive_demand_anchor` (line 565) resolves and validates the opportunity before deriving the anchor when investigation identity is supplied.

### Create mutation and WAL order

```text
MCP create_product_opportunity
  mcp/server_v61.py:_v63_create_product_opportunity_handler (line 1090)
  -> _invoke_mutation (server_v61.py:675)
  -> validate idempotency key and write PREPARED (lines 687-737)
  -> invoke wrapped runtime handler (line 739)
  -> Runtime.create_product_opportunity (demand_expansion.py:595)
  -> _invoke_v63_durable_mutation (demand_expansion.py:562)
  -> bound production backend create_product_opportunity
  -> append V63_PRODUCT_OPPORTUNITY_CREATED event (existing_production_store_backend_v63.py:58-92)
  -> refresh locator index for investigation (production_integration_bindings_v63.py:529-533)
  -> duplicate projection can raise
  -> outer WAL handler writes COMMITTED_ERROR (server_v61.py:754-767)
```

The backend validates canonical resolution and profile pinning, then appends; it has no lookup that rejects/replays an already-created business opportunity before append. The integration binding refreshes the locator only after `super()._invoke_v63_durable_mutation` returns. Thus source order permits a durable append followed by locator failure and a `COMMITTED_ERROR` WAL record. That source ordering is confirmed. Whether the sanitized production WAL row corresponds to a particular pair of durable events remains unconfirmed without event-level sequence/correlation evidence.

### Demand-anchor and market-acceptance composition

`get_demand_anchors` (demand_expansion.py:322) reads only `arguments.seeds`, derives each dictionary seed, then unconditionally returns `status=READY`; account/opportunity selectors at the top level are ignored. A seed with investigation/opportunity identity enters `derive_demand_anchor`, which resolves the opportunity and lets projection errors propagate. Therefore the handoff's specific claim that this function swallows a derivation exception is contradicted by current source.

The empty-input path is real: identity-only arguments produce `READY, anchors=[]`. `evaluate_market_acceptance` (line 353) consumes only the explicitly supplied `anchors`; the domain evaluator in `demand_market.py:116-124` maps an empty list to `M0 / NO_VERIFIED_PROCUREMENT`. This is not proof that a company lacks procurement; it is a conclusion about the provided empty set. The failure is the missing resolution/completeness contract between the tools. `get_market_cells` similarly consumes an explicit `items` list (line 336) and does not implicitly fetch anchors.

### Crawler, redirect handling, and response errors

```text
MCP public crawl handler (mcp/crawler_tool_v64.py:337)
  -> _run_coroutine_sync (line 313)
  -> _execute (line 204)
  -> Crawl4AIBackend(public_network_only=True) (lines 263-292)
  -> optional PlaywrightBrowserBackend with public_network_only=True
  -> CrawlExecutionBridge.execute (crawler_execution_bridge.py:810)
  -> backend.fetch
```

The seed is validated before navigation in both backends. Crawl4AI registers a `page.route("**/*", guard_route)` callback that resolves each HTTP(S) request URL and aborts non-public targets (crawler_execution_bridge.py:145-178); `before_goto` validates the seed and `after_goto` validates the final page URL (lines 180-205). Playwright also registers a per-request route callback and validates `page.url` after `goto` (browser_escalation.py:279-357). The isolated callback test confirms the current Crawl4AI hook aborts `127.0.0.1` without continuing it. This disproves a code-level claim that no redirect/request guard exists.

No real browser was launched against a controlled public-to-private redirect in this round. Therefore pre-request blocking in the deployed Render runtime, redirect behavior across Crawl4AI/Playwright versions, and DNS-rebinding/TOCTOU resistance remain unverified. The response path has a confirmed gap: Crawl4AI returns raw exception/error strings (crawler_execution_bridge.py:221-254), Playwright does the same (browser_escalation.py:390-399), and CrawlExecutionBridge copies page errors into `failed_urls` (crawler_execution_bridge.py:891-892). Guard-specific strings are not recognized by `_source_access_blocked_failure` (line 716), so they fall through to `SOURCE_UNAVAILABLE` and `retryable=true` (lines 971-1019). The red test verifies this classification gap; it does not simulate a live redirect.

### MCP schema, wrapper, and recursive expansion

`server_v61.py:995-1007` merges the descriptors from `build_v63_tool_descriptors`; lines 1018-1084 register thin wrappers that pass the received argument dictionary directly to runtime methods. `_descriptor` in `mcp_schema_v63.py:332-364` gives most read-only tools only `investigation_id`, `account_id`, `opportunity_id`, and `product_profile_id`, with `required=[]` and `additionalProperties=true`. Only two read-only tools have specialized schemas. Unknown fields may pass at the transport level, but clients do not receive a declared, validated contract.

| Tool | Domain input found in implementation | Descriptor gap |
| --- | --- | --- |
| `get_demand_anchors` | `seeds` list | `seeds` absent; identity fields alone are silently ignored |
| `evaluate_market_acceptance` | `anchors` list | `anchors` absent |
| `assess_candidate_researchability` | required `candidate_id`, `company_name`, `product_profile_id` | first two absent |
| `plan_candidate_expansion` | `product_profile_id`, `geography`; optional limits | `geography` absent; `limit` is not wired to either internal limit |
| `evaluate_relative_opportunity` | required `anchor_grade`, `candidate_grade`; scores | both grade fields absent |
| `project_legacy_peer_receipt` | required `source_event=PEER_RECEIPT_APPENDED`, `peer_id` | both absent |
| `preview_customs_seed_expansion` | investigation/account/opportunity, source evidence IDs, product, geography | source IDs and geography absent; requiredness not expressed |
| `plan_contact_exhaustion`, `evaluate_route_reuse`, `evaluate_sales_readiness` | investigation + opportunity IDs, or supplied opportunity object | required identity pair/object alternative absent |
| `preview_recursive_anchor_expansion` | nested `promoted_anchor` plus nested `market_cell` | descriptor shows top-level IDs but neither nested object/shape |

For recursion, `preview_recursive_anchor_expansion` (demand_expansion.py:477) forwards arguments unchanged to `prepare_recursive_expansion` (recursive_expansion.py:20). That function reads `payload.promoted_anchor.opportunity_id/account_id/product_profile_id/stage` and `payload.market_cell.market_cell_id/geography/product_profile_id`. Passing the top-level opportunity ID advertised by the generic descriptor reproducibly raises `ValueError: opportunity_id is required`. A patch must resolve the durable opportunity and validate promoted stage/owner/product; it must not merely wrap caller-supplied identity fields into an authoritative-looking anchor.

### Planner reproduction

`plan_candidate_expansion` (demand_expansion.py:453-472) pops `query_limit` (default 100) and `source_task_limit` (default 1000), then overwrites `context.limit` with `query_limit`. Top-level `limit=5` is unused. `generate_discovery_queries` constructs candidate rows before slicing (expansion_planner.py:190-327). `plan_public_source_tasks` forms branch × source family × query tasks (source_execution.py:57-102) and slices to `max_tasks` after constructing the full list. There is no continuation cursor in its response.

Isolated exact-input reproduction: `account_id=C363`, `product_profile_id=PVC`, `geography=Mexico`, `market_acceptance=M0`, no grade/score, empty applications/archetypes, and `limit=5` produced `query_candidate_count=54`, `query_returned_count=54`, `task_candidate_count=7668`, `task_returned_count=1000`, `truncated=true`. This was planner-only; no search or crawl executed.

## Test evidence and limits

Command environment: Python 3.15 at `C:\Users\scorp\AppData\Local\Python\pythoncore-3.15-64\python.exe`.

The isolated new suite executed 10 test methods: 20 assertion/subtest failures, 0 errors. The current-route-hook probe and the explicit empty-anchor/M0 semantics check passed. Red findings:

- T1: a duplicate in the real lazy locator rebuild prevents the C363 account query from returning its healthy opportunity.
- T2: the same C364 PVC duplicate prevents WPC, SPC, and ACRYLIC_PMMA lookups.
- T3: identity-scoped `get_demand_anchors` returns `READY` instead of resolving or reporting a projection/input block.
- T4: a private-destination guard error becomes `SOURCE_UNAVAILABLE` and retryable, not a typed redirect block.
- T5: `Traceback`, `site-packages`, `runner.py`, and `Code context` appear in the returned receipt.
- T6: top-level opportunity context is rejected with `opportunity_id is required`.
- T7: `limit=5` returns 54 discovery queries; exact baseline separately measured 7,668 candidate / 1,000 returned source tasks.
- Schema check: 8 gaps across required domain inputs and opportunity-scoping contracts.

Adjacent pre-existing baseline checks from the Round 1 audit: `test_v63_recursive_expansion.py` 5/5 pass, `test_v63_expansion_planner.py` 17/17 pass, `test_v63_mcp_schema.py` 21/21 pass, `test_v64_crawler_execution_bridge.py` 18/18 pass, `test_v64_crawler_mcp_surface.py` 10/10 pass. `test_v63_production_integration_completion.py` ran 20 with one existing sales-readiness failure: expected `OUTREACH_EXECUTION_READY`, received `WAIT_FOR_LOCAL_WINDOW`. `test_v63_sales_readiness.py` ran 7 with 3 existing failures because global Python 3.15 has no timezone database (`ZoneInfoNotFoundError` for `Asia/Ho_Chi_Minh`; `tzdata` package absent). No packages were installed and no global interpreter setting was changed. These baseline failures are environment/runtime findings, not caused by the Round 1 test file.

## Stop boundary

Round 1 evidence and regression tests are complete. The only new files are the intentionally failing test module and this report. No runtime source, production data, Render service, or deployment was changed. The next authorized stage is Round 2 patching on this isolated branch; production acceptance still requires exact production event evidence, fresh Render service/deployed SHA, and a live controlled redirect probe.
