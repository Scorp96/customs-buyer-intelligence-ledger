# CBI v6.4 Durable Backup and WAL Audit Hardening Design

## Status

Approved for implementation on 2026-09-09.

## Purpose

Close two production-safety gaps without weakening CBI evidence, route, CRM, outreach, WAL, or object-store safety semantics:

1. Make `backups-v61` history durable across Render ephemeral restart/deploy cycles by replicating immutable backup snapshots to the existing S3-compatible/R2 backend.
2. Add a sanitized, read-only WAL audit surface so terminal `COMMITTED_ERROR` entries can be classified without exposing raw request payloads, idempotency keys, credentials, or mutable state.

This work must not mutate production data, auto-sync CRM, send outreach, lower route-admission rules, or change C279 authority/route evidence.

## Baseline and lineage

Implementation branch starts from current integrated v6.4 candidate `00f30d783c1609a65c25e3e2c0548ed485a1d4cc` (`cbi-v64-release-candidate-integrated-currentprod-58c3120c`).

The previously verified performance candidate `768b53eb8ed0166943acaac3ab804ee20b98e148` diverged from that lineage at `17f4fe160c0908a602224eab95d172ba4eb753c6`. The new branch must preserve the `00f30d...` route/identity/current-production lineage and semantic-forward-port only the already verified request-scoped snapshot and stable load-acceptance behavior. Do not merge the historical branch wholesale.

## Architecture

### 1. Hot runtime state remains unchanged

The current object-store CAS generation remains responsible for hot durable runtime state. Its state archive and `current.json` pointer keep their existing split-brain semantics.

`backups-v61` MUST NOT be recursively embedded in every hot object-state generation. This avoids archive amplification, backup-history coupling to every mutation, and changing current CAS semantics.

### 2. Dedicated immutable backup namespace

Reuse the existing stdlib-only `S3CompatibleClient` and the same configured private object store. Add a dedicated backup-replication component with a namespace separate from object-state generations, conceptually:

```
<prefix>/backups-v61/snapshots/<snapshot_id>-<archive_sha256>.tar.gz
<prefix>/backups-v61/manifests/<snapshot_id>.json
```

Snapshot archives are immutable. Uploads use `If-None-Match: *`. A retry with identical bytes is idempotent success; an existing object under the same immutable key with different bytes fails closed.

The manifest is also immutable and contains only non-secret integrity metadata required to rediscover and verify the snapshot after restart/deploy.

### 3. Local snapshot creation remains authoritative for mutation ordering

Existing backup-before-mutation semantics remain unchanged. The local backup must be completed first. External replication is then required for the snapshot to satisfy v6.4 durable-retention evidence.

A failure to replicate MUST NOT silently mark retention verified. The mutation policy remains fail-closed wherever the existing backup contract requires a durable pre-mutation snapshot.

### 4. Cross-instance discovery

On fresh process startup or health evaluation, the backup-replication component can list/read only its dedicated prefix and produce a read-only external snapshot inventory. The latest externally durable snapshot is derived deterministically from manifest metadata, not from mutable local state.

The runtime health view should distinguish:

- local latest snapshot
- external latest snapshot
- external replication configured
- latest local snapshot externally replicated
- persistence mode (`OBJECT_STORE_REPLICATED` when verified)

No credentials, signed URLs, raw secret environment values, or backup payload contents may be returned.

### 5. Restore isolation

External backup replication is not an automatic live-state restore path. Any backup restore remains explicitly isolated and MUST NOT overwrite the live runtime root automatically. Existing hot object-state restore behavior remains separate.

### 6. WAL terminal audit surface

Add a read-only runtime method/tool:

```
get_mutation_wal_audit
```

Input supports bounded filtering such as terminal status and limit. The v6.4 production use case is `COMMITTED_ERROR` classification.

Returned rows may include only sanitized operational metadata:

- sequence/index if already non-secret
- tool name
- request SHA-256
- state version before
- prepared timestamp
- completed timestamp
- terminal status
- error type
- sanitized/truncated error message or normalized error code

The surface MUST NOT return:

- idempotency keys
- raw request arguments
- raw mutation result payloads
- authorization headers
- bearer tokens
- API keys
- passwords/secrets
- environment values
- contact route values solely because they appeared in an error message

The implementation must be read-only and must not alter WAL replay/idempotency behavior.

## Performance-forward-port constraint

Before the new production-safety features are judged release-ready, preserve the previously verified performance behavior from `768b53...` on top of the `00f30d...` lineage:

- one fully verified session read can be reused inside one request scope only
- cached material is deep-copied to consumers
- snapshot mutation fails closed
- no cross-request cache
- no-store/mixin compatibility remains valid
- state-query acceptance uses five warm samples, median `< 0.5s`, warm max `< 1.0s`, invalid timing samples fail closed

## Error handling

### Backup replication

Fail closed on:

- invalid snapshot identifiers
- archive hash mismatch
- manifest hash mismatch
- immutable-key content mismatch
- object-store request failure when durability is required
- malformed external manifest
- path traversal/archive member violations
- cross-prefix discovery attempts

Pruning is best-effort only for objects already outside the retention set; it must never delete the currently referenced/latest accepted snapshot during a failed verification cycle.

### WAL audit

Fail closed on malformed limits/filters. Sanitize before returning. Unknown record shapes are represented as safe audit errors or omitted with a diagnostic count; never return the raw row as fallback.

## Tests and acceptance

### Backup RED/GREEN contract

The test suite must prove:

1. Local snapshot with no external replica does not satisfy v6.4 retention verification.
2. First immutable upload succeeds.
3. Retrying identical snapshot bytes is idempotent.
4. Same immutable object key with different bytes fails closed.
5. A fresh runtime/client can rediscover the same snapshot ID from the object store.
6. Restart/deploy evidence preserves the same accepted snapshot ID.
7. Hot object-state payload inventory still excludes `backups-v61`.
8. Backup restore target remains isolated and cannot automatically overwrite live root.
9. Health exposes durable-replication status without credentials.
10. `backup_retention_evidence_v64.verified` becomes true only with a verified external durable snapshot.

### WAL audit RED/GREEN contract

The test suite must prove:

1. `COMMITTED_ERROR` rows are visible through the audit method.
2. Terminal success/error filtering is bounded and deterministic.
3. No raw idempotency key or request arguments are returned.
4. Secret-like material in error text is redacted/truncated.
5. The call performs no WAL mutation and does not change replay behavior.
6. Invalid limits/filters fail closed.
7. MCP schema/transport exposes only the read-only tool.

### Regression gates

Required before merge/promotion:

- full unittest regression
- Linux Python 3.10 / 3.11
- Windows Python 3.10 / 3.11 with pinned `tzdata==2026.3`
- privacy scan
- MCP protocol/schema compatibility
- performance acceptance
- isolated object-store backup restart/deploy acceptance
- production branch and Render remain unchanged during development

## Success criteria

The feature is complete only when all of the following are true:

- external backup history survives a fresh instance and is independently verifiable
- local ephemeral backup alone can never produce `backup_retention_verified=true`
- hot object-state CAS semantics remain unchanged
- `get_mutation_wal_audit` can classify terminal failures without exposing sensitive material
- all regression, privacy, MCP, Windows/Linux, and performance gates pass on one exact SHA
- no production mutation, CRM write, or outreach send occurred during implementation/acceptance

## Non-goals

- Do not relax C279 route admission.
- Do not fabricate/upgrade company contact claims into canonical routes.
- Do not modify current-authority policy.
- Do not auto-sync CRM.
- Do not send outreach.
- Do not replace the existing object-state CAS mechanism.
- Do not add boto3 or a second cloud SDK solely for backups.
