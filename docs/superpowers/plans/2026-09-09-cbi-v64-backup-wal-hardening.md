# CBI v6.4 Backup Durability and WAL Audit Hardening — Implementation Plan

> **Status note (2026-09-10):** Tasks 1–7 have been implemented on the isolated hardening branch. Task 7 now includes a side-effect-free backup-retention acceptance runner plus focused contract tests. Exact-SHA release verification and live current-cloud acceptance remain separate gates; no Production Ready claim follows from this document alone.

## Approved architecture

The implementation preserves the user-approved boundaries:

- keep the existing hot Runtime object-state CAS unchanged;
- replicate backup snapshots into an independent immutable R2/S3 namespace;
- reuse the existing object-store client and credentials rather than introduce a second cloud SDK/CAS;
- keep restore targets isolated and non-live;
- expose terminal mutation WAL history only through an allowlisted, sanitized, read-only audit surface;
- never weaken C279 route admission or substitute synthetic evidence for authoritative current-cloud acceptance.

## Completed implementation sequence

### Task 1 — Request-scoped verified session snapshot

Completed. One verified durable read is reused only within a request; there is no cross-request cache and corruption revalidation remains fail-closed.

### Task 2 — Stable state-query performance protocol

Completed. Acceptance uses five warm samples, median < 0.5s, max < 1.0s, and rejects invalid measurements.

### Task 3 — Immutable backup object-store replica

Completed. Backup archives and manifests use an independent immutable namespace. Identical retries are idempotent; conflicting content fails closed. Hot object-state `current.json` / generation semantics are unchanged.

### Task 4 — Runtime backup retention integration and production wiring

Completed. `ProductionBackupRecoveryManager` accepts an external replica. A local snapshot must be durably replicated before the protected mutation path continues. Fresh instances can discover `durable_latest` even when their local ephemeral backup directory is empty. Production wiring reuses the existing R2/S3 client and prefix.

### Task 5 — Sanitized terminal mutation WAL audit

Completed. The audit projection is read-only and allowlisted. It excludes idempotency keys, raw arguments/results, resource snapshots, route data, tokens, secrets and credentials; error text is sanitized.

### Task 6 — MCP exposure

Completed. `get_mutation_wal_audit` is exposed as a production-adapter read-only tool and is not added to the mutating tool set. The core `CBI_MCP_TOOL_NAMES` contract remains unchanged.

### Task 7 — Backup restart/deploy acceptance runner

Completed in code and deterministic CI.

Files:
- `scripts/run_v64_backup_retention_acceptance.py`
- `tests/test_v64_backup_retention_acceptance.py`
- `.github/workflows/cbi-v64-backup-wal-tdd.yml`
- `.github/workflows/cbi-v64-backup-wal-release-gate.yml`

The runner consumes sanitized observations only:
- `pre_deploy_health`
- `post_restart_health`
- `post_deploy_health`
- production source snapshot SHA-256
- persistence mode
- external snapshot locator
- observation time

It does not call Render, object storage, or production Runtime itself. It reuses `build_backup_retention_evidence()` as the policy owner and fails closed unless all three observations prove a verified durable external snapshot and the same snapshot identity survives restart and deploy. Local-only/ephemeral modes, missing replication, snapshot identity drift, invalid source SHA, and restore-safety regressions fail acceptance.

The focused contract covers seven cases: successful preservation, missing external snapshot after restart, changed snapshot after deploy, local-only mode, incomplete external verification, unsafe restore behavior, and invalid source SHA.

## Current verification boundary

Deterministic code/CI GREEN is necessary but not sufficient for Production Ready. A separate authoritative current-cloud orchestration must still capture real pre-restart, fresh-instance, and post-deploy observations from an environment whose durable backup namespace is demonstrably the intended production lineage. That live orchestration must not weaken production isolation, guess credentials, or treat the historical v6.3 acceptance service's different R2 state as production evidence.

C279 authoritative route admission remains independent and must not be weakened or satisfied by synthetic data.
