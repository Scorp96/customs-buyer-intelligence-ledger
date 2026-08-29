# v5.4.1 to v6.1 Migration Plan

## Non-negotiable rule

Never mutate the v5 production data root in place.

## Procedure

1. Require a non-empty source session root and freeze a read-only SHA-256 inventory of its sessions plus the canonical registry and pending envelopes belonging to that exact root.
2. Create a distinct empty, non-overlapping target root.
3. Copy every `INV-*.jsonl` byte-for-byte to `target/sessions`.
4. Copy canonical and pending data to the target Runtime-owned directories.
5. Validate every source and copied v5 hash chain before adding new events.
6. Append one v6.1 `V6_RUNTIME_INITIALIZED` extension event to each copied session.
7. Re-read and validate every resulting chain.
8. Re-hash the source inventory and generate `V6_MIGRATION_REPORT.json` with before/after manifest digests, source/target paths, counts, errors, mutation flag and switch readiness.
9. Run compatibility, v6, crash, load, privacy and golden tests against the target.
10. Switch `CBI_SESSION_ROOT` only after external acceptance; restart the Desktop/tunnel and run health checks.
11. Keep the v5 source and pre-upgrade plugin backup for rollback.

## Legacy mapping

| v5 record | v6 handling |
|---|---|
| Investigation header | Preserved unchanged; v6 extension is appended |
| SourceAttempt | Preserved as historical execution proof; not auto-promoted into Claim support |
| Evidence/Information | Preserved; compiler may later create v6 Claim-bound observations with exact lineage |
| Peer receipt | Preserved; v6 Peer lifecycle is appended independently |
| Open Pivot | Preserved; materiality must be evaluated before Decision Saturation |
| Closure | Preserved as historical token; never recreated or treated as a fresh v6 Closure |
| CRM receipt | Preserved as immutable transaction proof |
| Pending receipt | Copied unchanged; host bundle queue remains a separate v6 channel |

## Rollback

Rollback changes only the configured active root and plugin cache selection. It does not rewrite either source or migrated logs. Any events created after the v6 switch remain in the v6 root for audit.

## Acceptance

- Source root hashes unchanged.
- Empty, missing or overlapping source/target roots are rejected before copying.
- Copied session count equals source count.
- All copied and extended chains validate.
- Canonical IDs are identical.
- No credential-like fields exist in target data.
- New Runtime reports v6 contract and all tools.
- A cold process can resume a migrated investigation.
- Failed migration leaves `switched=false`.
