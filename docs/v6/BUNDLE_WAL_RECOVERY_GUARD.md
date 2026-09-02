# Bundle WAL Recovery Guard

This note records the production-acceptance boundary for `compile_and_append_research_bundle` crash recovery.

Automatic reconciliation is authorized **only** when a retry can find exactly one `V6_RESEARCH_BUNDLE_COMPILED` event that:

- occurs after the WAL `state_version_before`;
- carries the exact production mutation correlation for the retried idempotency key;
- matches `investigation_id`, `bundle_id`, and the Runtime-compatible `input_sha256`;
- uses schema `cbi.research-bundle-result.v6.1`; and
- contains the complete public result material (`status`, counts, accepted observation IDs, and outcomes).

A durable prefix is not a commit marker. If a process dies after one or more correlated `V6_OBSERVATION_COMPILED` events but before the final `V6_RESEARCH_BUNDLE_COMPILED` summary, the retry must remain `MUTATION_RECONCILIATION_REQUIRED`. The adapter must not rerun the compiler, infer a result from the prefix, or append duplicate observations.

A pre-existing bundle replay that produced no new correlated final summary also remains fail-closed after a PREPARED crash. Historical uncorrelated rows, missing summaries, and ambiguous summaries never authorize automatic replay.

The final bundle summary therefore acts as the durable commit proof for adapter-level crash reconciliation; it does not replace the Runtime's own validation or bundle idempotency rules.