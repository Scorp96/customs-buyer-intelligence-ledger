# Customs Buyer Intelligence v6.1 Data Model

## Investigation extension

The first v6 event stores `state_version`, Runtime/build version, Claim catalog, search playbook, network branches, priority grade, budget, EIV threshold and `DECISION_SATURATION` policy. A legacy v5 header remains immutable.

## ResearchObjective

Required logical fields:

- `objective_id`, `investigation_id`, `claim_key`;
- query or navigation action and source family;
- optional network branch;
- probability, decision impact, evidence-quality gain, commercial weight and search cost;
- computed EIV, status, input hash and submitted timestamp.

## ResearchBundle and CompiledObservation

A bundle contains 1–1000 raw observations. Each accepted observation stores:

- stable observation and bundle IDs;
- investigation, Owner type/ID and Account relationship;
- observation type, Claim key and result;
- normalized value and exact boundary;
- Source Family/type, reference type, concrete URL or locator, captured content SHA-256, authority, freshness and observed time;
- optional Evidence ID, conflict links, exhaustion proof, material/optional Pivots and commercial signals;
- search cost and compiler timestamp.

Raw full page content is hashed but not retained in the session log. When raw material and a declared hash are both supplied, they must match. A bounded excerpt may be retained. Provider credentials, credential-like query parameters and non-finite numbers are rejected recursively. Each observation is limited to 2 MiB and each bundle to 32 MiB.

## Claim projection

Claim state is derived, never overwritten. Independent controlling sources—not two pages or hashes from one website—may produce `STRONGLY_SUPPORTED`; opposing support/refutation or explicit links produce `CONFLICTED`; a single no-result remains `SEARCHING`; only validated multi-strategy exhaustion whose declarations bind to distinct actual attempts produces `NEGATIVE_EXHAUSTED`.

## Pivot

`pivot_id`, type, value, materiality, estimated EIV, generating observation, timestamps and status. Valid closures are `CONSUMED`, `NOT_MATERIAL` or `BLOCKED`. Consumption requires a real later objective. Not-material requires measured remaining EIV below threshold, and terminal states cannot reopen or regress.

## Peer

Identity, country/tax key, discovery Anchor, network branch, discovery observation, relationship Evidence and monotonic stage. Assessments retain Evidence IDs for entity, product, business/trade, relationship and novelty. Peer-owned Evidence must follow discovery; canonical-new is mechanically derived. A Peer remains a saturation blocker until promoted/audited or explicitly disposed with below-threshold remaining EIV. Contact coverage is stored separately.

## Closures and actions

A Closure binds Account, basis event hash, Decision Saturation digest, independent state dimensions, expiry and single-use flag. Expired Closure rows are never reusable; any later operational mutation makes them stale. Closure and outreach issuance use conditional tail appends so concurrent state changes fail closed. Outreach preparation binds the exact route, source Evidence, history/authority digests, subject/body/stage and a one-time render token.

## Host queue

Each envelope stores schema, queue ID, queued time, request SHA-256 and the exact compiler payload. Queue state changes are in a separate append-only hash-chain event log. Envelopes are retained after failed validation.

## Privacy and lineage

- Production data lives outside plugin source.
- Business-public PII may be retained only with source and Account relationship.
- Tokens, passwords, authorization headers and cookies are prohibited.
- Every mutation is append-only; current views are projections.
- Every migration records source/target, before/after source-manifest digests and the mechanically verified source-mutation result.
