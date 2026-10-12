# CBI v6.4: balanced six-branch discovery source planning

## Reproduced production problem (2026-10-12)

Read-only production `plan_candidate_expansion` call with `product_profile_id=SOAP_MACHINERY`, `geography=Indonesia`, `query_limit=24`, `source_task_limit=50` produced 50 planned tasks. **All 50** belonged to `TRADE_GRAPH/same_supplier_buyer` (24 trade_history, 24 supplier_official, 2 customs_parties); five other branch groups received **zero** tasks on page one.

This is an actual *planning/allocation* defect. It does not itself prove that any real customer has been found or lost.

## Fix (read-only planner)

- Replace nested group-first query enumeration with deterministic group round robin.
- Within a group, alternate branches; within each branch, alternate source families by query.
- Preserve `call_id` generation from `branch_group,branch,source_family,query`, preserving durable receipt association for individual tasks.
- Preserve all candidate task combinations, all source types, true pagination and `planning_is_execution_proof=False`.
- Use a canonical group order, independent of Python dict insertion order, to keep cursor semantics stable.
- Pin `task_order_policy=BALANCED_GROUP_BRANCH_FAMILY_V1` into the plan fingerprint. **Old cursors fail closed with `SOURCE_TASK_CONTINUATION_PLAN_MISMATCH`**, instead of silently mixing old and new positional indexes.

## Acceptance targets

- First six tasks of a complete six-group plan span all six groups.
- First fifty spread approximately equally across six groups and contain multiple branches and source families.
- Pagination over any page size reconstructs the same complete deduplicated plan with zero task loss/repetition.
- A truncated plan never certifies source exhaustion.
- A stored old-version cursor is invalidated explicitly; operator must replan. Previously **executed** receipts can still be matched to stable call IDs and need not be reexecuted.
- Existing PVC/WPC task identity, source family registry, and six-group contract remain stable.
- CI on Linux/Windows × Python3.10/3.11 + isolated real planner canary before any production deployment.

## Business boundary

Fairness creates **research coverage**, not actual searches. It does not scrape data, prove trade, invent business contacts or replace FULL_AUDIT. Real execution receipts, buyer roles, product identity, and paid data provider permissions remain separate. If source budgets are extremely small (fewer than six tasks), page continuation must cover the remaining groups before research is described as complete.

## Release caution

This is an ordering change. Active `continuation_token` values are **not compatible** with the new planner and must fail closed. Do not silently reuse old cursors or mark partially completed prior research as exhausted. Existing immutable candidate task IDs and evidence are preserved.
