# ASTRA Phase 2A GitHub Pull Worker Design

## Goal

Extend the Phase 1 ASTRA supervisor/local-executor architecture with an unattended Windows worker that can receive narrowly-scoped engineering tasks without requiring Codex allowance, while preserving strict privilege separation and keeping CBI runtime/evidence semantics untouched.

Phase 2A must allow GPT-5.6 Sol/ASTRA to continue engineering work when Codex is unavailable, but it must not turn ChatGPT, a browser session, a GitHub issue, or a remote manifest into general-purpose remote shell access to the user's Windows machine.

Phase 2A starts from the Phase 1 exact-head baseline:

`7fbf1c15477632f2f36259bd9d91b3074807b3da`

The Phase 1 branch remains frozen. Phase 2A is developed independently.

## User-approved operating boundary

The worker is intended to be:

- persistent on Windows;
- automatically started after installation;
- able to process approved tasks without per-task human confirmation;
- limited to pre-bound repositories and worker-owned ephemeral worktrees;
- unable to accept a remote arbitrary filesystem path;
- unable to expose unrestricted shell, PowerShell, cmd, arbitrary Python, package installation, arbitrary network commands, or direct push authority to protected/production branches.

## Architecture decision

Use a **GitHub pull queue** rather than an inbound writable HTTP bridge.

```text
GPT-5.6 Sol / ASTRA
        |
        | create proposed task issue
        v
GitHub Issues
        |
        | GitHub Actions validates + signs
        v
Signed READY task
        |
        | Windows worker polls outbound only
        v
ASTRA Windows Worker
        |
        +-- trusted local repo registry
        +-- task authentication / replay ledger
        +-- ephemeral worktree isolation
        +-- task -> Phase 1 manifest compiler
        +-- Phase 1 LocalExecutor
        +-- diff / test / receipt generation
        |
        | post signed receipt + patch chunks
        v
GitHub Issues
        |
        | GitHub Actions verifies receipt
        v
VERIFIED RESULT
        |
        v
ASTRA independent review
        |
        v
GitHub executor applies approved change to isolated remote branch / PR
```

The Windows worker has **no inbound listening port** in Phase 2A. It polls GitHub over outbound HTTPS.

## Anti-path-dependence decision

Three approaches were considered.

### Selected: GitHub Issues pull queue + local worker

Advantages:

- no inbound mutation endpoint on the Windows machine;
- durable GitHub audit trail for tasks and receipts;
- GitHub-native identity, timestamps, issue state, comments, and Actions automation;
- worker token can be restricted to Issues read/write plus Metadata read;
- no need to fork or convert `codex-with-chatgpt` into a writable bridge;
- no requirement for Codex allowance.

### Rejected for Phase 2A: Cloudflare Tunnel + writable local HTTP endpoint

This would provide lower latency but would create a remotely reachable mutation surface. Authentication, replay, request-flooding, tunnel lifecycle, and endpoint compromise become first-order risks. The gain does not justify the larger attack surface for this use case.

### Rejected for Phase 2A: GitHub self-hosted runner

A self-hosted runner offers excellent GitHub orchestration, but its normal execution model assumes broad workflow command/shell authority. Constraining it back down to the Phase 1 capability boundary would require another supervisory wrapper and would duplicate the worker being designed here.

## Trust model

### Trusted local authority

The following are trusted local configuration or runtime authorities and are never supplied by a remote task:

- logical repository ID -> local repository path mapping;
- expected GitHub repository identity;
- worker ID;
- allowed worker branch namespace;
- protected branch list;
- task signing verification secret/material;
- receipt signing secret/material;
- GitHub token used by the worker;
- worker policy/version limits;
- maximum task, operation, output, and diff sizes;
- worker service account and local state directory.

### Remote task is untrusted input until verified

A GitHub issue body, comment, label, task JSON, file content, test selector, or claimed result is not trusted merely because it exists in GitHub.

A task becomes eligible only after:

1. schema validation;
2. canonical serialization;
3. signing by the dedicated GitHub Actions gate;
4. worker-side signature verification;
5. worker ID match;
6. repository ID match to trusted local registry;
7. TTL validation;
8. task ID replay check;
9. exact base commit availability;
10. all task preconditions passing.

### Explicit out-of-scope host compromise

Phase 2A is not designed to defend against:

- a compromised Windows Administrator account;
- compromise of the dedicated worker service account;
- replaced local Python/Git binaries;
- a malicious dependency already trusted and importable by repository tests;
- malicious trusted repository test code performing side effects outside the repository;
- compromise of both GitHub repository administration and the Actions signing secrets.

Those are higher-order host/supply-chain boundaries and must not be mislabeled as solved by the task protocol.

## GitHub queue transport

Use GitHub Issues as the task and receipt transport. Do not store task queue state as commits in the CBI code branch.

### Task lifecycle labels

Phase 2A uses a dedicated label namespace:

- `astra-task/proposed`
- `astra-task/ready`
- `astra-task/claimed`
- `astra-task/completed`
- `astra-task/failed`
- `astra-task/rejected`
- `astra-task/result-verified`

Only a task with a valid signed envelope and `astra-task/ready` is executable.

### Proposal -> signing gate

ASTRA creates a proposed GitHub issue containing a single JSON task envelope and applies `astra-task/proposed`.

A GitHub Actions workflow triggered from the repository's authoritative branch:

1. confirms the issue is in the expected repository;
2. parses the task envelope;
3. applies the Phase 2A task schema and size limits;
4. canonicalizes the JSON;
5. computes an HMAC-SHA256 signature using the Actions-only task-signing secret;
6. posts a signed task comment as `github-actions[bot]`;
7. removes `astra-task/proposed` and applies `astra-task/ready` only on success.

Malformed or oversized proposals are labeled `astra-task/rejected` and never become ready.

The worker does not trust an unsigned issue body, even when the issue author is allowlisted.

## Cryptographic task and receipt binding

Phase 2A uses two independent HMAC-SHA256 keys:

- `ASTRA_TASK_HMAC_KEY`: GitHub Actions signs task envelopes; worker verifies them.
- `ASTRA_RECEIPT_HMAC_KEY`: worker signs execution receipts; GitHub Actions verifies them.

Both keys are generated during trusted installation/provisioning. The GitHub copies are stored only as Actions secrets. The Windows copies are stored using Windows-protected local secret storage and ACLs restricted to the dedicated worker identity and local administrators.

The two keys are not interchangeable.

Every signature covers canonical UTF-8 JSON bytes, including schema version, task ID, worker ID, repository ID, base commit, expiry, nonce, operations, and limits relevant to execution.

A changed byte invalidates the signature.

## Worker GitHub credential

The worker GitHub credential is separate from task/receipt HMAC keys.

Required GitHub token permission is limited to:

- Metadata: read;
- Issues: read/write.

The worker must not receive Contents write, Pull requests write, Actions write, Administration, or repository-secret permissions in Phase 2A.

The worker therefore cannot commit or push authoritative CBI source through GitHub.

## Trusted local configuration

The worker reads a local configuration owned by the worker installation, for example:

```json
{
  "schema_version": "astra.worker.config.v1",
  "worker_id": "scorp-windows-01",
  "queue_repository": "Scorp96/customs-buyer-intelligence-ledger",
  "repositories": {
    "cbi-primary": {
      "source_repo_root": "D:/CBI/customs-buyer-intelligence-ledger",
      "expected_origin": "https://github.com/Scorp96/customs-buyer-intelligence-ledger",
      "ephemeral_branch_prefix": "astra-worker/"
    }
  },
  "poll_interval_seconds": 15,
  "max_task_age_seconds": 1800,
  "max_task_payload_bytes": 49152,
  "max_operations": 32,
  "max_changed_files": 20,
  "max_diff_bytes": 262144,
  "max_command_output_bytes": 262144
}
```

The exact local path is never copied into the signed remote task. Remote callers use only `repository_id`, such as `cbi-primary`.

The worker refuses startup if required trusted configuration or secret material is missing, unreadable, schema-invalid, or has unsafe local permissions.

## Task schema

The signed Phase 2A task envelope has this logical shape:

```json
{
  "schema_version": "astra.task.v1",
  "task_id": "uuid-or-equivalent-opaque-id",
  "worker_id": "scorp-windows-01",
  "repository_id": "cbi-primary",
  "base_commit_sha": "40-hex-git-object-id",
  "issued_at": "RFC3339 UTC timestamp",
  "expires_at": "RFC3339 UTC timestamp",
  "nonce": "high-entropy unique value",
  "operations": [],
  "acceptance": {
    "max_changed_files": 20,
    "max_diff_bytes": 262144
  }
}
```

The task does **not** contain:

- `repository_root`;
- shell text;
- an arbitrary executable path;
- GitHub credentials;
- HMAC secrets;
- a Git remote URL override;
- a push destination;
- a protected-branch override.

## Remote capability model

The remote task is higher-level than the Phase 1 execution manifest. It requests narrowly-defined capabilities; the worker compiles those capabilities into a Phase 1 manifest.

Phase 2A permits:

### `write_text`

Fields:

- relative UTF-8 repository path;
- complete replacement UTF-8 text;
- exactly one precondition: `expected_sha256` for an existing file or `expect_absent=true` for creation.

The worker refuses a stale or mismatched precondition.

### `delete_file`

Fields:

- relative repository path;
- mandatory `expected_sha256`.

Deletion is refused if the current file hash differs.

### `run_unittest`

Fields:

- repository-relative/dotted test targets accepted by the Phase 1 validator;
- a bounded subset of existing unittest flags.

The worker compiles this into the existing constrained `python -m unittest ...` Phase 1 command.

### `run_compileall`

Fields:

- repository-relative targets;
- bounded existing compileall flags.

The worker compiles this into the existing constrained `python -m compileall ...` Phase 1 command.

No remote operation maps to arbitrary `run` argv.

## Ephemeral worktree isolation

Phase 2A must not apply remote tasks directly to the user's normal working tree.

For each accepted task:

1. resolve `repository_id` through trusted local config;
2. verify the configured source repo exists and its origin matches the pinned expected origin;
3. prove `base_commit_sha` is already present in the local repository object database;
4. refuse automatic network fetch in Phase 2A if the base object is missing;
5. create a worker-owned ephemeral Git worktree at the exact base commit;
6. create a generated local branch under `astra-worker/<task-id-derived-name>`;
7. inject the ephemeral worktree path into the Phase 1 manifest locally;
8. execute the task there;
9. collect diff/test evidence;
10. cleanly remove the ephemeral worktree and generated branch after receipt construction.

The generated worktree path and local source path are never accepted from the task payload.

A task that references a base commit not already present locally fails with a state-mismatch receipt; it does not trigger `git fetch`, credential negotiation, or remote code download in Phase 2A.

## Mutation-set confinement

Remote `write_text` and `delete_file` operations declare the complete expected mutable path set.

After all operations and tests run, the worker compares Git status/diff against that declared set.

If test code or another process changes or creates an undeclared repository path, the task is not eligible for successful completion. The worker returns a failed/quarantined receipt and does not mark the candidate patch as apply-ready.

This detects unexpected repository-local side effects. It does not claim to detect side effects outside the repository, which remain part of the trusted-code boundary.

## Phase 1 reuse

The worker does not reimplement file/command safety rules. It compiles the high-level task into the existing Phase 1 `ExecutionManifest` and invokes the Phase 1 `LocalExecutor`.

The worker supplies trusted local values that remote input is forbidden to choose:

- ephemeral `repository_root`;
- generated exact branch;
- worker-controlled execution policy.

Phase 1 continues to enforce:

- repository containment;
- no nested `.git` path access;
- protected branch logic;
- no shell;
- Python unittest/compileall restrictions;
- sanitized `PYTHON*` / `GIT_*` environment;
- Git external-helper restrictions;
- command timeouts;
- fail-closed operation validation.

## Result and patch transport

The worker never pushes source code in Phase 2A.

On completion it creates a canonical signed receipt containing at least:

- receipt schema version;
- task ID;
- worker ID;
- repository ID;
- base commit SHA;
- worker software/policy version;
- start and finish timestamps;
- terminal status;
- Phase 1 execution result;
- changed path inventory;
- before/after SHA-256 for each changed path;
- patch SHA-256;
- patch byte count and chunk count;
- bounded test output or hashes when output is truncated;
- ephemeral worktree cleanup result;
- local state/config fingerprint excluding paths and secrets.

UTF-8 text patch content is split into bounded GitHub issue comments when necessary. Each chunk is ordered and independently hashed; the receipt binds the ordered chunk hashes and final patch hash.

Binary changes are outside Phase 2A and fail closed.

A failed test may produce a diagnostic candidate patch for ASTRA review, but the receipt must explicitly mark it `NOT_APPLY_READY`.

## Receipt verification gate

A GitHub Actions workflow triggered by worker result comments:

1. parses the receipt;
2. verifies the worker HMAC signature with `ASTRA_RECEIPT_HMAC_KEY`;
3. checks task ID / worker ID / repository ID consistency with the signed task;
4. verifies chunk count, per-chunk hashes, and final patch SHA-256;
5. rejects duplicate or conflicting terminal receipts;
6. applies `astra-task/result-verified` only when the receipt is internally consistent;
7. applies `astra-task/completed` or `astra-task/failed` according to the signed terminal status.

ASTRA treats an unverified receipt as untrusted evidence.

## Replay and crash safety

The worker maintains a local SQLite ledger under its protected state directory.

The ledger records:

- task ID;
- nonce;
- signed task digest;
- claim timestamp;
- terminal state;
- receipt digest;
- cleanup state.

Rules:

- the same task ID or nonce is never executed twice;
- a duplicate signed task returns the previous terminal receipt reference when available;
- a task whose digest conflicts with an existing task ID is rejected;
- after worker restart, in-progress tasks are reconciled from the ledger and ephemeral worktree state before any new task is claimed;
- ambiguous crash state fails closed rather than automatically re-running mutations.

Only one task executes at a time in Phase 2A.

## Worker service model

The Windows worker runs under a dedicated non-administrator local identity.

Installation is an explicit trusted administrative operation and is outside remote task authority.

Runtime requirements:

- no Administrator/SYSTEM execution for normal worker operation;
- automatic startup using a Windows service wrapper appropriate to the installed Python runtime;
- pinned worker dependencies installed only during trusted setup, never by remote task;
- state/config/secrets stored in a dedicated protected directory;
- no listening network socket;
- outbound HTTPS only to the configured GitHub host;
- controlled polling with exponential backoff on transient GitHub failures.

The exact Windows service wrapper is an implementation choice, but it must be version-pinned, checksum-verified during trusted installation, and must not broaden the worker's runtime privileges.

## Kill switch

Phase 2A has a local fail-closed kill switch.

The worker stops claiming new tasks when either:

- the service is stopped/disabled; or
- a locally protected `DISABLED` marker exists in the worker state directory.

Existing in-progress execution is allowed to reach a safe terminal/cleanup point unless immediate process termination is explicitly chosen by the local administrator.

Remote GitHub state cannot override the local kill switch.

## ASTRA review and authoritative GitHub mutation

A verified worker result is still not self-approving.

The final flow is:

```text
verified signed task
    -> local candidate execution
    -> signed + GitHub-verified receipt
    -> ASTRA independent diff/test review
    -> PASS / FAIL decision
    -> GitHub executor applies approved content to an isolated remote branch
    -> normal CI / PR review
```

The worker does not receive permission to push source changes, merge PRs, or modify protected branches.

This preserves the Phase 1 supervisor/executor separation and avoids combining local filesystem mutation and authoritative GitHub source-write authority in one unattended process.

## Relationship to `codex-with-chatgpt`

`codex-with-chatgpt` remains optional and read-only. It may help ASTRA inspect local uncommitted state or execution output, but it is not part of the Phase 2A trust chain and is not required for the GitHub pull worker to operate.

No ChatGPT browser/session token is used to authenticate the worker.

## CBI boundaries

Phase 2A must not change CBI business-governance semantics merely to support the worker.

Specifically, Phase 2A does not redesign:

- evidence semantics;
- canonical identity;
- WAL/recovery rules;
- R2 persistence;
- Decision Saturation;
- CRM or outreach gates;
- production deployment semantics.

The worker/control-plane code remains an engineering orchestration surface outside those business rules.

## Security and acceptance tests

Implementation must include at least these adversarial tests before Phase 2A can be called merge-ready:

1. unsigned issue/task is never executed;
2. tampering with signed task JSON invalidates the task;
3. wrong worker ID is rejected;
4. unknown repository ID is rejected;
5. remote task cannot specify or influence local repository root;
6. expired task is rejected;
7. duplicate task ID/nonce is not executed twice;
8. conflicting payload under reused task ID is rejected;
9. missing local base commit fails closed without network fetch;
10. source repo origin mismatch is rejected;
11. stale file SHA precondition rejects write/delete;
12. remote task cannot supply arbitrary argv/executable/shell;
13. unexpected repository path mutation by a test causes failure/quarantine;
14. binary diff is rejected;
15. diff/file/output size limits are enforced;
16. worker cannot process two tasks concurrently;
17. crash/restart does not silently re-run an ambiguous mutation;
18. invalid task HMAC cannot be promoted to `ready` execution;
19. invalid receipt HMAC cannot become `result-verified`;
20. patch chunk reordering/removal/tampering is detected;
21. worker GitHub credential has no source Contents write path in the tested configuration;
22. local `DISABLED` kill switch prevents new claims;
23. protected CBI branches are never used as worker mutation branches;
24. ephemeral worktree is removed after a normal successful task;
25. cleanup failure produces a non-success/quarantined receipt;
26. existing Phase 1 LocalExecutor adversarial suite remains green;
27. full CBI regression remains green with no CBI runtime/evidence/WAL/R2 semantic changes.

## Success criteria

Phase 2A is successful only when all of the following are demonstrated with fresh evidence:

1. a GitHub proposed task is schema-validated and signed before the worker can see it as executable;
2. the Windows worker polls outbound only and accepts no inbound mutation connection;
3. remote input identifies only a logical repository ID, never a local path;
4. local config maps that repository ID to the sole allowed CBI source repository;
5. tasks execute in worker-owned ephemeral worktrees at exact preexisting base commits;
6. task capabilities compile into the Phase 1 LocalExecutor rather than bypassing it;
7. replay/crash state is durable and fail-closed;
8. task/test-induced unexpected repository mutations are detected;
9. results and patches are integrity-bound and GitHub-verifiable;
10. ASTRA independently reviews the verified result before authoritative GitHub code mutation;
11. the worker has no source push/merge/protected-branch authority;
12. Windows service runtime is non-admin and local secrets/config are protected;
13. Phase 1 tests and full CBI regressions remain green;
14. no CBI production/business-governance semantics are changed.

## Stop conditions

Stop and redesign before implementation or merge if any of these becomes necessary:

- opening an inbound writable port on the Windows worker for Phase 2A;
- allowing a remote task to choose `repository_root` or another arbitrary local path;
- granting the worker unrestricted shell, PowerShell, cmd, arbitrary Python, package installation, or generic network-command authority;
- granting the worker GitHub Contents write / protected-branch push / merge authority merely to simplify patch transport;
- running the worker routinely as Administrator or SYSTEM;
- allowing unsigned or browser-session-authenticated tasks to execute;
- automatically re-running a mutation after ambiguous crash state;
- automatically fetching or executing a missing remote base commit without a separately reviewed read-only sync design;
- accepting a task after file-hash/base-commit/state preconditions fail;
- treating worker execution as self-approval without ASTRA independent review;
- requiring changes to CBI evidence/WAL/R2/runtime semantics to make the worker viable.

## Deferred scope

The following are intentionally deferred beyond Phase 2A:

- automatic read-only Git fetch/synchronization of missing base commits;
- worker-side Git commit/push;
- direct remote HTTP/WebSocket control;
- multiple concurrent workers or distributed leasing;
- arbitrary repository enrollment from remote tasks;
- binary file editing;
- package/dependency installation by tasks;
- OS-level sandboxing of repository test code;
- automatic production merge or deployment.

Each deferred capability changes the threat model and requires a separate design/review gate.