# Customs Buyer Intelligence v6.1 Test Plan

## Release gates

All P0 tests must pass before `Production Ready`. No accepted adversarial sample may be waived by documentation.

## Unit tests

- Claim-state transitions, corroboration, staleness, conflict and negative exhaustion.
- EIV formula, threshold ordering and budget pause semantics.
- Commercial Value independent from contact/CRM.
- Research Confidence and Outreach Readiness boundaries.
- Evidence-bound, monotonic Peer lifecycle and optional contact coverage for Anchor eligibility.
- Pivot materiality, below-threshold disposition, later-objective consumption and terminal-state monotonicity.
- credential/query-secret, finite-number, Unicode, URL, locator, raw/hash equality, Owner and route validation.

## Integration tests

- start → compile bundle → Claims → objectives → saturation → Closure.
- 1,000-observation bundle with partial success and deterministic replay.
- host queue while MCP is absent, cold-process replay and deduplication;
- concurrent Pending Receipt and host-bundle recovery jobs invoke each handler once and record one terminal result.
- promoted Anchor six-branch audit.
- CRM plan → external synthetic receipt → independent CRM state.
- Closure → Account-owned route → one-time draft render; no send.

## Migration tests

- copy v5.4.1 fixture to a distinct root;
- source hashes unchanged;
- copied chain valid before and after v6 extension;
- canonical IDs and history preserved;
- existing Closure not treated as fresh v6 Closure;
- failed target validation returns `switched=false`.

## Crash and concurrency tests

- process death after individual observation append and before bundle summary;
- retry completes remaining rows without duplication;
- concurrent writers and concurrent identical bundles serialize sequence/hash correctly with exactly-once replay;
- dead-process sentinel locks recover without stealing a live owner;
- Closure/outreach conditional-tail races fail closed;
- restart reconstructs state without in-memory ownership;
- corrupt tail returns `QUARANTINED_READ_ONLY`.

## Property and adversarial tests

- arbitrary batch partitioning produces the same accepted observation set;
- replay is idempotent;
- first positive never closes unresolved critical Claims;
- first email/phone/person never closes research;
- grade never shortens research;
- budget never becomes completion;
- empty/fake/self-authored locator rejected;
- Evidence Owner or Claim mismatch rejected;
- `NEGATIVE_EXHAUSTED` without multiple independent strategies or without binding declarations to actual attempt queries rejected;
- two pages or content hashes from one controlling website never become two independent corroborating sources;
- Peer-owned Evidence before discovery and bare-boolean Peer promotion rejected;
- expired Closure cannot be reused and any later operational event makes Closure stale;
- 403/login/paywall cannot become N/A or Negative Exhausted;
- masked/guessed/third-party route cannot become send-ready;
- phone never implies WhatsApp/Zalo;
- provider token fields never persist;
- contact/CRM absence never caps Commercial Value;
- Anchor eligibility does not require contact coverage;
- undispositioned Peer, Anchor-eligible unpromoted Peer and promoted Anchor without six-branch audit block saturation.

## Golden fixtures

Synthetic, non-production fixtures use the labels Western Woods, Arecibo Home Center, Arecibo Home Design, Chimelis, Tesoro, Forza, Edwin Seda and Hangzhou Promise. They test known relationship, conflict, route and network patterns without asserting new live facts about those names.

## Load targets

- 1,000 observations in one compiler request.
- 100 concurrent append attempts with no duplicate sequence.
- 1,000 queued bundles listed and dry-run replayed.
- 500 investigations ranked by the Portfolio Scheduler.

## Packaging gates

- MCP initialize and exact 42-tool discovery.
- every tool legal/illegal input check.
- original compatibility suites.
- plugin and skill validators.
- source and cold-copy privacy scans.
- no `__pycache__`, `.pyc`, credentials or production CRM in plugin.
- cachebuster/reinstall and new-task discovery.
