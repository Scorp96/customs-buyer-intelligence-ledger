# CBI v6.3 — Isolated Render / R2 / PVC Deployment Acceptance Design

**Date:** 2026-09-03  
**Branch:** `cbi-v6-3-demand-expansion`  
**Predecessor gate:** exact-checkout acceptance at feature SHA `42080887ff910ae48acde72f45b03d58e37c434b`

## Objective

Prove CBI v6.3 against an isolated, production-shaped remote deployment before any production branch merge or production cutover. The deployment acceptance must exercise the real HTTP MCP path, Cloudflare R2-compatible object storage, cross-instance durable recovery, and a disposable synthetic PVC demand-expansion scenario.

Passing this phase is evidence for the later release gate. It does not by itself mutate the production branch, reuse production customer data, or authorize production traffic.

## Non-goals

- No production branch update or merge in this phase.
- No production Render service mutation.
- No production R2 prefix or customer ledger reuse.
- No caller-supplied verdict flags.
- No replacement recovery implementation parallel to the active v6.1/v6.3 handler stack.
- No paid-disk-only proof substituted for the required R2 proof.
- No reference/mock runner accepted as deployment proof.

## Verified current-state constraints

### Existing Render descriptor is not the acceptance environment

The repository's current Render descriptor is a free/preview-style configuration and existing tests intentionally enforce an ephemeral, fail-closed preview shape. Deployment documentation also describes a paid persistent-disk shape. The acceptance environment therefore requires its own descriptor instead of silently repurposing either current contract.

### Current object-store snapshot is session-only

`mcp/object_store_persistence.py` currently snapshots and fingerprints the session tree. The v6.1 mutation journal is stored at the live-root sibling path `mcp-idempotency-v61/`, not under `sessions/`.

Consequences:

1. WAL-only changes do not necessarily advance the object-store generation.
2. A new ephemeral instance can restore session events without the matching PREPARED/COMMITTED mutation journal.
3. Exact cross-instance recovery cannot be claimed from the current object-state archive.

### Current remote sync is too late for cold exit

The remote adapter synchronizes object-store state after `tools/call` returns or raises. The accepted cold-crash probe exits with `os._exit(91)` after the handler side effect and before WAL terminal commit. `os._exit` bypasses the outer adapter's exception path, so the post-handler PREPARED evidence is not guaranteed to reach R2 before process death.

These are release blockers, not test-fixture issues.

## Selected architecture

Use a dedicated feature-branch Render acceptance service backed by a disposable R2 namespace. Extend object-store persistence to a recovery-state generation that contains the complete minimum exact-recovery authority, then add a remote-only durability checkpoint immediately after mutation side effects and before cold-process exit.

The accepted local/stdin execution path remains unchanged unless the remote persistence hook is installed.

### Alternatives considered

1. **Selected — dedicated Render acceptance + real R2 + recovery-state v2.** Proves the actual deployment and cross-instance recovery contract with strong isolation.
2. **Local fake object store only.** Required for deterministic TDD but insufficient as release evidence because it does not prove Render lifecycle, real R2 API semantics, or deployed HTTP MCP.
3. **Paid persistent disk only.** Useful as an operational option, but insufficient for this gate because the predecessor acceptance explicitly requires Render/R2 deployment proof and does not prove object-store restore across instance replacement.

## Recovery-state v2 contract

Introduce a new object-state schema, `cbi.object-store-state.v2`, with backward read support for the existing migration and object-state v1 archives.

A v2 generation represents one coherent recovery root and must include, at minimum:

- `sessions/`
- `mcp-idempotency-v61/`

The manifest must include:

- schema and generation,
- aggregate recovery-state fingerprint,
- component inventory,
- per-file SHA-256 and size,
- archive creation metadata already required by existing persistence semantics.

The aggregate fingerprint must change when either session state or mutation WAL changes. A WAL-only PREPARED or terminal transition must therefore be observable by `sync_if_changed`.

Restore requirements:

- extract only into staging;
- reject traversal, links, devices and malformed inventory using existing safe-extraction principles;
- verify every declared file hash before activation;
- restore both sessions and WAL into the intended live root;
- never infer an empty WAL as equivalent to a missing WAL for v2;
- retain read compatibility with legacy v1 and migration archives.

Operational R2 archives are private runtime state. They may contain the existing v6.1 WAL representation, but acceptance reports and GitHub artifacts must never expose raw idempotency keys or object-store credentials.

## Remote durability checkpoint

The mutation lifecycle on the remote R2-backed path becomes:

1. write local PREPARED WAL;
2. execute the existing production mutation handler;
3. construct the business result and correlated durable event;
4. run an optional post-handler durability checkpoint;
5. only after the checkpoint succeeds, execute the existing cold-crash injection check;
6. on normal completion, write local terminal WAL;
7. run the existing post-tool object-store sync so the terminal state advances R2.

The checkpoint is installed only by the remote object-store runtime and synchronizes the complete recovery root, not `sessions/` alone.

Failure semantics:

- If the checkpoint fails after the side effect, do not acknowledge success.
- Do not falsely convert the PREPARED intent into a terminal success/error receipt merely because remote persistence failed.
- Preserve fail-closed reconciliation semantics.
- Local/stdin behavior remains unchanged when no checkpoint is registered.

Cold-crash acceptance must prove:

- R2 contains one PREPARED WAL plus the matching durable event before process exit;
- a fresh instance restores both;
- retrying the exact same request through active HTTP MCP performs recovery without a second business event;
- the restored request hash and correlation remain exact;
- terminal recovery state is subsequently persisted to R2.

## Dedicated Render acceptance descriptor

Add a separate descriptor, `render.v63-acceptance.yaml`, rather than changing the existing Render contract prematurely.

Required properties:

- service is clearly named as v6.3 acceptance, not production;
- branch is `cbi-v6-3-demand-expansion`;
- `autoDeployTrigger: off` so acceptance is explicitly initiated;
- ephemeral/free compute is acceptable because R2 is the durability authority being tested;
- no persistent disk is required for this gate;
- `CBI_OBJECT_STORE_MODE=r2`;
- bucket, endpoint, access key, secret and acceptance prefix are external environment values/secrets, never committed;
- acceptance R2 prefix is disposable and isolated from production;
- bearer authentication remains enabled;
- startup uses the real Render bootstrap/remote stack, not a test server.

The service must fail closed when R2 current state cannot be restored or validated.

## Deployment identity

Remote health must expose safe, non-secret deployment identity sufficient to pin the acceptance run:

- deployed Git SHA derived from `RENDER_GIT_COMMIT` when present;
- active remote entrypoint/runtime identity;
- object-store mode;
- object-state schema/current generation when available;
- boot restore generation/source where available.

Acceptance must stop before mutation if the deployed Git SHA does not exactly match the expected feature SHA.

No health response may expose bearer tokens, object-store access keys, secrets, raw idempotency keys, or customer data.

## Remote HTTP MCP acceptance flow

The acceptance producer is configuration-only. Allowed caller inputs are deployment coordinates and secrets required to execute the test, such as endpoint, bearer token, expected Git SHA, R2 acceptance namespace and a restart/deploy trigger. Caller inputs may not include pass/fail verdicts or prebuilt reports.

Required deployed checks:

1. boot/health proves exact feature SHA and R2-backed runtime;
2. MCP initialize/discovery/tool listing proves the active v6.3 mutation surface;
3. append/restore roundtrip proves R2 generation advancement and fresh-instance restoration;
4. candidate crash/recovery proves cross-instance exact durable recovery;
5. opportunity and anchor representative recovery checks preserve exact snapshot/gate semantics;
6. all observed evidence is normalized without raw idempotency keys.

## Disposable PVC demand-expansion scenario

Use synthetic identifiers only and the repository's canonical `PVC` product profile.

Minimum active HTTP MCP scenario:

1. start a synthetic investigation;
2. execute representative demand-expansion planning/derivation through the live v6.3 surface;
3. append one PVC candidate discovery;
4. create one PVC product opportunity using the canonical product-profile version/hash;
5. promote the opportunity anchor with valid eligibility and cycle-dedup evidence;
6. prove the resulting events and mutation evidence survive R2-backed instance replacement;
7. verify no duplicate candidate/opportunity/anchor business event is created during recovery.

No real company/account/customer information is allowed in this acceptance namespace.

## Acceptance artifacts

The deployment run must produce sanitized JSON artifacts bound to:

- feature Git SHA,
- production-source snapshot SHA,
- Render service/deployment identity,
- R2 endpoint class and disposable prefix identifier without credentials,
- object-state schema/generation lineage,
- HTTP MCP tool contract,
- crash/recovery evidence,
- PVC synthetic scenario evidence,
- validator results.

Raw idempotency keys, bearer tokens, R2 credentials and private customer state are forbidden in artifacts.

The top-level result must remain `production_ready: false` until the real Render/R2/PVC run is complete and the later production release-evidence gate independently accepts it.

## CI and execution boundary

Local/CI deterministic tests run on feature pushes. Real Render/R2 deployment acceptance is a separate `workflow_dispatch`/explicitly triggered gate using repository/environment secrets.

The real deployment workflow must:

- deploy the exact feature SHA to the isolated acceptance service;
- verify the deployed SHA before mutation;
- use only the disposable acceptance R2 namespace;
- run the remote acceptance producer;
- upload only sanitized receipts;
- never update the production branch;
- never deploy the production Render service;
- fail closed when required secrets or external configuration are absent.

An unexecuted or secret-blocked deployment workflow is `BLOCKED_EXTERNAL`, not PASS.

## Compatibility

- Existing object-state v1 and migration-v1 restores remain readable.
- Existing local/stdin MCP execution remains unchanged when remote durability checkpoint is absent.
- Existing production branch remains untouched during feature acceptance.
- Existing Render descriptor is not modified until a later release/cutover decision explicitly chooses its production topology.

## Test strategy

TDD sequence:

1. prove current object-store restore loses WAL;
2. implement and verify v2 sessions+WAL archive/restore and WAL-only fingerprint changes;
3. prove remote cold exit bypasses current post-tool sync;
4. implement/checkpoint hook and prove checkpoint precedes cold exit without altering local behavior;
5. verify deployment identity health fields;
6. statically validate the dedicated acceptance Blueprint;
7. build an HTTP MCP acceptance client and deterministic local remote-stack integration tests;
8. run synthetic PVC acceptance locally against in-memory/fake object store;
9. add explicit real Render/R2 workflow and validators;
10. execute the real external gate when credentials are available.

Every task must retain the existing exact-checkout regression, full repository regression, v6 protocol and v6.1 hardening gates.

## Release rule

No production merge or production-ready claim is allowed until all of the following are real and GREEN:

- exact-checkout acceptance;
- object-store recovery-state v2 tests;
- cross-instance crash/recovery using R2-backed deployed storage;
- deployed Git identity pin;
- deployed HTTP MCP contract;
- disposable PVC demand-expansion scenario;
- sanitized deployment receipt validators;
- full repository/protocol regression;
- production branch baseline unchanged until the explicit merge step.
