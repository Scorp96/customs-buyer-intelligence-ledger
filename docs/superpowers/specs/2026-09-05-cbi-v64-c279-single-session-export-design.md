# CBI v6.4 C279 Single-Session Zero-Write Export Design

**Status:** Design approved in conversation on 2026-09-05. Written specification pending human review before implementation planning.

**Design baseline:** `cbi-v64-release-candidate-integrated-4733a9b3-a311a2a5` at `17f4fe160c0908a602224eab95d172ba4eb753c6`.

**Production baseline at design time:** `cbi-v6-cloud-runtime-20260901` at `a311a2a57ee43a1f1a3b2819bf28946566b05692`.

## 1. Purpose

CBI v6.4 needs an authoritative current-cloud regression for one private C279 investigation before promotion. The regression must prove that the integrated candidate can consume the current production investigation state in isolation and reach the expected outreach-readiness / closure / `prepare_outreach` semantics without sending a message.

The current production durable state is restored from R2, but the available automation surface does not provide a safe read-only production R2 credential channel, Render filesystem shell, Render environment-variable readback, or a Docker preview service that can inherit the production secrets. Creating a general production runtime export or moving production object-store credentials into another system would broaden the trust boundary unnecessarily.

This design therefore introduces the narrowest possible diagnostic path: while explicitly enabled for a short period, the production HTTP process may export exactly one precommitted C279 session JSONL from its already-bound session root. The caller cannot choose another investigation or filesystem path. The exporter performs no write to the live durable root and fails closed on any mismatch.

The feature is temporary release diagnostics. It is not a new product API, not a backup API, not a general investigation export feature, and not an MCP tool.

## 2. Decision

Use a **temporary, static-admin-bearer-authenticated, fixed-target HTTP POST endpoint** that returns one stable C279 session snapshot only when all of the following are true:

1. the diagnostic feature is explicitly enabled by environment configuration;
2. the configured expiration time has not passed;
3. the request presents the exact existing production static admin bearer credential;
4. GitHub OAuth user tokens and other alternate auth paths are not sufficient for this raw-session endpoint;
5. the endpoint receives no investigation selector, path selector, account selector, or other user-controlled export target;
6. the configured target investigation identifier is syntactically valid;
7. the target resolves to exactly one regular JSONL file directly under the already-bound production session root;
8. the file is not a symlink and cannot escape the session root;
9. two independent reads of the file are byte-for-byte identical and have identical SHA-256 digests;
10. the JSONL parses as a complete append-only CBI session and its event sequence / previous-hash / event-hash chain is valid under the existing runtime hashing contract;
11. the observed tail sequence and tail event hash exactly match the private C279 bridge commitment supplied through runtime environment configuration;
12. the response size is no greater than the configured limit, whose default is 2 MiB and whose implementation hard cap is 8 MiB.

If any condition fails, no session bytes are returned.

## 3. Why this approach

### 3.1 Rejected: export the complete production runtime root

The v6.4 regression only needs the investigation event stream for the C279 route / closure / outreach path. Existing runtime tests demonstrate that a `UnifiedRuntime` rooted at an otherwise empty sessions directory can derive readiness, closure, and outreach preparation from investigation state. A full generation archive would expose unrelated investigations and WAL state and therefore violates least privilege.

The implementation must still prove the single-session sufficiency assumption by TDD before any production diagnostic deployment. If that proof fails, implementation stops and the design is revisited; it must not silently widen the export scope.

### 3.2 Rejected: direct production R2 credentials in GitHub Actions

Production R2 credentials are deliberately kept outside Git. The available GitHub Actions secret inventory is known to contain isolated acceptance credentials, not a verified production R2 read credential. Moving or duplicating production object-store credentials solely for this regression would create a larger and more durable security boundary than the one-session diagnostic endpoint.

### 3.3 Rejected: MCP export tool

An MCP export tool would alter the public tool surface and runtime contract, creating a long-lived capability that does not belong to the business API. The C279 export is release diagnostics and must remain outside the MCP tool registry.

### 3.4 Rejected: ordinary GitHub OAuth authorization for raw export

The service's ordinary OAuth allowlist is suitable for the MCP surface, but a byte-for-byte private session export is a stronger diagnostic capability. The endpoint therefore requires the configured production static admin bearer specifically. An allowed GitHub OAuth identity alone must not authorize raw session export.

### 3.5 Rejected: unauthenticated or query-selectable HTTP export

The endpoint contains private investigation evidence. It must never be publicly selectable, enumerable, cacheable, or callable without the stronger diagnostic authorization boundary.

### 3.6 Rejected: `SessionStore.read()` against the live root

`SessionStore.read()` obtains a per-investigation write lock. Even though the logical operation is a read, lock acquisition may create or touch a lock sidecar under the live root. The exporter therefore must not call `SessionStore.read()` or any other helper that writes a lock, cache, checkpoint, journal, recovery receipt, manifest, or temporary file inside the live durable root.

## 4. Security invariants

These are hard requirements, not implementation suggestions.

### 4.1 No private evidence in Git

The repository must not contain the private C279 investigation identifier, tail hash, observed route values, bridge JSON, production bearer token, R2 access key, R2 secret, or any other private production evidence.

Only environment variable names, schemas, and synthetic fixtures may be committed.

### 4.2 No general target selector

The endpoint path is fixed. The request body is exactly the JSON object `{}`. A query string, non-empty object, array, scalar, form body, or target/path/account field is rejected.

The target investigation identifier and expected tail commitment come only from server-side environment configuration established during the separately approved deployment step.

### 4.3 Disabled means nonexistent

When the diagnostic configuration is absent, false, invalid, or expired, the export route returns `404 Not Found` and does not reveal whether the feature exists, was disabled, or expired.

The endpoint must not appear in MCP discovery, OAuth metadata, health payloads, or ordinary service capability descriptions.

### 4.4 Static admin bearer only

The endpoint must compare the supplied bearer against the configured production `CBI_REMOTE_BEARER_TOKEN` using constant-time comparison. The existing bearer length/startup requirements remain authoritative.

GitHub OAuth fallback, OAuth allowlisted users, anonymous mode, and acceptance-only bearer credentials must not authorize this endpoint.

A secure caller channel for the production static admin bearer must exist before production diagnostic deployment is approved. If no such channel is available, the endpoint remains disabled even if all code tests pass.

### 4.5 Zero write to the live durable root

The export request must not modify the production session root, parent live root, R2 state, WAL, manifests, lock files, backups, checkpoints, or recovery generations.

Permitted operations on the live session file are filesystem metadata inspection and direct byte reads only.

### 4.6 Stable snapshot or fail closed

The exporter must protect against racing a concurrent append. It must perform at least:

- canonical target-path validation;
- pre-read metadata capture;
- first byte read;
- second byte read;
- post-read metadata capture;
- byte equality and SHA-256 equality checks.

A change in bytes, size, file identity, modification metadata, target resolution, or any required stability signal causes rejection.

The design does not claim a distributed snapshot transaction. It deliberately accepts only a byte-stable observation window; otherwise the caller retries later.

### 4.7 Validate the append-only chain before release

The returned bytes must parse as strict UTF-8 JSON Lines with a valid CBI session header and monotonically contiguous sequence numbers. Every event must satisfy the existing previous-hash and event-hash contract. Truncation, a partial tail line, invalid JSON, duplicate/out-of-order sequence numbers, previous-hash mismatch, or event-hash mismatch causes rejection.

Implementation should reuse existing canonical hashing primitives where possible. If a new pure validator is needed, tests must demonstrate equivalence with the existing `SessionStore` acceptance/rejection semantics over valid and corrupted synthetic fixtures. Runtime safety semantics must not be weakened to accommodate the exporter.

### 4.8 Exact private commitment required

The validated snapshot tail must equal the private bridge commitment supplied through environment configuration:

- expected last-safe sequence;
- expected last-safe event hash.

A newer production tail, older tail, different investigation, or different hash is a hard mismatch. The exporter must not attempt to trim, reconstruct, mutate, repair, or synthesize the committed state.

### 4.9 Bounded response

`CBI_V64_C279_EXPORT_MAX_BYTES` defaults to 2 MiB. Values greater than 8 MiB are invalid and keep the route unavailable. A target file larger than the active limit is rejected rather than streamed.

### 4.10 No plaintext persistence downstream

The authorized diagnostic caller may hold plaintext only in process memory or runner temporary storage long enough to validate the response and encrypt it for transfer to the isolated verifier environment.

Plaintext session bytes must never be printed to GitHub Actions logs, uploaded as an artifact, committed, attached to a pull request, or included in a test receipt.

Any durable diagnostic artifact must be ciphertext only. Encryption must provide confidentiality and integrity using an authenticated-encryption construction. The decryption private key must never be present in the production service, GitHub repository, or GitHub Actions secret store used for the capture.

## 5. Proposed components

Exact names may change during implementation planning, but responsibilities must remain separated.

### 5.1 `mcp/c279_single_session_export_v64.py`

A focused diagnostic module with no networking responsibilities.

Responsibilities:

- parse and validate diagnostic environment configuration;
- validate expiry;
- derive the single allowed session path from the already-bound session root and server-side target id;
- reject symlinks / path escape / non-regular files;
- acquire a stable two-read byte snapshot without locking the live root;
- validate JSONL structure and hash chain;
- verify the expected private tail commitment;
- return a typed in-memory result containing bytes plus non-sensitive validation metadata.

It must not know R2 credentials and must not call object-store sync/recovery methods.

### 5.2 Remote HTTP transport integration

The existing production service uses `ChatGPTOAuthRequestHandler`, which extends the base remote MCP request handler. The diagnostic endpoint should be integrated as the smallest optional protected route in this existing HTTP stack.

The transport integration must:

- register no route when no diagnostic callback is supplied;
- accept only POST;
- reject any query string;
- require `Content-Type: application/json`;
- parse the request body and require it to equal `{}` exactly;
- authorize the request with the static production admin bearer only;
- set `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`;
- return a fixed diagnostic response schema;
- avoid logging response bodies or private identifiers;
- keep the endpoint outside `/mcp` and outside tool discovery.

The production entrypoint supplies the diagnostic callback only when valid, unexpired server-side configuration is present. Otherwise the handler behaves exactly as before.

### 5.3 Production entrypoint binding

`mcp/server_v61_remote.py` already verifies that the production Runtime is bound to the expected explicit durable session root. The exporter must use that same resolved root; it must not independently discover another root or object-store location.

The entrypoint must not instantiate a second production `UnifiedRuntime` for export and must not call R2 recovery to service the request.

### 5.4 Diagnostic response schema

The response contains only what the isolated consumer needs:

```json
{
  "schema": "cbi.v64-c279-single-session-export.v1",
  "snapshot_sha256": "<sha256-of-jsonl-bytes>",
  "byte_length": 12345,
  "tail_seq": 27,
  "tail_event_hash": "<synthetic-tail-hash>",
  "payload_encoding": "base64",
  "payload": "<base64-jsonl>"
}
```

The response must not echo filesystem paths, R2 keys, bearer data, unrelated environment values, or broader runtime inventory.

The example values above are synthetic placeholders. No real C279 value belongs in the repository.

## 6. Environment contract

The implementation may use names equivalent to:

- `CBI_V64_C279_EXPORT_ENABLED`
- `CBI_V64_C279_EXPORT_EXPIRES_AT`
- `CBI_V64_C279_EXPORT_INVESTIGATION_ID`
- `CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ`
- `CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH`
- `CBI_V64_C279_EXPORT_MAX_BYTES`

Rules:

- all are server-side only;
- no private value is committed to Git;
- enable defaults false;
- expiry is mandatory when enabled;
- expiry is UTC and must be no more than 30 minutes after process start;
- target id and expected commitment are mandatory when enabled;
- invalid configuration causes the route to remain unavailable;
- the diagnostic route must not auto-enable because a target variable happens to exist;
- maximum bytes defaults to 2 MiB and cannot exceed 8 MiB.

Enabling these variables on production is a separate high-impact production mutation and requires explicit approval after implementation, tests, CI, and security review are complete.

## 7. Request/response behavior

Fixed path:

`POST /internal/v64/c279-session-export`

The path is intentionally not parameterized.

### 7.1 Success

On successful static-admin authentication, enabled/unexpired configuration, exact `{}` request body, stable snapshot validation, and exact commitment match:

- return HTTP 200;
- return only the fixed response schema;
- include `Cache-Control: no-store`;
- do not write any durable state.

### 7.2 Unavailable / disabled / expired

Return HTTP 404 with an empty or generic body that does not distinguish disabled, expired, or unconfigured state.

### 7.3 Authentication failure

Return the existing bearer-auth HTTP 401 semantics for a missing/invalid static admin bearer. Do not fall back to GitHub OAuth for this route.

### 7.4 Invalid request shape

- any query string: HTTP 404;
- wrong method: HTTP 405 only when the feature is enabled and unexpired, otherwise 404;
- wrong content type, malformed JSON, or JSON value other than exactly `{}`: HTTP 400;
- no session bytes in any error response.

### 7.5 Snapshot changed during read

Return HTTP 409 with sanitized diagnostic code `SNAPSHOT_NOT_STABLE`. Do not return partial bytes.

### 7.6 Commitment mismatch or corrupt chain

Return HTTP 409 with a sanitized code from a fixed allowlist such as `SNAPSHOT_INVALID` or `SNAPSHOT_COMMITMENT_MISMATCH`. Do not return session bytes, identifiers, expected/actual hashes, or payload excerpts.

### 7.7 Oversized target

Return HTTP 413 with sanitized code `SNAPSHOT_TOO_LARGE` and no private payload.

## 8. Logging and observability

Allowed diagnostic log fields:

- feature route invoked;
- authorized / rejected boolean or generic status;
- stable snapshot accepted/rejected;
- sanitized failure reason code;
- byte count only after successful validation;
- deployment Git SHA already exposed by existing health logic.

Forbidden log fields:

- JSONL payload or excerpts;
- investigation id;
- route/contact values;
- expected or actual private tail hash;
- Authorization header;
- R2 credentials or object keys.

No new health field should advertise the export feature.

## 9. Test strategy

Implementation follows TDD. The first implementation work must produce a failing test before production code changes.

### 9.1 Gate A — single-session sufficiency (must pass before endpoint work)

Create a synthetic full-runtime fixture, obtain its session JSONL, copy **only that one JSONL** into a completely new empty session root, instantiate a fresh integrated `UnifiedRuntime`, and prove the required sequence:

1. resume/read committed state;
2. evaluate outreach readiness;
3. evaluate decision saturation as required by the fixture;
4. evaluate investigation closure;
5. call `prepare_outreach` on the isolated copy;
6. assert preparation semantics;
7. assert `sends_message == false`;
8. assert no unrelated sidecar/root data was required before fresh-runtime construction.

The isolated test root may create its own ordinary test lock files after construction; the invariant is that the exported production input consists of the single JSONL only.

If this fails because other durable components are semantically required, stop. Do not widen production export until the design is revisited and re-approved.

### 9.2 Gate B — stable snapshot validator

Synthetic tests must cover:

- valid session accepted;
- missing file;
- symlink rejected;
- path escape rejected;
- malformed UTF-8;
- malformed JSON line;
- missing/invalid session header;
- sequence gap/duplicate/out-of-order event;
- previous-hash mismatch;
- event-hash mismatch;
- truncated tail;
- bytes changed between first and second read;
- metadata/file identity changed between reads;
- byte limit exceeded;
- expected tail sequence mismatch;
- expected tail hash mismatch;
- exact commitment accepted;
- live root unchanged byte-for-byte and file-inventory-for-file-inventory.

### 9.3 Gate C — transport/auth contract

Tests must prove:

- disabled route returns 404;
- expired route returns 404;
- enabled route without auth returns 401;
- a valid static admin bearer reaches the callback;
- a GitHub OAuth-authorized identity that is not the static bearer does not reach the callback;
- any query string returns 404;
- request JSON other than exactly `{}` returns 400;
- success has `no-store` headers;
- route is absent from MCP discovery and OAuth metadata;
- existing `/mcp`, `/healthz`, OAuth, and discovery behavior remains unchanged.

### 9.4 Gate D — no live durable mutation

A test must snapshot the complete synthetic live-root inventory and content hashes before export, invoke the endpoint, and prove the complete inventory and hashes are unchanged afterward. This includes absence of a new `.write.lock` in the live session root.

### 9.5 Gate E — encrypted handoff client

The external diagnostic workflow must be tested with synthetic payloads to prove:

- plaintext is never echoed;
- plaintext artifact upload is impossible by workflow construction;
- encryption uses authenticated encryption;
- only ciphertext and sanitized metadata may leave runner temporary storage;
- decryption restores byte-identical JSONL in the isolated verifier environment.

The capture side receives only an ephemeral encryption public key. The corresponding private key remains outside production, the public repository, and the capture runner's secrets.

The workflow must fail closed if the production static admin bearer is unavailable through a secure caller channel.

### 9.6 Gate F — diagnostic exact-SHA regression

The exporter implementation must live on a temporary diagnostic branch derived from the exact production baseline. That diagnostic SHA must pass focused tests plus the full relevant regression suite before any production deployment is proposed.

The exporter is not intended to be merged into the final v6.4 release candidate. Therefore prior candidate release-CI evidence is not invalidated merely by building the diagnostic branch.

If separate C279 verifier/forward-port assets are later added to the release candidate, the permanent four-matrix release CI must rerun on that new exact candidate SHA.

## 10. Current-cloud C279 verification flow after implementation

After all synthetic gates are green and a separate production-deployment approval is granted:

1. establish a secure caller channel containing the exact production static admin bearer without exposing it in Git or chat output;
2. configure the private target id, expected tail seq/hash, expiry, maximum byte size, and explicit enable flag on the production service;
3. deploy the reviewed diagnostic implementation through the separately approved temporary production deployment procedure;
4. verify deployment identity and ordinary health before calling the endpoint;
5. invoke the fixed endpoint exactly once or only as needed to obtain a stable committed snapshot;
6. validate returned SHA / tail metadata without logging private values;
7. encrypt the snapshot immediately for handoff to the isolated verifier environment;
8. disable the export feature immediately after successful capture;
9. restore the ordinary production code tree through the approved fast-forward rollback/revert procedure;
10. verify the endpoint is gone/unavailable and ordinary `/mcp` and `/healthz` remain healthy;
11. reconstruct a temporary isolated session root containing only the exported JSONL;
12. validate source tail seq/hash against the private bridge;
13. instantiate the integrated candidate runtime only against the isolated copy;
14. execute C279 readiness / closure / `prepare_outreach` proof;
15. assert `sends_message == false`;
16. record only sanitized pass/fail evidence in release receipts;
17. verify production durable state and R2 generation were not mutated by the diagnostic read.

A successful diagnostic capture is evidence acquisition only. It does not authorize merge, production promotion, message sending, or ruleset changes.

## 11. Production deployment and rollback

Implementation completion does **not** authorize production deployment.

The currently available Render connector cannot retarget the existing Docker service to a temporary branch, cannot read or inherit production environment secrets into a new Docker preview service, and cannot provide a production filesystem shell. Therefore the implementation plan must not assume an isolated Render preview can access the current production durable state.

If those capabilities remain unchanged at deployment time, the only currently feasible production-code path is a controlled temporary deployment on the existing production service. That procedure requires its own explicit approval and must satisfy all of the following:

1. start from the exact then-current production branch head;
2. introduce the exporter as an auditable temporary fast-forward commit or commit set with no private values in Git;
3. require all designated CI checks before Render deploys the diagnostic tree;
4. enable the endpoint only through separate short-lived server-side environment configuration;
5. capture and encrypt the single committed session;
6. disable the endpoint;
7. restore the ordinary production code tree by a new fast-forward revert/rollback commit — never by force-resetting production history;
8. redeploy and verify ordinary health;
9. leave production durable state and R2 contents untouched.

Before this deployment the human approver must see:

- exact diagnostic implementation SHA;
- exact then-current production SHA;
- focused TDD results;
- full diagnostic regression results;
- security invariant review;
- proof that the endpoint is unavailable by default;
- proof that live-root export creates no write/lock side effect;
- secure static-admin-bearer caller readiness;
- exact Render environment mutations;
- exact Git/Render deployment sequence;
- exact revert/rollback sequence.

No rollback procedure may delete or rewrite production runtime state. No production Git history may be force-reset as part of this diagnostic lifecycle.

The exporter implementation is temporary diagnostic code and should not be merged into the final v6.4 release candidate unless a separate design explicitly changes that decision.

## 12. Interaction with the production branch ruleset blocker

This design does not solve repository administration. A dedicated production-branch ruleset remains a separate release gate.

The desired production ruleset should protect `refs/heads/cbi-v6-cloud-runtime-20260901` with the existing four release regression status contexts and the same core deletion / non-fast-forward / pull-request safeguards already used by the repository governance template.

No implementation of this exporter may weaken or bypass repository governance. If administration write capability is still unavailable, the ruleset blocker remains RED even if C279 proof becomes GREEN.

Because the temporary exporter deployment itself would mutate the production branch/service, the pre-production deployment review must explicitly call out the then-current ruleset state rather than treating it as an unrelated detail.

## 13. Non-goals

This design does not:

- expose a general investigation download API;
- add an MCP tool;
- export the complete production runtime root;
- export mutation WAL or unrelated investigations;
- move production R2 credentials into GitHub Actions;
- authorize raw session export via ordinary GitHub OAuth;
- repair or modify a production investigation;
- trim a newer investigation to an older bridge tail;
- send outreach;
- merge or promote the release candidate;
- permanently add exporter code to the release candidate;
- change GitHub branch rulesets;
- change CBI route-readiness semantics;
- weaken append-only hash-chain validation.

## 14. Acceptance criteria

The design is implemented successfully only when all are true:

1. single-session sufficiency is proven on a fresh isolated runtime root;
2. the exporter can return only the configured single target;
3. request-controlled target/path selection is impossible;
4. the endpoint is absent/unavailable by default and after expiry;
5. only the static production admin bearer authorizes raw export;
6. live durable root content and inventory are unchanged by export;
7. no live-root lock sidecar is created;
8. unstable/concurrent snapshots fail closed;
9. corrupt hash chains fail closed;
10. private tail commitment mismatch fails closed;
11. no private C279 values or secrets are committed or logged;
12. downstream handoff persists ciphertext only;
13. isolated C279 verification proves `prepare_outreach` without sending and `sends_message == false`;
14. all focused tests and the full diagnostic regression suite are green on the exact diagnostic SHA;
15. any subsequent candidate change reruns permanent release CI on its new exact SHA;
16. production deployment occurs only after a separate explicit approval;
17. production rollback is fast-forward/auditable and never force-resets Git history;
18. production ruleset governance remains a mandatory visible gate and is not bypassed.

## 15. Implementation boundary

After this written specification is reviewed and approved, implementation planning should decompose work into at least:

1. single-session sufficiency TDD gate;
2. pure/stable snapshot validator;
3. static-admin-only optional HTTP transport hook;
4. production entrypoint binding and environment contract;
5. transport/security/no-mutation tests;
6. encrypted diagnostic handoff workflow;
7. exact-SHA diagnostic regression verification;
8. pre-production deployment review package.

No production mutation belongs in the implementation phase before the separate deployment approval gate.
