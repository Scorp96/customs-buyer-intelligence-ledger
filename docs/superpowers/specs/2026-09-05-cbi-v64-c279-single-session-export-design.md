# CBI v6.4 C279 Single-Session Zero-Write Export Design

**Status:** Design approved in conversation on 2026-09-05. Written specification pending human review before implementation planning.

**Design baseline:** `cbi-v64-release-candidate-integrated-4733a9b3-a311a2a5` at `17f4fe160c0908a602224eab95d172ba4eb753c6`.

**Production baseline at design time:** `cbi-v6-cloud-runtime-20260901` at `a311a2a57ee43a1f1a3b2819bf28946566b05692`.

## 1. Goal

Obtain authoritative current-cloud evidence for one private C279 investigation without exporting the complete production runtime, copying production R2 credentials, mutating the production durable root, changing the MCP tool surface, or sending outreach.

The captured production input must be no broader than the one committed C279 session JSONL. The integrated candidate must then consume that JSONL in an isolated temporary root and prove readiness / closure / `prepare_outreach` semantics with `sends_message == false`.

This is temporary release diagnostics, not a product API.

## 2. Architecture decision

Implement a temporary fixed-path HTTP endpoint:

`POST /internal/v64/c279-session-export`

The endpoint returns one stable session snapshot only when every gate below passes:

1. `CBI_V64_C279_EXPORT_ENABLED=true`;
2. `CBI_V64_C279_EXPORT_EXPIRES_AT` is valid UTC and not expired;
3. expiry is no more than 30 minutes after process start;
4. the request presents the exact production static admin bearer in `CBI_REMOTE_BEARER_TOKEN`;
5. GitHub OAuth fallback is not accepted for this endpoint;
6. the URL contains no query string;
7. `Content-Type` is `application/json` and the parsed body equals `{}` exactly;
8. the server-side configured target id is valid;
9. the target is exactly one regular non-symlink JSONL directly under the already-bound production session root;
10. two direct byte reads are stable and identical;
11. the JSONL satisfies the existing append-only session header, sequence, previous-hash, and event-hash contract;
12. the observed tail sequence equals `CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ`;
13. the observed tail hash equals `CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH`;
14. the file size is within `CBI_V64_C279_EXPORT_MAX_BYTES`.

If any gate fails, no session bytes are returned.

## 3. Scope reduction rationale

A complete generation-669 runtime export is rejected because it would include unrelated investigations and WAL state. Existing runtime tests show that investigation state is reconstructed from the session event stream and that an otherwise empty temporary sessions root can support readiness, closure, and outreach preparation. The implementation must nevertheless prove **single-session sufficiency** with TDD before endpoint work begins.

Direct production R2 credentials in GitHub Actions are rejected because the available secret channel is acceptance-scoped, not a verified production read channel. A raw-session MCP tool is rejected because it would permanently change the product tool surface. An unauthenticated, OAuth-only, query-selectable, or general filesystem endpoint is rejected because it violates least privilege.

`SessionStore.read()` must not be used against the production root because it obtains a per-investigation lock and may create/touch a lock sidecar. The exporter performs direct read-only filesystem operations instead.

## 4. Hard security invariants

### 4.1 No private values in Git

Never commit:

- private C279 investigation id;
- private C279 tail sequence/hash values;
- C279 route/contact values;
- bridge JSON;
- production bearer;
- R2 access key/secret;
- production object keys.

Only variable names, schemas, implementation code, and synthetic fixtures may be public.

### 4.2 No caller-controlled target

The request cannot contain an investigation id, path, account id, filename, selector, or query string. The target comes only from server-side environment configuration.

### 4.3 Disabled means unavailable

Absent, false, invalid, or expired diagnostic configuration makes the route return `404 Not Found`. The feature is not advertised in MCP discovery, OAuth metadata, health, or ordinary capabilities.

### 4.4 Static admin bearer only

The diagnostic route compares the supplied bearer directly against the configured production `CBI_REMOTE_BEARER_TOKEN` using constant-time comparison. Ordinary GitHub OAuth authorization is insufficient for raw session export.

A secure caller channel for the production static admin bearer is a hard deployment prerequisite. If it does not exist, the route stays disabled.

### 4.5 Zero write to production durable state

The request must not write or touch:

- the production session root;
- parent live root;
- `.write.lock` files;
- mutation WAL;
- backup data;
- export/recovery manifests;
- R2 objects or generations;
- checkpoint state.

Only metadata inspection and direct byte reads of the one target file are allowed.

### 4.6 Stable snapshot

The implementation captures pre-read metadata, reads bytes twice, captures post-read metadata, and requires byte equality plus SHA-256 equality. Changes in size, file identity, modification metadata, resolution, or bytes cause HTTP 409 `SNAPSHOT_NOT_STABLE`.

This is a byte-stable observation window, not a distributed transaction.

### 4.7 Hash-chain validation

The snapshot must be strict UTF-8 JSONL and satisfy the current CBI session contract: valid first event/header, contiguous monotonic sequence, correct previous-hash linkage, and correct event hashes. Partial tails, malformed JSON, sequence defects, or hash defects fail closed.

Implementation may reuse existing pure hashing/canonicalization primitives, but it must not weaken runtime validation. If a new pure validator is introduced, tests must prove equivalence against existing `SessionStore` acceptance/rejection behavior for valid and corrupted synthetic fixtures.

### 4.8 Exact bridge commitment

The exporter accepts only the exact configured last-safe sequence and event hash. It must not trim a newer session, reconstruct an older state, repair a chain, or synthesize missing events.

### 4.9 Response bound

`CBI_V64_C279_EXPORT_MAX_BYTES` defaults to `2097152` (2 MiB). Values above `8388608` (8 MiB) are invalid and leave the route unavailable. Oversized targets return HTTP 413 `SNAPSHOT_TOO_LARGE` without payload.

### 4.10 Plaintext handling

Plaintext may exist only in process memory or caller temporary storage long enough to validate and encrypt it. Plaintext must never be logged, uploaded as an artifact, committed, attached to a PR, or stored in a release receipt.

## 5. Exact repository components

### 5.1 `mcp/c279_single_session_export_v64.py`

Owns the diagnostic configuration and filesystem snapshot logic. It must:

- parse the exact environment contract in section 6;
- validate expiry and size cap;
- derive the one allowed path from the bound session root;
- reject symlink/path escape/non-regular files;
- perform the two-read stability check without taking a live-root lock;
- validate JSONL/hash-chain semantics;
- verify exact tail commitment;
- return an in-memory result containing bytes and non-secret metadata only.

It has no R2 or networking responsibility.

### 5.2 `mcp/remote_transport.py`

Expose only the smallest reusable constant-time static-bearer authorization primitive needed by the diagnostic handler. Existing `/mcp` behavior must remain unchanged.

### 5.3 `mcp/chatgpt_oauth_transport.py`

Add an optional diagnostic POST callback to `serve()` / `main()` and route only the exact path above when the callback exists. The handler must:

- reject query strings with 404;
- require `application/json`;
- require body `{}` exactly;
- require the static admin bearer specifically;
- return `Cache-Control: no-store`;
- return `X-Content-Type-Options: nosniff`;
- never print response body/private identifiers;
- stay outside `/mcp`, OAuth metadata, and discovery.

When callback is `None`, behavior is byte-for-byte compatible at the HTTP contract level with the pre-feature service and the diagnostic path is 404.

### 5.4 `mcp/server_v61_remote.py`

Bind the exporter to the already-resolved `_RUNTIME.store.root`. Do not instantiate a second production Runtime and do not invoke R2 restore/sync for the export request.

Pass no diagnostic callback unless the complete server-side configuration is valid and unexpired.

### 5.5 `scripts/capture_v64_c279_single_session.py`

A standalone capture client. It receives the production base URL and static admin bearer only through its process environment and receives an X25519 recipient public key as a non-secret input.

It must:

1. POST `{}` to the fixed endpoint;
2. keep the plaintext response in memory / temporary storage only;
3. validate response schema, decoded byte length, snapshot SHA-256, and returned tail metadata;
4. encrypt the JSONL immediately;
5. write only an encrypted envelope plus sanitized metadata;
6. delete temporary plaintext before exit;
7. never echo the bearer or plaintext.

A GitHub Actions wrapper may call this script only after a secure production-bearer secret channel exists. The script itself is the authoritative capture behavior; GitHub Actions is not required by the architecture.

## 6. Exact environment contract

Server-side variables:

- `CBI_V64_C279_EXPORT_ENABLED`
- `CBI_V64_C279_EXPORT_EXPIRES_AT`
- `CBI_V64_C279_EXPORT_INVESTIGATION_ID`
- `CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ`
- `CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH`
- `CBI_V64_C279_EXPORT_MAX_BYTES`

Existing auth variable:

- `CBI_REMOTE_BEARER_TOKEN`

Rules:

- enable defaults false;
- expiry is mandatory when enabled;
- expiry is UTC and no more than 30 minutes after process start;
- investigation id, expected seq, and expected hash are mandatory when enabled;
- max bytes defaults to 2 MiB and may not exceed 8 MiB;
- incomplete or invalid configuration means callback `None` and route 404;
- target variables never auto-enable the feature.

Production values are supplied only during the separately approved deployment step and are never committed.

## 7. Exact response contract

Success is HTTP 200 JSON:

```json
{
  "schema": "cbi.v64-c279-single-session-export.v1",
  "snapshot_sha256": "<sha256-of-jsonl-bytes>",
  "byte_length": 12345,
  "tail_seq": 27,
  "tail_event_hash": "<synthetic-placeholder>",
  "payload_encoding": "base64",
  "payload": "<base64-jsonl>"
}
```

No filesystem path, object-store locator, credential, environment dump, or unrelated runtime inventory is included.

Error behavior:

- disabled / expired / invalid server config: 404;
- any query string: 404;
- wrong method while route is enabled/unexpired: 405;
- missing/invalid static bearer: 401;
- GitHub OAuth token that is not the exact static bearer: 401;
- wrong content type / malformed JSON / body other than `{}`: 400;
- unstable snapshot: 409 `SNAPSHOT_NOT_STABLE`;
- invalid chain: 409 `SNAPSHOT_INVALID`;
- tail commitment mismatch: 409 `SNAPSHOT_COMMITMENT_MISMATCH`;
- oversized target: 413 `SNAPSHOT_TOO_LARGE`.

All errors return no session bytes and no private expected/actual values.

## 8. Encrypted handoff contract

The capture client uses this exact envelope construction:

1. recipient has an X25519 private/public key pair generated outside production and outside the capture runner;
2. the capture process receives only the recipient public key;
3. capture generates a fresh ephemeral X25519 key pair;
4. shared secret is derived with X25519;
5. key material is derived with HKDF-SHA256 using a fresh 32-byte salt and info string `cbi-v64-c279-export-v1`;
6. payload is encrypted with ChaCha20-Poly1305 using a fresh 12-byte nonce;
7. associated data is ASCII `cbi.v64-c279-ciphertext.v1|<snapshot_sha256>`;
8. envelope contains schema, ephemeral public key, salt, nonce, snapshot SHA-256, and ciphertext/tag;
9. only the ciphertext envelope may be persisted or transferred.

The capture environment installs a pinned `cryptography` package version during implementation CI. The selected version and package hash are fixed in the implementation plan/lock step before execution; production does not gain this dependency.

## 9. Logging contract

Allowed:

- route invoked;
- authorized/rejected status;
- sanitized reason code;
- accepted byte count;
- existing deployment Git SHA.

Forbidden:

- payload/excerpts;
- investigation id;
- contact/route values;
- expected/actual tail hashes;
- Authorization header;
- R2 credentials/object keys.

No new health field advertises the feature.

## 10. TDD and verification gates

### Gate A — single-session sufficiency, before endpoint code

Witness RED, then prove GREEN:

1. create a synthetic full investigation whose state reaches the required route/closure path;
2. copy only its one JSONL into a completely new empty sessions root;
3. instantiate a fresh integrated `UnifiedRuntime` on that root;
4. resume/read state;
5. evaluate outreach readiness;
6. evaluate decision saturation as required;
7. evaluate closure;
8. call `prepare_outreach`;
9. assert prepared semantics and `sends_message == false`.

If other production durable components are semantically required, stop and redesign. Do not broaden production export automatically.

### Gate B — snapshot validator

Test valid acceptance plus missing file, symlink, path escape, non-regular file, malformed UTF-8, malformed JSON, invalid header, sequence gap/duplicate/order defect, previous-hash mismatch, event-hash mismatch, truncated tail, first/second-read race, metadata/file-identity race, oversized file, expected-seq mismatch, expected-hash mismatch, and exact commitment success.

### Gate C — auth/HTTP contract

Test 404 disabled/expired, 401 without exact static bearer, OAuth-only rejection, no-query requirement, exact `{}` body requirement, fixed error statuses, no-store headers, absence from discovery/OAuth metadata, and unchanged `/mcp`/`healthz` behavior.

### Gate D — zero live-root mutation

Snapshot full synthetic live-root inventory and file hashes before request; invoke exporter; prove inventory and hashes unchanged afterward and prove no `.write.lock` appeared.

### Gate E — encrypted capture

With synthetic data prove byte-identical decrypt, AEAD tamper rejection, plaintext never logged, plaintext artifact upload absent by construction, and ciphertext-only persisted output.

### Gate F — exact-SHA diagnostic regression

Exporter implementation lives on a temporary diagnostic branch derived from the exact production baseline. Its exact SHA must pass focused tests and the full relevant regression suite before any production deployment proposal.

The exporter is not merged into the final v6.4 release candidate. If C279 verifier/forward-port assets later change the candidate, permanent four-matrix release CI reruns on the new exact candidate SHA.

## 11. Production diagnostic flow

Implementation success does not authorize this section.

After a separate explicit production-deployment approval:

1. verify exact then-current production SHA and service health;
2. verify a secure caller channel for the exact production static admin bearer;
3. apply the reviewed temporary diagnostic code to the existing production deployment path without committing private values;
4. configure private target id, expected tail seq/hash, max bytes, expiry, and enable flag;
5. deploy and verify ordinary health/deployment identity;
6. call the endpoint only as needed to capture a stable committed snapshot;
7. immediately encrypt through the capture client;
8. disable the endpoint;
9. restore the ordinary production code tree by a new fast-forward revert/rollback commit, never a force reset;
10. redeploy and verify the endpoint is gone and `/mcp`/`healthz` are healthy;
11. decrypt only in an isolated verifier environment;
12. create a temporary session root containing only the JSONL;
13. verify source tail against the private bridge;
14. instantiate the integrated candidate runtime only on the isolated copy;
15. execute readiness / closure / `prepare_outreach`;
16. assert `sends_message == false`;
17. record sanitized evidence only;
18. verify the diagnostic read did not mutate production durable state or R2 generation.

The currently available Render connector cannot retarget the existing Docker service to a temporary branch and cannot inherit/read production secrets into a new Docker preview service. Therefore the pre-production package must show the exact auditable production Git/Render sequence rather than assuming a preview-service path exists.

## 12. Rollback and production Git history

If current Render capabilities remain unchanged, any temporary exporter deployment on the existing service must be represented by auditable fast-forward Git history from the exact production baseline. Removal is a new fast-forward revert/rollback commit whose tree restores ordinary production code.

Never force-reset production Git history. Never delete or rewrite production runtime state. Never use rollback as authorization to modify R2.

The exporter is temporary diagnostic code and is not part of the final v6.4 release candidate unless a later separately approved design changes that decision.

## 13. Repository governance

A dedicated production-branch ruleset remains a separate mandatory release gate. The desired ruleset protects `refs/heads/cbi-v6-cloud-runtime-20260901` with deletion protection, non-fast-forward protection, pull-request safeguards, and the existing four required release-regression contexts.

Exporter work must not weaken or bypass repository governance. Before any production diagnostic deployment, the review package must explicitly report the then-current production ruleset state.

## 14. Non-goals

This design does not:

- create a general investigation export/download API;
- add an MCP tool;
- export the complete runtime or WAL;
- copy production R2 credentials to GitHub Actions;
- authorize raw export with ordinary GitHub OAuth;
- repair/trim/rewrite production investigation state;
- send outreach;
- merge/promote the release candidate;
- permanently merge exporter code into the candidate;
- change branch rulesets;
- change readiness semantics;
- weaken hash-chain validation.

## 15. Acceptance criteria

All must be true:

1. single-session sufficiency is GREEN on a fresh isolated root;
2. only the configured one session can be exported;
3. caller target/path selection is impossible;
4. endpoint is unavailable by default and after expiry;
5. only exact production static admin bearer authorizes raw export;
6. live durable root bytes and inventory remain unchanged;
7. no live-root lock sidecar is created;
8. races/corruption/commitment mismatch fail closed;
9. no private C279 value or secret is committed/logged;
10. persisted handoff is AEAD ciphertext only;
11. isolated C279 proof reaches `prepare_outreach` and `sends_message == false`;
12. exact diagnostic SHA passes focused and full diagnostic regressions;
13. any later candidate change reruns permanent release CI on its exact SHA;
14. production deployment requires a separate explicit approval;
15. rollback is auditable fast-forward history, never force reset;
16. production ruleset remains a visible mandatory gate.

## 16. Implementation boundary

After written-spec approval, implementation planning must cover exactly these workstreams:

1. single-session sufficiency TDD gate;
2. stable snapshot validator;
3. static-admin-only optional HTTP hook;
4. production entrypoint/env binding;
5. capture client and exact AEAD envelope;
6. transport/security/no-mutation tests;
7. exact-SHA diagnostic regression;
8. pre-production deployment review package.

No production mutation occurs during implementation. Production deployment remains a separate explicit approval gate.
