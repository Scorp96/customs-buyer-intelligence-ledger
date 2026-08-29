# CBI v6.1 byte-read-only Canonical preflight

## Why this exists

`audit-file --commit` ultimately calls the WAL-guarded production
`resolve_or_create_account` mutation. That is the correct write path, but it is
not an appropriate preview path: the v6.1 MCP adapter classifies that tool as a
mutation and creates a mutation-WAL intent even when `create_if_missing=false`.

Constructing a normal `UnifiedRuntime` is also not a byte-read-only diagnostic:
its compatibility constructors are allowed to create the configured session,
canonical and pending directories.

Therefore the pre-commit identity diagnostic is a separate script:

```text
scripts/cbi_canonical_preflight.py
```

It never constructs `UnifiedRuntime`, never calls the production MCP adapter and
never invokes the normal hash-chain lock-file writer.

## Command

```powershell
python scripts/cbi_canonical_preflight.py C:\PrivateInputs\buyer.json
```

When an already reviewed Account ID is known, supply it as an exact constraint:

```powershell
python scripts/cbi_canonical_preflight.py `
  --requested-account-id C157 `
  C:\PrivateInputs\buyer.json
```

An explicit or discoverable V6 session root is required. On Windows the same
standard V6 production root used by `scripts/cbi.py` is discovered automatically
unless `CBI_SESSION_ROOT` overrides it.

## Read-only implementation

The preflight:

1. reuses the customs normalization/country-resolution code from `scripts/cbi.py`;
2. determines the canonical registry path from the V6 session root and
   `CBI_CANONICAL_ROOT` override contract;
3. reads `accounts.jsonl` without constructing `HashChainLog`, therefore without
   creating its lock file or parent directories;
4. mechanically validates every canonical hash-chain event (`seq`, `prev_hash`,
   `event_hash`);
5. reads existing `INV-*.jsonl` headers through the same session-header semantics
   used by the production Canonical Registry;
6. reuses `CountryAwareCanonicalRegistry.resolve()` for the actual identity
   decision;
7. hashes the exact canonical/session files in its read set before and after;
8. withholds the resolution and returns `CONCURRENT_STATE_CHANGE` if those files
   changed during the check.

The command emits all three guarantees as false:

```text
runtime_mutation_performed = false
wal_mutation_performed = false
persistent_write_performed = false
```

and reports `read_set_unchanged=true` only when the before/after file hashes are
identical.

## Resolution results

### Existing Runtime Account

```text
status = MATCHED
recommendation = EXISTING_RUNTIME_ACCOUNT_MATCHED
```

A returned exact requested C-number is strong evidence that the Runtime already
knows the Account. It does not by itself prove that every external CRM row is
correct or current.

### No Runtime match, no requested C-number

```text
status = NOT_FOUND
recommendation = NO_RUNTIME_MATCH_CHECK_CRM_BEFORE_CREATE
```

This is deliberately **not** permission to create. Runtime `NOT_FOUND` says only
that the local Canonical Registry/session headers did not resolve the candidate.
An external CRM/workbook may still already contain the customer.

### Requested C-number is absent

```text
status = NOT_FOUND
recommendation = REQUESTED_ID_NOT_IN_RUNTIME_RECONCILE_BEFORE_COMMIT
```

Do not silently allocate a different C-number. Reconcile whether the reviewed
external C-number should be bound/imported into the Runtime before committing an
audit.

### Ambiguous identity

```text
status = AMBIGUOUS_MATCH
recommendation = BLOCK_COMMIT_IDENTITY_REVIEW_REQUIRED
```

No automatic merge/create should occur until the conflicting legal identity is
resolved.

### Concurrent state change

```text
status = CONCURRENT_STATE_CHANGE
recommendation = RETRY_READ_ONLY_PREFLIGHT_BEFORE_COMMIT
```

The command refuses to present a stale single-snapshot resolution when another
process changed the canonical/session read set during the check.

## Relationship to customs preview

The normal sequence for an existing production environment is:

```text
1. cbi.py audit-file buyer.json
   -> customs normalization only; no Runtime state

2. cbi_canonical_preflight.py buyer.json
   -> byte-read-only Runtime identity check; no WAL

3. compare any known CRM C-number with the preflight result

4. only after identity reconciliation:
   cbi.py audit-file buyer.json --commit
```

If a known CRM C-number is not represented in the Runtime, stop between steps 3
and 4 and reconcile identity first. Do not create a second Account merely because
the Runtime and CRM have not yet been synchronized.

## Privacy

Real customer/customs JSON remains local/private. The public repository and
GitHub Actions contain only synthetic fixtures. The preflight output should be
treated as operational metadata and does not need to be committed to Git.
