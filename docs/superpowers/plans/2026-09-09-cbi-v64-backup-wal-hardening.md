# CBI v6.4 Durable Backup and WAL Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make backup history durable across ephemeral Render restart/deploy cycles and add a sanitized read-only mutation-WAL audit surface, while preserving the current v6.4 route/identity lineage and previously verified state-query performance behavior.

**Architecture:** Keep hot object-state CAS unchanged. Replicate completed backup snapshots into a separate immutable prefix using the existing `S3CompatibleClient`, expose only durable-retention metadata in health/evidence, and add a bounded read-only WAL audit projection that sanitizes terminal error records. Forward-port the verified request-scoped session snapshot and stable performance protocol onto the current integrated candidate before release validation.

**Tech Stack:** Python stdlib, existing CBI file-backed runtime, existing S3-compatible/R2 client, GitHub Actions, unittest.

**Spec:** `docs/superpowers/specs/2026-09-09-cbi-v64-backup-wal-hardening-design.md`

## Global Constraints

- Development base is `00f30d783c1609a65c25e3e2c0548ed485a1d4cc`; do not write production branch.
- Preserve current route/identity semantics from the `00f30d...` lineage.
- Semantic-forward-port only the previously verified performance behavior from `768b53eb8ed0166943acaac3ab804ee20b98e148`; do not merge that historical branch wholesale.
- Hot object-state CAS archives MUST continue to exclude `backups-v61`.
- Reuse the existing stdlib-only `S3CompatibleClient`; do not add boto3 or another cloud SDK.
- Backup restore MUST remain isolated and MUST NOT automatically overwrite live runtime state.
- `get_mutation_wal_audit` is read-only and MUST NOT expose idempotency keys, raw arguments/results, credentials, bearer/API tokens, passwords/secrets, environment values, or contact route values leaked through errors.
- No production data mutation, CRM sync, or outreach send is permitted during development or acceptance.
- Windows CI installs pinned `tzdata==2026.3`.

---

### Task 1: Forward-port verified request-scoped session snapshot

**Files:**
- Modify: `unified_runtime/core.py`
- Modify: `unified_runtime/research_orchestration_hardening.py`
- Create: `tests/test_v64_request_scoped_verified_snapshot.py`

**Interfaces:**
- Produces: `SessionStore.verified_read_snapshot(investigation_id: str)` context manager.
- Produces: request-scoped `SessionStore.read()` reuse with deep-copy isolation.
- Consumed by: `V61ResearchOrchestrationHardeningMixin.get_account_state()`.

- [ ] **Step 1: Write failing request-scope tests**

Create tests that require one underlying verified durable read for repeated derived reads inside one `get_account_state` request, require a second durable read on the next request, verify deep-copy isolation, verify mutation detection fails closed, and verify a runtime/mixin without `store.verified_read_snapshot` still works.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_v64_request_scoped_verified_snapshot -v
```

Expected: FAIL because current `00f30d...` lineage lacks the full verified snapshot context-manager behavior.

- [ ] **Step 3: Implement the minimal snapshot cache in `core.py`**

Forward-port the already verified semantics:

```python
_ACTIVE_VERIFIED_SESSION_SNAPSHOTS: ContextVar[
    dict[tuple[int, int | None, int, str], tuple[list[dict[str, Any]], str]] | None
]
```

Key by thread id + asyncio task id + store id + investigation id. `verified_read_snapshot()` must perform one verified `read()`, deep-copy it, store a digest, and fail closed if cached material mutates before context exit. `read()` may reuse only the scoped snapshot and always returns a deep copy.

- [ ] **Step 4: Wrap only one derived account-state request**

In `research_orchestration_hardening.py`, split the current method into:

```python
def get_account_state(...):
    ...

def _get_account_state_derived_view(...):
    ...
```

Use `store.verified_read_snapshot(investigation_id)` only when present; otherwise preserve compatibility.

- [ ] **Step 5: Run focused tests and existing route tests**

```bash
python -m unittest \
  tests.test_v64_request_scoped_verified_snapshot \
  tests.test_v64_route_promotion_safety \
  tests.test_v61_research_orchestration_hardening -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add unified_runtime/core.py unified_runtime/research_orchestration_hardening.py tests/test_v64_request_scoped_verified_snapshot.py
git commit -m "perf(v64): forward-port request-scoped verified snapshots"
```

---

### Task 2: Forward-port stable state-query performance acceptance

**Files:**
- Modify: `scripts/run_v6_load_acceptance.py`
- Modify: `tests/test_v61_load_acceptance.py`

**Interfaces:**
- Produces: `evaluate_state_query_samples(cold_seconds: float, warm_samples_seconds: list[float]) -> dict[str, Any]`.
- Constants: `STATE_QUERY_WARM_SAMPLES = 5`, `STATE_QUERY_TAIL_SECONDS = 1.0`.

- [ ] **Step 1: Write failing protocol tests**

Add tests proving exactly five warm samples are required, NaN/inf/negative values fail closed, median must be `< 0.5`, warm max must be `< 1.0`, and a valid sample set returns both median/tail pass booleans.

- [ ] **Step 2: Run test and verify RED**

```bash
python -m unittest tests.test_v61_load_acceptance -v
```

Expected: FAIL because the current script still uses a single timing sample.

- [ ] **Step 3: Implement the stable protocol**

Add `math` and `statistics`; evaluate five warm samples; keep the existing target at `0.5s`; add a strict `1.0s` warm-tail bound; invalid samples fail closed. `run_smoke()` reports cold timing separately and uses warm median for `state_query_seconds`.

- [ ] **Step 4: Run focused performance tests**

```bash
python -m unittest tests.test_v61_load_acceptance -v
python scripts/run_v6_load_acceptance.py --smoke --enforce-targets
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_v6_load_acceptance.py tests/test_v61_load_acceptance.py
git commit -m "perf(v64): restore stable state-query acceptance"
```

---

### Task 3: Add immutable external backup replication component

**Files:**
- Create: `unified_runtime/backup_object_store_v64.py`
- Modify: `mcp/object_store_persistence.py` only if a small reusable helper is required; do not change current object-state archive/pointer semantics.
- Create: `tests/test_v64_backup_object_store.py`

**Interfaces:**
- Produces: `BackupObjectStoreReplica` constructed from existing `S3CompatibleClient` and a bounded prefix.
- Produces: `replicate_snapshot(snapshot_dir: Path, snapshot_id: str) -> dict[str, Any]`.
- Produces: `list_snapshots() -> list[dict[str, Any]]`.
- Produces: `latest_snapshot() -> dict[str, Any] | None`.

- [ ] **Step 1: Write RED tests for immutable upload and discovery**

Tests must cover first upload, identical retry idempotence, conflicting immutable bytes fail closed, malformed snapshot id fail closed, fresh client rediscovery, manifest/archive SHA verification, and prefix isolation.

- [ ] **Step 2: Run and verify RED**

```bash
python -m unittest tests.test_v64_backup_object_store -v
```

Expected: FAIL because `BackupObjectStoreReplica` does not exist.

- [ ] **Step 3: Implement the minimal replica**

Use existing `S3CompatibleClient.put(..., if_none_match=True)`, `get()`, `head()`, and `list_keys()`. Build a deterministic tar.gz archive of one snapshot directory with safe relative paths, compute SHA-256, and write immutable archive + immutable JSON manifest under the dedicated backup prefix. On `ObjectStoreConflict`, identical bytes are idempotent success; different bytes raise `ObjectStorePersistenceError`/a v6.4 backup-specific subclass.

- [ ] **Step 4: Verify GREEN**

```bash
python -m unittest tests.test_v64_backup_object_store -v
```

Expected: PASS.

- [ ] **Step 5: Confirm hot payload inventory remains unchanged**

```bash
python -m unittest tests.test_v63_object_store_recovery_state tests.test_v63_explicit_runtime_payload_inventory -v
```

Expected: PASS; `backups-v61` is still excluded from the hot state archive.

- [ ] **Step 6: Commit**

```bash
git add unified_runtime/backup_object_store_v64.py tests/test_v64_backup_object_store.py mcp/object_store_persistence.py
git commit -m "feat(v64): add immutable R2 backup replication"
```

---

### Task 4: Integrate external backup durability with backup manager and health

**Files:**
- Modify: `unified_runtime/backup_recovery_hardened.py`
- Modify: `mcp/server_v61_backup_recovery.py`
- Modify: `unified_runtime/backup_retention_evidence_v64.py` only if needed to consume the verified runtime health shape.
- Modify/Create: `tests/test_v61_backup_recovery.py`
- Create: `tests/test_v64_backup_retention_runtime.py`

**Interfaces:**
- Consumes: `BackupObjectStoreReplica` from Task 3.
- Produces health fields for local/external latest snapshot and replication verification.

- [ ] **Step 1: Write RED integration tests**

Require that a locally completed snapshot without external replica does not satisfy durable retention; a successfully replicated snapshot does; a fresh manager can rediscover the same external snapshot after local backup root starts empty; restore remains isolated; health never exposes credentials.

- [ ] **Step 2: Run RED tests**

```bash
python -m unittest tests.test_v64_backup_retention_runtime tests.test_v61_backup_recovery -v
```

Expected: FAIL on external durability fields/behavior.

- [ ] **Step 3: Wire the replica after local snapshot completion**

Instantiate the replica from existing object-store environment/config when R2/S3 mode is enabled. Preserve local snapshot ordering. Mark durable retention verified only after immutable external verification succeeds.

- [ ] **Step 4: Extend health safely**

Expose only sanitized metadata such as:

```python
{
  "external_replication_configured": True,
  "external_latest_snapshot_id": "...",
  "latest_local_snapshot_replicated": True,
  "backup_root_persistence_mode": "OBJECT_STORE_REPLICATED"
}
```

Never return credentials or signed URLs.

- [ ] **Step 5: Verify integration and existing backup behavior**

```bash
python -m unittest \
  tests.test_v64_backup_object_store \
  tests.test_v64_backup_retention_runtime \
  tests.test_v61_backup_recovery \
  tests.test_v64_stream_b_semantic_forward_port -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add unified_runtime/backup_recovery_hardened.py mcp/server_v61_backup_recovery.py unified_runtime/backup_retention_evidence_v64.py tests/test_v61_backup_recovery.py tests/test_v64_backup_retention_runtime.py
git commit -m "feat(v64): require durable external backup retention"
```

---

### Task 5: Add sanitized mutation-WAL audit projection

**Files:**
- Modify: `unified_runtime/core.py` or the existing WAL mixin owning `_mutation_wal_status()`; keep responsibility with the current WAL owner.
- Create: `tests/test_v64_mutation_wal_audit.py`

**Interfaces:**
- Produces: `get_mutation_wal_audit(arguments: dict[str, Any]) -> dict[str, Any]`.

- [ ] **Step 1: Write RED tests**

Build real WAL terminal rows through existing mutation/WAL test helpers. Require `COMMITTED_ERROR` filtering, bounded deterministic limit, stable terminal ordering, secret redaction in messages, absence of idempotency keys/raw arguments/raw results, and unchanged WAL bytes before/after the read.

- [ ] **Step 2: Run RED test**

```bash
python -m unittest tests.test_v64_mutation_wal_audit -v
```

Expected: FAIL because the method does not exist.

- [ ] **Step 3: Implement the read-only projection**

Validate `status` against a small terminal-status allowlist and `limit` against an explicit bounded range. Read the current WAL through the existing verified/read-only path. Return only allowlisted metadata. Redact common secret-bearing key/value patterns and cap error text length; never return raw row fallback.

- [ ] **Step 4: Verify no replay/idempotency change**

```bash
python -m unittest \
  tests.test_v64_mutation_wal_audit \
  tests.test_v61_adapter_wal \
  tests.test_v63_wal_contract -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add unified_runtime/core.py tests/test_v64_mutation_wal_audit.py
git commit -m "feat(v64): add sanitized read-only WAL audit"
```

---

### Task 6: Expose WAL audit as read-only MCP tool

**Files:**
- Modify: `unified_runtime/mcp_schema_v63.py`
- Modify: current MCP dispatch/registration owner (`mcp/server_v61.py` and/or current overlay determined from existing registration pattern).
- Modify: `tests/test_v63_mcp_schema.py`
- Create: `tests/test_v64_wal_audit_mcp.py`

**Interfaces:**
- Tool name: `get_mutation_wal_audit`.
- Input: optional bounded `status`, optional bounded `limit`.
- Output: sanitized audit envelope from Task 5.

- [ ] **Step 1: Write RED schema/dispatch tests**

Require the tool to appear exactly once, be classified read-only, reject mutation-only/idempotency parameters, dispatch to the runtime method, and preserve sanitized output.

- [ ] **Step 2: Run RED tests**

```bash
python -m unittest tests.test_v64_wal_audit_mcp tests.test_v63_mcp_schema -v
```

Expected: FAIL because tool is not registered.

- [ ] **Step 3: Register minimal read-only tool**

Follow current MCP schema/dispatch patterns. Do not add auth bypasses or mutation wrappers.

- [ ] **Step 4: Verify protocol compatibility**

```bash
python -m unittest tests.test_v64_wal_audit_mcp tests.test_v63_mcp_schema -v
python mcp/v6_protocol_test.py
python mcp/v61_hardening_protocol_test.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add unified_runtime/mcp_schema_v63.py mcp/server_v61.py tests/test_v63_mcp_schema.py tests/test_v64_wal_audit_mcp.py
git commit -m "feat(v64): expose sanitized WAL audit over MCP"
```

---

### Task 7: Add isolated backup restart/deploy acceptance

**Files:**
- Create: `scripts/run_v64_backup_retention_acceptance.py`
- Create: `tests/test_v64_backup_retention_acceptance.py`
- Create/Modify: branch CI workflow for v6.4 hardening validation.

**Interfaces:**
- Acceptance runner consumes pre-restart, fresh-instance, and post-deploy health/inventory inputs or runs the isolated local/object-store harness.
- Produces `cbi.v64-backup-retention-evidence.v1` compatible result.

- [ ] **Step 1: Write RED acceptance tests**

Require failure when no external snapshot exists, failure when snapshot IDs change unexpectedly, failure for ephemeral-only mode, success only when the same verified immutable external snapshot is rediscovered after restart/deploy, and isolated restore target remains non-live.

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_v64_backup_retention_acceptance -v
```

Expected: FAIL because runner does not exist.

- [ ] **Step 3: Implement the minimal acceptance runner**

Use the runtime/replica public interfaces rather than reading private object-store files directly. Emit no credentials or snapshot payloads.

- [ ] **Step 4: Verify GREEN**

```bash
python -m unittest tests.test_v64_backup_retention_acceptance -v
```

Expected: PASS.

- [ ] **Step 5: Add branch CI**

Matrix:

```yaml
os: [ubuntu-latest, windows-latest]
python: ['3.10', '3.11']
```

Install `tzdata==2026.3`, run full unittest discovery, privacy scan, compileall, protocol tests, performance acceptance, and focused backup acceptance.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_v64_backup_retention_acceptance.py tests/test_v64_backup_retention_acceptance.py .github/workflows/<v64-hardening-ci>.yml
git commit -m "ci(v64): gate durable backup and WAL hardening"
```

---

### Task 8: Full exact-SHA verification and release handoff

**Files:**
- No production code changes unless verification exposes a defect; any defect starts a new RED/GREEN cycle.

- [ ] **Step 1: Run full local/CI-equivalent suite**

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/privacy_scan.py
python -m compileall -q mcp unified_runtime scripts
python mcp/v6_protocol_test.py
python mcp/v61_hardening_protocol_test.py
python scripts/run_v6_load_acceptance.py --smoke --enforce-targets
python scripts/run_v64_backup_retention_acceptance.py
```

Expected: all PASS.

- [ ] **Step 2: Verify exact branch SHA and Git diff**

Confirm the final branch contains only approved spec/plan, semantic performance forward-port, backup durability implementation/tests, WAL audit implementation/tests, and CI/acceptance changes. Confirm no production branch write occurred.

- [ ] **Step 3: Verify GitHub Actions**

Require all four matrix jobs green on the exact final SHA. Inspect any failure logs instead of retrying blindly.

- [ ] **Step 4: Open/update a draft PR only after exact-SHA GREEN**

PR body must state:

- no production mutation occurred
- backup gate now has implementation-backed evidence rather than policy-only evidence
- WAL audit is read-only and sanitized
- C279 route gate remains unchanged
- Production Ready is not claimed until current-cloud backup acceptance and remaining C279 authoritative gate are closed

- [ ] **Step 5: Stop before production promotion**

Do not merge/promote merely because branch CI is green. Promotion requires a separate fresh production/Render/R2 gate review.
