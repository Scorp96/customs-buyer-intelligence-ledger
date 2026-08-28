# Customs Buyer Intelligence v6.1 API Specification

## Contract and health

- `get_runtime_contract()` returns versions, enums, architecture, Claim catalog, EIV, Peer, durability and error policies.
- `get_runtime_health(investigation_id?)` validates sessions, canonical data, Runtime pending data and host queue.
- `get_investigation_health(investigation_id)` returns last safe sequence/hash or `QUARANTINED_READ_ONLY`.

## Account and investigation

- `resolve_or_create_account(candidate, requested_account_id?, create_if_missing?)` preserves canonical ambiguity.
- `start_investigation(account, mode?, priority_grade?, budget_units?, claim_catalog?, ...)` creates/resumes and appends the v6 extension.
- `resume_investigation(investigation_id)` explicitly resumes durable state after process or transport loss.
- `get_account_state(investigation_id)` returns the four independent business dimensions.
- `get_investigation_state(investigation_id)` returns Claims, counters, saturation and last safe position.

## Research planning and compilation

- `submit_research_objective(investigation_id, objective)` computes and stores EIV.
- `get_next_research_objectives(investigation_id, limit?)` ranks unresolved Claims and material Pivots under budget.
- `compile_and_append_research_bundle(investigation_id, bundle)` accepts 1–1000 bounded observations, returns per-row `ACCEPTED`, `DEDUPLICATED` or `REJECTED`, validates raw material against a supplied SHA-256, and provides exactly-once concurrent replay.
- `get_claims(investigation_id)` returns Claim states and Evidence bindings.
- `get_material_pivots(investigation_id)` returns open material Pivots.
- `close_pivot(investigation_id, pivot_id, status, reason, consumed_by_objective_id?, max_remaining_eiv?)` appends the closure decision. `NOT_MATERIAL` requires finite remaining EIV below threshold; terminal states do not regress.

## Peer and network

- `append_peer_discovery(investigation_id, peer)` requires branch and relationship Evidence.
- `evaluate_peer(investigation_id, peer_id, assessment)` advances the stage monotonically. Positive facts require `fact_evidence_ids` bound to compatible Peer-owned Claims; canonical-new is registry-derived. Contact coverage is optional for eligibility.
- `promote_anchor(investigation_id, peer_id, promotion_reason)` requires `ANCHOR_ELIGIBLE`.

## Evaluation

- `evaluate_commercial_value(investigation_id)` returns `A+`–`NQ` without contact/CRM caps.
- `evaluate_research_confidence(investigation_id)` returns `R0`–`R5`.
- `evaluate_outreach_readiness(investigation_id)` returns the independent route state.
- `evaluate_decision_saturation(investigation_id)` returns blockers and above-threshold work.
- `evaluate_investigation_closure(investigation_id)` issues a short-lived, single-use research Closure only after saturation. Expired tokens are never reused and all operational mutations stale earlier tokens.
- `evaluate_commercial_readiness(investigation_id)` is a compatibility entry point returning all four dimensions.

## CRM and outreach

- `prepare_crm_writeback(investigation_id, target_workbook_path, records?)` returns a deterministic Artifact Tool transaction plan and writes nothing.
- `append_crm_writeback_receipt(...)` validates the external transaction proof.
- `prepare_outreach(...)` binds a v6.1 Closure and Account-owned Route with atomic tail checking, concrete-claim authority scanning and 80–110-word first-touch enforcement; CRM sync is not a Commercial Value gate.
- `render_outreach_action_card(...)` opens a one-time local draft and never sends.

## Recovery, portfolio and migration

- `queue_host_bundle(payload, bundle_queue_id?)` writes to the independent host queue.
- `sync_pending_bundles(...)` and `sync_pending_research_bundles(...)` replay idempotently.
- `get_portfolio_queue(limit?)` ranks accounts by value, confidence, EIV and budget.
- `migrate_v5_4_1_to_v6(target_root, source_session_root?)` rejects empty/overlapping roots, copies the supplied session root with its own canonical/pending data, verifies source and target manifests, and never switches.

## Compatibility APIs

`append_information_record`, `get_information_history`, `plan_public_source_calls`, `plan_provider_calls`, `append_execution_receipt`, `append_provider_receipt`, `append_peer_receipt`, `queue_pending_receipt`, `get_pending_journal_status`, and `sync_pending_receipts` remain supported for v5 lineage and gradual migration.

## Error behavior

Validation failures are per observation inside compiler batches and fail-closed for security or ownership. Integrity failures quarantine the affected investigation read-only. Transport failure never changes research state and never converts to Negative or Complete.
