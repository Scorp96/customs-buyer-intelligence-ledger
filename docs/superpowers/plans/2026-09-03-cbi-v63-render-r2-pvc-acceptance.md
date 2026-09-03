# CBI v6.3 — Render / R2 / PVC Deployment Acceptance Implementation Plan

**Date:** 2026-09-03  
**Branch:** `cbi-v6-3-demand-expansion`  
**Design:** `docs/superpowers/specs/2026-09-03-cbi-v63-render-r2-pvc-acceptance-design.md`

## Goal

Turn the completed exact-checkout acceptance into real isolated deployment evidence by hardening R2 recovery state, proving cross-instance crash recovery through the remote HTTP MCP stack, and executing a disposable synthetic PVC demand-expansion scenario. Production remains untouched until this gate and the later release-evidence gate are both GREEN.

## Invariants

- TDD only: RED must demonstrate the intended defect before implementation.
- No production branch update or production Render deployment.
- No production R2 prefix or real customer data.
- No caller verdict booleans/reports.
- No raw idempotency keys or credentials in acceptance artifacts.
- Existing local/stdin mutation semantics remain unchanged unless a remote durability hook is installed.
- Legacy object-state/migration restore remains readable.
- Full v6.3, full repository, v6 protocol, and v6.1 hardening regressions remain mandatory.

## Task 1 — Recovery-state v2: prove WAL omission

**Files**
- Create: `tests/test_v63_object_store_recovery_state.py`
- Modify: `mcp/object_store_persistence.py`

**RED**

Create a temporary live root containing:

- `sessions/INV-...jsonl`
- `mcp-idempotency-v61/<mutation>.json` with a PREPARED record

Use the existing in-memory object-store test client pattern to commit a state generation and restore into a fresh live root. Assert that both the session event and the WAL record restore byte-for-byte.

The current implementation must fail because only the sessions root is archived/restored.

**GREEN**

Add explicit recovery-root v2 support without breaking existing callers. The new archive must include `sessions/` and `mcp-idempotency-v61/`, verify hashes/sizes, and restore both into staging/activation paths.

Add assertions for:

- v2 schema;
- WAL restored;
- session restored;
- aggregate recovery fingerprint;
- no undeclared/malformed archive member accepted.

## Task 2 — WAL-only changes advance R2 generation

**Files**
- Extend: `tests/test_v63_object_store_recovery_state.py`
- Modify: `mcp/object_store_persistence.py`

**RED**

After attaching a restored v2 recovery root, change only a WAL JSON file. Assert `sync_if_changed` returns true and advances the generation/fingerprint.

**GREEN**

Compute v2 fingerprint over the complete recovery authority rather than sessions alone. Keep legacy session-only behavior for callers that do not opt into recovery-root v2.

Also prove existing v1 migration/object-state restore tests remain GREEN.

## Task 3 — Remote post-handler durability checkpoint

**Files**
- Create: `tests/test_v63_remote_durability_checkpoint.py`
- Modify: `mcp/server_v61.py`
- Modify: `mcp/server_v61_remote.py`

**RED**

Prove the current remote outer post-tool sync cannot execute after the accepted `os._exit(91)` crash point. Test via a subprocess or controlled hook boundary; do not monkeypatch the acceptance verdict.

**GREEN**

Add an optional post-handler durability checkpoint hook to the v6.1 mutation adapter:

- no hook by default;
- called after handler result/side effect is established and before cold-crash injection;
- remote runtime registers an R2 recovery-root sync hook;
- checkpoint failure does not acknowledge success and leaves a fail-closed reconciliation state;
- local/stdin behavior and existing WAL tests remain unchanged.

Prove ordering explicitly: PREPARED + business event -> checkpoint -> crash injection -> terminal commit only on non-crash path.

## Task 4 — Remote deployment identity and persistence health

**Files**
- Create: `tests/test_v63_remote_deployment_identity.py`
- Modify: `mcp/server_v61_remote.py`

**RED**

Require remote health to expose safe deployment identity and persistence lineage fields while rejecting malformed `RENDER_GIT_COMMIT` when acceptance pinning is enabled.

**GREEN**

Expose only safe fields:

- deployment Git SHA;
- active remote/runtime identity;
- object-store mode;
- object-state schema/current generation;
- restore generation/source where available.

Never expose tokens, object-store credentials, raw idempotency keys or customer payloads.

## Task 5 — Dedicated isolated Render acceptance Blueprint

**Files**
- Create: `render.v63-acceptance.yaml`
- Create: `tests/test_v63_render_r2_acceptance_blueprint.py`

**RED**

Require a descriptor that is explicitly feature-only, manually deployed, R2-backed, bearer-authenticated and free of persistent-disk/production-service coupling.

**GREEN contract**

The Blueprint must include:

- branch `cbi-v6-3-demand-expansion`;
- `autoDeployTrigger: off`;
- clearly non-production service name;
- real Render bootstrap/remote entrypoint;
- `CBI_OBJECT_STORE_MODE=r2`;
- external R2 bucket/endpoint/access/secret/prefix configuration;
- generated/external bearer secret;
- no production prefix/customer data;
- no persistent disk as proof substitute.

Do not change the existing production/preview `render.yaml` in this task.

## Task 6 — Remote HTTP MCP acceptance client

**Files**
- Create: `unified_runtime/render_r2_acceptance_client_v63.py`
- Create: `tests/test_v63_render_r2_acceptance_client.py`

Implement a configuration-only client that:

1. reads `/health`;
2. pins exact deployment Git SHA before mutation;
3. initializes/discovers HTTP MCP;
4. lists tools;
5. proves required v6.3 mutation surface;
6. sanitizes all response/evidence structures.

No caller pass/fail verdicts.

## Task 7 — Local cross-instance R2 integration proof

**Files**
- Create: `tests/test_v63_render_r2_cross_instance_recovery.py`
- Add focused support only where required in runtime/object-store code.

Using the real active mutation adapter and an in-memory S3/R2-compatible client:

1. boot instance A with empty disposable recovery root;
2. execute a synthetic candidate mutation with crash-after-handler;
3. prove checkpoint committed PREPARED WAL + durable event to object-state v2;
4. create fresh instance B/root;
5. restore from object store;
6. retry the exact same request;
7. prove one business event only, exact request hash/correlation, and terminal WAL persisted.

Repeat representative opportunity snapshot and anchor gate assertions as needed to show state shape is preserved across restore.

This task is necessary but still not sufficient for the external Render/R2 gate.

## Task 8 — Disposable PVC remote scenario and receipt validators

**Files**
- Create: `unified_runtime/render_r2_pvc_acceptance_v63.py`
- Create: `unified_runtime/render_r2_pvc_acceptance_validator_v63.py`
- Create: `tests/test_v63_render_r2_pvc_acceptance.py`

Use synthetic IDs and the canonical `PVC` product profile. Through the active HTTP MCP contract:

- start investigation;
- execute representative demand-expansion planning/derivation;
- append one candidate;
- create one PVC opportunity with exact profile version/hash;
- promote one anchor with eligibility/cycle proof;
- verify events/WAL survive instance replacement;
- verify no duplicate candidate/opportunity/anchor event.

Validator must fail closed on missing deployment SHA, R2 generation lineage, exact correlation/hash proof, cross-instance restore, or any secret/raw-idempotency exposure.

## Task 9 — Explicit real Render/R2 workflow

**Files**
- Create: `.github/workflows/cbi-v63-render-r2-pvc-acceptance.yml`
- Create: `scripts/run_v63_render_r2_pvc_acceptance.py`
- Create: `tests/test_v63_render_r2_workflow_contract.py`

Use `workflow_dispatch` only.

Required secret/external inputs include the isolated Render deployment trigger/API coordinates, deployed base URL/bearer configuration, and R2 acceptance credentials/prefix.

Workflow sequence:

1. checkout exact feature SHA;
2. run deterministic regressions;
3. deploy exact SHA to isolated acceptance service;
4. poll health and verify SHA;
5. execute remote HTTP acceptance;
6. trigger controlled instance replacement/redeploy;
7. verify R2 restore and exact recovery;
8. execute PVC scenario;
9. validate receipts;
10. upload sanitized acceptance artifacts;
11. re-check production branch baseline;
12. explicitly state no production deploy/merge occurred.

Missing required external configuration must produce `BLOCKED_EXTERNAL`, never a synthetic PASS.

## Task 10 — Real external Render/R2 execution

Run the workflow against the isolated Render service and disposable R2 namespace when credentials are available.

Required real evidence:

- deployment boot at exact feature SHA;
- active v6.3 tool surface;
- R2 generation append/restore roundtrip;
- candidate cold-crash recovery across instance replacement;
- opportunity snapshot and anchor gate preservation;
- PVC synthetic demand-expansion result;
- sanitized receipts verified with zero blockers.

If credentials or the external service are unavailable, record the gate as externally blocked and stop before production readiness.

## Task 11 — Release evidence integration

**Files**
- Modify existing v6.3 release-evidence assembler/gate tests only after Task 10 is real GREEN.

Require the real Render/R2/PVC receipt as a production-readiness dependency. Reference/local/mock execution is insufficient.

Only after this gate, full regressions, and production-branch safety checks are GREEN may the project proceed to the explicit merge/release decision. This task itself still does not merge production.
