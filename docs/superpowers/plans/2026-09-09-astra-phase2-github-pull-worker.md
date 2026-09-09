# ASTRA Phase 2A GitHub Pull Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an unattended, outbound-only Windows ASTRA worker that receives signed GitHub Issues tasks, synchronizes only a pinned CBI repository, executes narrowly scoped edits/tests through the Phase 1 `LocalExecutor`, emits signed receipts, and preserves ASTRA independent review plus GitHub-authoritative application.

**Architecture:** GitHub Actions is the task-signing and receipt-verification authority. A non-admin Windows service polls GitHub, verifies signed tasks, resolves logical repository IDs through trusted local configuration, synchronizes a dedicated mirror, creates an ephemeral worktree at an exact signed base commit, compiles high-level capabilities into Phase 1 manifests, verifies final state, and posts an integrity-bound receipt. The worker never exposes an inbound listener and never receives GitHub source-write, merge, shell, package-install, or protected-branch authority.

**Tech Stack:** Python 3.10/3.11 standard library (`dataclasses`, `json`, `hmac`, `hashlib`, `sqlite3`, `urllib.request`, `subprocess`, `ctypes`), existing `astra_supervisor.LocalExecutor`, Git, GitHub Actions, Windows DPAPI, PowerShell only for trusted administrative installation, WinSW v2.12.0 x64 pinned to SHA-256 `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`.

**Spec:** `docs/superpowers/specs/2026-09-09-astra-phase2-github-pull-worker-design.md`

## Global Constraints

- Phase 2A starts from Phase 1 exact HEAD `7fbf1c15477632f2f36259bd9d91b3074807b3da`; do not rewrite Phase 1 history.
- Development remains isolated on `astra-phase2-pull-worker-design-20260909` or a worktree/child branch created from it.
- Do not modify CBI Evidence, canonical identity, WAL/recovery, R2, Decision Saturation, CRM/outreach, production-deployment semantics, or existing business-governance rules.
- Worker runtime supports Python 3.10 and 3.11 and adds no third-party Python runtime dependency.
- Worker accepts no inbound network listener. All GitHub/source communication is outbound HTTPS/Git HTTPS to the locally pinned repository.
- Remote tasks never supply local paths, Git remote URLs, refspecs, executable paths, shell text, credentials, HMAC keys, push destinations, or protected-branch overrides.
- Worker GitHub credential is limited to Metadata read, Contents read, and Issues read/write; it must not have Contents write, Pull Requests write, Actions write, Administration, or secret-management permission.
- Task and receipt HMAC keys are independent. Task signatures are verified by the worker; receipt signatures are verified by GitHub Actions.
- Normal service runtime is non-admin. Runtime secrets live under `%ProgramData%\ASTRAWorker`, are DPAPI machine-scope protected, and are guarded by restrictive ACLs.
- Remote capabilities are only `write_text`, `delete_file`, `run_unittest`, and `run_compileall`; no arbitrary `run` capability exists in Phase 2A.
- All writes/tests occur in worker-owned ephemeral worktrees from an exact signed base commit; the user's normal CBI checkout is never mutated.
- A task may be executed at most once by task ID and nonce. Ambiguous crash state fails closed and is never silently re-run.
- A successful result requires exact pre-state hashes, exact signed final-state hashes, declared mutation-set confinement, text-only diff, and configured size limits.
- Worker never commits/pushes source. GitHub-authoritative application happens only after ASTRA review and must recheck the same exact base/file preconditions.
- WinSW runtime auto-update is forbidden. Installer downloads only `https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe` and verifies SHA-256 `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da` before installation.

## File Structure

- Create `astra_worker/__init__.py` — public Phase 2A package exports and version.
- Create `astra_worker/protocol.py` — strict JSON parsing, canonical JSON v1, HMAC signing/verification, signed-envelope framing.
- Create `astra_worker/models.py` — typed task/operation/receipt models and strict schema validation.
- Create `astra_worker/config.py` — trusted local worker/repository configuration and ref-policy validation.
- Create `astra_worker/windows_security.py` — DPAPI machine-scope protection/unprotection and Windows-only secret/ACL startup checks.
- Create `astra_worker/github_api.py` — narrow GitHub Issues/refs API client; no source-write method exists.
- Create `astra_worker/task_gate.py` — trusted GitHub Actions proposer/schema/base-ref signing gate.
- Create `astra_worker/receipt_gate.py` — trusted GitHub Actions receipt/chunk verification gate.
- Create `astra_worker/ledger.py` — SQLite replay/crash ledger and single-task lease.
- Create `astra_worker/git_workspace.py` — fixed-source mirror synchronization, exact-ref verification, ephemeral worktree lifecycle.
- Create `astra_worker/compiler.py` — high-level capability -> Phase 1 `ExecutionManifest` compiler plus pre-state checks.
- Create `astra_worker/evidence.py` — final-state/mutation-set verification, text patch generation/chunking, receipt construction.
- Create `astra_worker/queue.py` — ready-task discovery, unambiguous signed-task selection, claim/result comment transport.
- Create `astra_worker/worker.py` — one-task orchestration, crash reconciliation, kill switch, polling/backoff.
- Create `astra_worker/apply_contract.py` — pure GitHub-authoritative apply precondition planner; no network writes.
- Create `astra_worker/cli.py` — worker/service CLI and trusted secret provisioning entrypoints.
- Create `scripts/astra_worker.py` — repository-root launcher for `astra_worker.cli`.
- Create `scripts/astra_task_gate.py` — GitHub Actions task-gate launcher.
- Create `scripts/astra_receipt_gate.py` — GitHub Actions receipt-gate launcher.
- Create `scripts/install_astra_worker.ps1` — trusted Windows installation/provisioning workflow.
- Create `deploy/astra-worker/ASTRAWorker.xml.template` — pinned WinSW service template.
- Create `.github/workflows/astra-task-sign.yml` — Issues proposal signing workflow.
- Create `.github/workflows/astra-receipt-verify.yml` — worker result verification workflow.
- Create `.github/workflows/astra-worker-ci.yml` — Phase 2A Linux/Windows CI plus full CBI regression.
- Create `tests/test_astra_worker_protocol.py` — canonicalization/signature/schema adversarial tests.
- Create `tests/test_astra_worker_config_security.py` — local config/ref-policy/DPAPI tests.
- Create `tests/test_astra_worker_gates.py` — proposer/signing/receipt-gate tests.
- Create `tests/test_astra_worker_ledger.py` — replay/concurrency/crash-state tests.
- Create `tests/test_astra_worker_git_workspace.py` — pinned sync/ref/origin/worktree tests.
- Create `tests/test_astra_worker_compiler.py` — capability/pre-state/final-state compiler tests.
- Create `tests/test_astra_worker_queue.py` — task selection/claim/transport tests.
- Create `tests/test_astra_worker_evidence.py` — mutation confinement/patch/receipt tests.
- Create `tests/test_astra_worker_worker.py` — orchestration, kill-switch, no-listener, cleanup tests.
- Create `tests/test_astra_worker_apply_contract.py` — stale-base/file-hash authoritative-apply tests.
- Create `tests/test_astra_worker_install_contract.py` — static installer/WinSW/permission contract tests.
- Modify `skills/sol-advisor-astra/SKILL.md` — document Phase 2A task/receipt flow and trust boundary after implementation is green.

---

### Task 1: Canonical protocol and signed-envelope primitives

**Files:**
- Create: `astra_worker/__init__.py`
- Create: `astra_worker/protocol.py`
- Test: `tests/test_astra_worker_protocol.py`

**Interfaces:**
- Produces: `ProtocolError`, `parse_strict_json(raw: str) -> object`, `canonical_json_v1(value: object) -> bytes`, `hmac_sha256_hex(key: bytes, value: object) -> str`, `verify_hmac_sha256(key: bytes, value: object, expected_hex: str) -> None`, `encode_signed_envelope(kind: str, payload: dict, signature: str) -> str`, `decode_signed_envelope(text: str, expected_kind: str) -> tuple[dict, str]`.
- Consumers: Tasks 2, 3, 8, 9.

- [ ] **Step 1: Write strict-JSON and HMAC RED tests**

```python
import unittest
from astra_worker.protocol import (
    ProtocolError, canonical_json_v1, parse_strict_json,
    hmac_sha256_hex, verify_hmac_sha256,
)

class CanonicalProtocolTests(unittest.TestCase):
    def test_duplicate_key_and_float_are_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":1,"a":2}')
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":1.5}')

    def test_canonical_bytes_are_stable_utf8(self):
        left = parse_strict_json('{"z":"越南","a":1}')
        right = parse_strict_json('{"a":1,"z":"越南"}')
        self.assertEqual(canonical_json_v1(left), canonical_json_v1(right))
        self.assertEqual(canonical_json_v1(left), b'{"a":1,"z":"\xe8\xb6\x8a\xe5\x8d\x97"}')

    def test_changed_byte_invalidates_hmac(self):
        key = b'k' * 32
        value = {"task_id": "t1", "n": 1}
        signature = hmac_sha256_hex(key, value)
        verify_hmac_sha256(key, value, signature)
        with self.assertRaises(ProtocolError):
            verify_hmac_sha256(key, {"task_id": "t1", "n": 2}, signature)
```

- [ ] **Step 2: Run the test and prove RED**

Run: `python -m unittest tests.test_astra_worker_protocol -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'astra_worker'`.

- [ ] **Step 3: Implement the minimal strict protocol**

```python
# astra_worker/protocol.py
from __future__ import annotations
import hashlib, hmac, json
from typing import Any

class ProtocolError(ValueError):
    pass

def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ProtocolError(f"duplicate JSON key: {key}")
        out[key] = value
    return out

def _reject_float(value: str):
    raise ProtocolError("floats are not allowed")

def parse_strict_json(raw: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_float=_reject_float,
                          parse_constant=lambda token: (_ for _ in ()).throw(ProtocolError(f"non-finite JSON: {token}")))
    except ProtocolError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProtocolError(str(exc)) from exc

def canonical_json_v1(value: Any) -> bytes:
    def check(v):
        if v is None or isinstance(v, (str, bool)):
            return
        if isinstance(v, int) and not isinstance(v, bool):
            if abs(v) > 2**63 - 1:
                raise ProtocolError("integer outside signed 64-bit range")
            return
        if isinstance(v, list):
            for item in v: check(item)
            return
        if isinstance(v, dict):
            if not all(isinstance(k, str) for k in v):
                raise ProtocolError("object keys must be strings")
            for item in v.values(): check(item)
            return
        raise ProtocolError(f"unsupported canonical JSON type: {type(v).__name__}")
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def hmac_sha256_hex(key: bytes, value: Any) -> str:
    return hmac.new(key, canonical_json_v1(value), hashlib.sha256).hexdigest()

def verify_hmac_sha256(key: bytes, value: Any, expected_hex: str) -> None:
    actual = hmac_sha256_hex(key, value)
    if not hmac.compare_digest(actual, expected_hex.lower()):
        raise ProtocolError("HMAC verification failed")
```

Use an envelope prefix of `ASTRA_TASK_V1 ` or `ASTRA_RECEIPT_V1 ` followed by canonical compact JSON containing only `payload` and `signature`; reject extra keys and wrong prefixes.

- [ ] **Step 4: Run focused tests GREEN**

Run: `python -m unittest tests.test_astra_worker_protocol -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add astra_worker/__init__.py astra_worker/protocol.py tests/test_astra_worker_protocol.py
git commit -m "feat(astra-worker): add canonical signed protocol"
```

---

### Task 2: Typed task/receipt models and trusted config/ref policy

**Files:**
- Create: `astra_worker/models.py`
- Create: `astra_worker/config.py`
- Extend: `tests/test_astra_worker_protocol.py`
- Create: `tests/test_astra_worker_config_security.py`

**Interfaces:**
- Produces: `TaskEnvelope.from_mapping`, `ReceiptEnvelope.from_mapping`, operation dataclasses, `WorkerConfig.load(path)`, `RepositoryBinding.allows_base_ref(ref) -> bool`.
- Task model intentionally has no `repository_root`, `remote_url`, `refspec`, `argv`, or executable field.

- [ ] **Step 1: Add RED tests for forbidden remote authority and ref lookalikes**

```python
class TaskSchemaTests(unittest.TestCase):
    def test_remote_path_and_argv_fields_are_rejected(self):
        payload = valid_task_mapping()
        payload["repository_root"] = "C:/Users"
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)
        payload = valid_task_mapping()
        payload["operations"] = [{"kind": "run", "argv": ["powershell", "-c", "x"]}]
        with self.assertRaises(TaskValidationError):
            TaskEnvelope.from_mapping(payload)

class RefPolicyTests(unittest.TestCase):
    def test_exact_and_prefix_rules_are_distinct(self):
        binding = RepositoryBinding(
            repository_id="cbi-primary",
            github_repository="Scorp96/customs-buyer-intelligence-ledger",
            expected_origin="https://github.com/Scorp96/customs-buyer-intelligence-ledger",
            mirror_root=Path("D:/ASTRAWorker/repos/cbi-primary.git"),
            allowed_base_refs_exact=("cbi-v6-3-demand-expansion",),
            allowed_base_ref_prefixes=("astra-",),
            ephemeral_branch_prefix="astra-worker/",
        )
        self.assertTrue(binding.allows_base_ref("cbi-v6-3-demand-expansion"))
        self.assertFalse(binding.allows_base_ref("cbi-v6-3-demand-expansion-evil"))
        self.assertTrue(binding.allows_base_ref("astra-feature-x"))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_protocol tests.test_astra_worker_config_security -v`

Expected: FAIL because models/config do not exist.

- [ ] **Step 3: Implement strict dataclasses and config parsing**

Implement only these operation kinds and required fields:

```python
@dataclass(frozen=True)
class WriteTextCapability:
    path: str
    content: str
    expected_sha256: str | None
    expect_absent: bool

@dataclass(frozen=True)
class DeleteFileCapability:
    path: str
    expected_sha256: str

@dataclass(frozen=True)
class RunUnittestCapability:
    targets: tuple[str, ...]
    flags: tuple[str, ...]

@dataclass(frozen=True)
class RunCompileallCapability:
    targets: tuple[str, ...]
    flags: tuple[str, ...]
```

`TaskEnvelope.from_mapping` must require exactly: `schema_version`, `task_id`, `worker_id`, `repository_id`, `base_ref`, `base_commit_sha`, `issued_at`, `expires_at`, `nonce`, `operations`, `acceptance`; reject unknown top-level keys. Validate SHA as lowercase/uppercase 40-hex, RFC3339 UTC timestamps, non-empty IDs, bounded operation count, and exactly one write precondition (`expected_sha256` xor `expect_absent=true`).

`WorkerConfig.load` must reject unknown repository IDs, unsafe/non-absolute local mirror paths, duplicate exact/prefix rules, a queue repository mismatch, non-positive limits, and protected branch names accidentally present as worker prefixes.

- [ ] **Step 4: Run focused tests GREEN**

Run: `python -m unittest tests.test_astra_worker_protocol tests.test_astra_worker_config_security -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add astra_worker/models.py astra_worker/config.py tests/test_astra_worker_protocol.py tests/test_astra_worker_config_security.py
git commit -m "feat(astra-worker): add strict task and config models"
```

---

### Task 3: Windows DPAPI secret store and startup security checks

**Files:**
- Create: `astra_worker/windows_security.py`
- Extend: `tests/test_astra_worker_config_security.py`

**Interfaces:**
- Produces: `protect_machine_secret(clear: bytes) -> bytes`, `unprotect_machine_secret(blob: bytes) -> bytes`, `SecretBundle`, `write_secret_bundle(path, bundle)`, `read_secret_bundle(path)`, `validate_worker_state_location(path, service_sid) -> None`.
- Windows-only cryptographic functions raise `WindowsSecurityError` on non-Windows; tests are skipped there.

- [ ] **Step 1: Add RED Windows security tests**

```python
@unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
class WindowsSecretTests(unittest.TestCase):
    def test_dpapi_machine_scope_round_trip(self):
        clear = b"task-key\0receipt-key\0github-token"
        protected = protect_machine_secret(clear)
        self.assertNotEqual(protected, clear)
        self.assertEqual(unprotect_machine_secret(protected), clear)

    def test_plaintext_secret_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "secrets.bin"
            path.write_text('{"github_token":"plain"}', encoding="utf-8")
            with self.assertRaises(WindowsSecurityError):
                read_secret_bundle(path)
```

- [ ] **Step 2: Run RED on Windows matrix**

Run: `python -m unittest tests.test_astra_worker_config_security -v`

Expected on Windows: FAIL because DPAPI functions do not exist.

- [ ] **Step 3: Implement DPAPI using `ctypes` only**

Use `CryptProtectData` / `CryptUnprotectData` from `Crypt32.dll` with `CRYPTPROTECT_LOCAL_MACHINE = 0x4`, `DATA_BLOB`, and `LocalFree`. Secret file format is `ASTRA_SECRET_V1\0` + DPAPI ciphertext; clear JSON contains exactly `task_hmac_key_b64`, `receipt_hmac_key_b64`, `github_token` and is never logged.

```python
CRYPTPROTECT_LOCAL_MACHINE = 0x4
MAGIC = b"ASTRA_SECRET_V1\0"

@dataclass(frozen=True)
class SecretBundle:
    task_hmac_key: bytes
    receipt_hmac_key: bytes
    github_token: str
```

`validate_worker_state_location` must require a path under resolved `%ProgramData%\ASTRAWorker` on Windows and invoke a fixed, installer-owned ACL verifier mode in `astra_worker.cli`; it must fail closed when ACL verification is unavailable or reports broad write/read principals beyond `SYSTEM`, `BUILTIN\Administrators`, and the service SID.

- [ ] **Step 4: Run GREEN on Windows and non-Windows skip path**

Run: `python -m unittest tests.test_astra_worker_config_security -v`

Expected: PASS; DPAPI tests skip only on non-Windows.

- [ ] **Step 5: Commit**

```bash
git add astra_worker/windows_security.py tests/test_astra_worker_config_security.py
git commit -m "feat(astra-worker): protect worker secrets with DPAPI"
```

---

### Task 4: Narrow GitHub API client and trusted task-signing gate

**Files:**
- Create: `astra_worker/github_api.py`
- Create: `astra_worker/task_gate.py`
- Create: `scripts/astra_task_gate.py`
- Create: `.github/workflows/astra-task-sign.yml`
- Create: `tests/test_astra_worker_gates.py`

**Interfaces:**
- `GitHubIssueClient` exposes only `get_issue`, `list_issue_comments`, `post_issue_comment`, `replace_astra_labels`, `resolve_branch_head`; it has no Contents mutation, PR mutation, Actions mutation, or secret API methods.
- `TaskGate.process(event: dict) -> GateResult` authorizes proposer, validates task, binds ref->SHA, signs, comments, and moves label proposed->ready.

- [ ] **Step 1: Write RED signer tests**

```python
class TaskGateTests(unittest.TestCase):
    def test_unauthorized_proposer_never_gets_ready(self):
        api = FakeGitHub(proposer="mallory", ref_sha=BASE_SHA)
        gate = TaskGate(api, allowed_proposers={"Scorp96"}, task_key=b"t"*32,
                        worker_id="scorp-windows-01", repository_id="cbi-primary",
                        ref_policy=policy())
        result = gate.process(issue_event(valid_task_json()))
        self.assertEqual(result.status, "REJECTED")
        self.assertNotIn("astra-task/ready", api.labels)

    def test_base_ref_sha_mismatch_is_rejected(self):
        api = FakeGitHub(proposer="Scorp96", ref_sha="1"*40)
        result = make_gate(api).process(issue_event(valid_task_json(base_commit_sha="2"*40)))
        self.assertEqual(result.status, "REJECTED")
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_gates -v`

Expected: FAIL because GitHub gate modules do not exist.

- [ ] **Step 3: Implement the API and signer**

Use `urllib.request.Request` with explicit `Authorization: Bearer`, `Accept: application/vnd.github+json`, and `X-GitHub-Api-Version: 2022-11-28`. Never include token values in exception text. `resolve_branch_head` URL-encodes the already policy-validated branch name and accepts only a 40-hex object SHA.

Signed comment body format:

```text
ASTRA_TASK_V1 {"payload":{...canonical task...},"signature":"64-hex"}
```

The gate must require repository `Scorp96/customs-buyer-intelligence-ledger`, allowlisted proposer, `astra-task/proposed`, one JSON object in issue body, known worker/repository ID, allowed ref, valid TTL, and exact GitHub ref SHA match before signing.

- [ ] **Step 4: Add the trusted GitHub Actions workflow**

```yaml
name: ASTRA task signing gate
on:
  issues:
    types: [opened, edited, labeled]
permissions:
  contents: read
  issues: write
jobs:
  sign:
    if: contains(github.event.issue.labels.*.name, 'astra-task/proposed')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: '3.11'
      - run: python scripts/astra_task_gate.py --event "$GITHUB_EVENT_PATH"
        env:
          GITHUB_TOKEN: ${{ github.token }}
          ASTRA_TASK_HMAC_KEY: ${{ secrets.ASTRA_TASK_HMAC_KEY }}
          ASTRA_ALLOWED_PROPOSERS: Scorp96
          ASTRA_WORKER_ID: scorp-windows-01
          ASTRA_REPOSITORY_ID: cbi-primary
```

- [ ] **Step 5: Run GREEN and static workflow contract tests**

Run: `python -m unittest tests.test_astra_worker_gates -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add astra_worker/github_api.py astra_worker/task_gate.py scripts/astra_task_gate.py .github/workflows/astra-task-sign.yml tests/test_astra_worker_gates.py
git commit -m "feat(astra-worker): add GitHub task signing gate"
```

---

### Task 5: Durable replay ledger and single-task lease

**Files:**
- Create: `astra_worker/ledger.py`
- Create: `tests/test_astra_worker_ledger.py`

**Interfaces:**
- Produces: `TaskLedger(path)`, `claim(task_id, nonce, digest, ...)`, `mark_terminal(...)`, `mark_cleanup(...)`, `find_replay(...)`, `list_in_progress()`, `acquire_worker_lease(worker_id)`.

- [ ] **Step 1: Write replay/concurrency RED tests**

```python
class LedgerTests(unittest.TestCase):
    def test_same_task_or_nonce_cannot_execute_twice(self):
        ledger = TaskLedger(self.db)
        ledger.claim("t1", "n1", "d1", "repo", "ref", BASE_SHA)
        with self.assertRaises(ReplayError):
            ledger.claim("t1", "n2", "d1", "repo", "ref", BASE_SHA)
        with self.assertRaises(ReplayError):
            ledger.claim("t2", "n1", "d2", "repo", "ref", BASE_SHA)

    def test_conflicting_digest_for_task_id_is_rejected(self):
        ledger = TaskLedger(self.db)
        ledger.claim("t1", "n1", "d1", "repo", "ref", BASE_SHA)
        with self.assertRaises(ReplayConflictError):
            ledger.claim("t1", "n1", "DIFFERENT", "repo", "ref", BASE_SHA)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_ledger -v`

Expected: FAIL because ledger does not exist.

- [ ] **Step 3: Implement SQLite ledger with transactional uniqueness**

Schema must include unique `task_id`, unique `nonce`, signed task digest, state, receipt digest, mirror/ref/SHA, worktree, generated branch, cleanup state, timestamps. `claim` and lease acquisition use `BEGIN IMMEDIATE`; `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=FULL`, and foreign keys are enabled. Legal states are `CLAIMED`, `EXECUTING`, `TERMINAL`, `QUARANTINED`; no API changes a terminal record back to executable.

- [ ] **Step 4: Add crash reconciliation test**

Create a `CLAIMED`/`EXECUTING` row, reopen the SQLite file, verify it is returned by `list_in_progress()` and cannot be automatically reclaimed as fresh.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_ledger -v`

```bash
git add astra_worker/ledger.py tests/test_astra_worker_ledger.py
git commit -m "feat(astra-worker): add replay-safe task ledger"
```

---

### Task 6: Fixed-source mirror synchronizer and ephemeral worktrees

**Files:**
- Create: `astra_worker/git_workspace.py`
- Create: `tests/test_astra_worker_git_workspace.py`

**Interfaces:**
- Produces: `GitWorkspaceManager(binding, token, git_executable)`, `sync_exact(base_ref, base_sha) -> None`, `create_task_worktree(task_id, base_sha) -> WorktreeHandle`, `cleanup(handle) -> CleanupResult`.

- [ ] **Step 1: Write RED adversarial Git tests**

Use local bare repositories as the remote fixture. Tests must prove:

```python
def test_origin_mismatch_is_rejected(): ...
def test_ref_sha_mismatch_fails_before_worktree_creation(): ...
def test_task_cannot_override_remote_or_refspec(): ...
def test_inherited_git_config_and_hooks_are_suppressed(): ...
def test_cleanup_removes_worktree_and_generated_branch(): ...
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_git_workspace -v`

Expected: FAIL because workspace manager does not exist.

- [ ] **Step 3: Implement a sanitized Git environment**

`_git_env()` must remove inherited keys beginning `GIT_`, `SSH_`, `GCM_`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`; set worker-owned `HOME`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0`, `GIT_LFS_SKIP_SMUDGE=1`, `GCM_INTERACTIVE=Never`; and inject only worker-controlled `GIT_CONFIG_COUNT` entries such as `core.hooksPath=<empty-hooks>` and an ephemeral GitHub Authorization extraheader when the remote is HTTPS.

The token must exist only in the subprocess environment and must be redacted from exceptions.

- [ ] **Step 4: Implement exact bounded fetch and worktree creation**

For GitHub branches, fetch only:

```text
+refs/heads/<validated-base-ref>:refs/astra/fetched/<sha256(base-ref)[:24]>
```

Then `rev-parse` the destination ref and require equality with signed `base_commit_sha`. Create branch `astra-worker/<sha256(task_id)[:24]>` and worktree under the worker-owned worktree root. Do not initialize submodules or LFS.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_git_workspace -v`

```bash
git add astra_worker/git_workspace.py tests/test_astra_worker_git_workspace.py
git commit -m "feat(astra-worker): add pinned mirror and worktree isolation"
```

---

### Task 7: Capability compiler, pre-state checks, and Phase 1 reuse

**Files:**
- Create: `astra_worker/compiler.py`
- Create: `tests/test_astra_worker_compiler.py`
- Reuse without weakening: `astra_supervisor/manifest.py`, `astra_supervisor/local_executor.py`

**Interfaces:**
- Produces: `TaskCompiler.compile(task, worktree, expected_branch) -> ExecutionManifest`, `verify_pre_state(task, worktree) -> None`, `intended_final_hashes(task) -> dict[str, str | None]`.

- [ ] **Step 1: Write RED compiler tests**

```python
class CompilerTests(unittest.TestCase):
    def test_stale_sha_rejects_before_any_write(self): ...
    def test_creation_requires_absence(self): ...
    def test_no_remote_arbitrary_run_can_be_compiled(self): ...
    def test_unittest_compiles_to_current_python_and_phase1_validator(self): ...
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_compiler -v`

Expected: FAIL.

- [ ] **Step 3: Implement exact capability translation**

`write_text` -> Phase 1 `Operation(kind="write_text", ...)`; `delete_file` -> `delete_file`; `run_unittest` -> `Operation(kind="run", argv=(sys.executable, "-m", "unittest", ...))`; `run_compileall` -> equivalent compileall operation. No mapping accepts an executable, argv vector, environment, remote URL, or network flag from the task.

Pre-state SHA is lowercase SHA-256 of raw file bytes. Final intended SHA for `write_text` is SHA-256 of exact UTF-8 encoded signed content; final delete state is `None`.

- [ ] **Step 4: Re-run the Phase 1 adversarial suite**

Run: `python -m unittest tests.test_astra_supervisor tests.test_astra_supervisor_executable_boundary tests.test_astra_worker_compiler -v`

Expected: all PASS; do not modify Phase 1 behavior to make Phase 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add astra_worker/compiler.py tests/test_astra_worker_compiler.py
git commit -m "feat(astra-worker): compile signed capabilities into phase1 manifests"
```

---

### Task 8: Final-state confinement, patch evidence, and signed receipts

**Files:**
- Create: `astra_worker/evidence.py`
- Create: `tests/test_astra_worker_evidence.py`

**Interfaces:**
- Produces: `verify_final_state(task, worktree, intended_hashes, limits) -> ChangeEvidence`, `build_text_patch(...) -> bytes`, `chunk_patch(...) -> tuple[PatchChunk, ...]`, `build_signed_receipt(...) -> ReceiptEnvelope`.

- [ ] **Step 1: Write RED mutation-confinement tests**

```python
class EvidenceTests(unittest.TestCase):
    def test_test_created_undeclared_file_quarantines_result(self): ...
    def test_declared_file_changed_away_from_signed_content_quarantines(self): ...
    def test_binary_diff_is_rejected(self): ...
    def test_diff_and_changed_file_limits_are_enforced(self): ...
    def test_patch_chunk_reorder_changes_bound_hash(self): ...
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_evidence -v`

Expected: FAIL.

- [ ] **Step 3: Implement repository-local final-state verification**

Use sanitized fixed Git commands to obtain status, `git diff --numstat`, and unified text diff. Reject a binary numstat entry (`-`), any changed path outside the signed mutable set, any final SHA mismatch, any surviving delete target, changed-file count above both local and task acceptance limits, or diff bytes above the lower of local/task limits.

Patch chunks are UTF-8, maximum 48 KiB per comment payload before framing, numbered from 1, each hashed independently; the receipt stores ordered chunk hashes and the SHA-256 of the complete patch.

- [ ] **Step 4: Build terminal receipts with bounded test output**

Receipt statuses are exactly `APPLY_READY`, `NOT_APPLY_READY`, `REJECTED`, `QUARANTINED`. Store bounded stdout/stderr when under limit; otherwise store prefix/suffix plus full-output SHA-256 and original byte count. Never include local absolute paths or credentials.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_evidence -v`

```bash
git add astra_worker/evidence.py tests/test_astra_worker_evidence.py
git commit -m "feat(astra-worker): bind final state and signed receipts"
```

---

### Task 9: Queue client, receipt verification gate, and lifecycle labels

**Files:**
- Create: `astra_worker/queue.py`
- Create: `astra_worker/receipt_gate.py`
- Create: `scripts/astra_receipt_gate.py`
- Create: `.github/workflows/astra-receipt-verify.yml`
- Create: `tests/test_astra_worker_queue.py`
- Extend: `tests/test_astra_worker_gates.py`

**Interfaces:**
- `TaskQueue.find_ready(worker_id) -> list[ReadyTask]`, `claim(issue, task)`, `post_patch_chunks`, `post_receipt`.
- Receipt gate verifies one signed task, one terminal receipt, ordered patch chunks, and lifecycle consistency before applying `result-verified`.

- [ ] **Step 1: Write RED ambiguity/receipt tests**

```python
def test_unsigned_ready_issue_is_not_returned(): ...
def test_two_conflicting_valid_signed_tasks_fail_closed(): ...
def test_invalid_receipt_hmac_never_sets_result_verified(): ...
def test_missing_or_reordered_chunk_is_rejected(): ...
def test_duplicate_conflicting_terminal_receipt_is_rejected(): ...
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_queue tests.test_astra_worker_gates -v`

Expected: FAIL.

- [ ] **Step 3: Implement queue parsing and lifecycle operations**

Only Issues labeled `astra-task/ready` are candidates. Select exactly one `github-actions[bot]` signed task comment whose HMAC verifies; zero or more-than-one conflicting valid envelope fails closed. Claim changes labels to `claimed` and writes a non-secret worker claim comment bound to task digest.

- [ ] **Step 4: Add receipt verification workflow**

```yaml
name: ASTRA receipt verification gate
on:
  issue_comment:
    types: [created]
permissions:
  contents: read
  issues: write
jobs:
  verify:
    if: startsWith(github.event.comment.body, 'ASTRA_RECEIPT_V1 ')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: '3.11'
      - run: python scripts/astra_receipt_gate.py --event "$GITHUB_EVENT_PATH"
        env:
          GITHUB_TOKEN: ${{ github.token }}
          ASTRA_TASK_HMAC_KEY: ${{ secrets.ASTRA_TASK_HMAC_KEY }}
          ASTRA_RECEIPT_HMAC_KEY: ${{ secrets.ASTRA_RECEIPT_HMAC_KEY }}
```

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_queue tests.test_astra_worker_gates -v`

```bash
git add astra_worker/queue.py astra_worker/receipt_gate.py scripts/astra_receipt_gate.py .github/workflows/astra-receipt-verify.yml tests/test_astra_worker_queue.py tests/test_astra_worker_gates.py
git commit -m "feat(astra-worker): verify queue tasks and receipts"
```

---

### Task 10: Worker orchestration, kill switch, and crash reconciliation

**Files:**
- Create: `astra_worker/worker.py`
- Create: `astra_worker/cli.py`
- Create: `scripts/astra_worker.py`
- Create: `tests/test_astra_worker_worker.py`

**Interfaces:**
- Produces: `Worker.run_once() -> WorkerCycleResult`, `Worker.run_forever() -> None`, `Worker.reconcile_in_progress() -> list[ReconciliationResult]`.

- [ ] **Step 1: Write orchestration RED tests**

```python
class WorkerTests(unittest.TestCase):
    def test_disabled_marker_prevents_claim(self): ...
    def test_only_one_task_executes_per_cycle(self): ...
    def test_ambiguous_crash_is_quarantined_not_rerun(self): ...
    def test_cleanup_failure_forces_quarantined_receipt(self): ...
    def test_worker_source_has_no_inbound_listener(self):
        source = Path("astra_worker/worker.py").read_text(encoding="utf-8")
        for forbidden in ("http.server", "socketserver", "listen(", "bind("):
            self.assertNotIn(forbidden, source)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_worker -v`

Expected: FAIL.

- [ ] **Step 3: Implement the one-task state machine**

Exact order:

```text
startup config/secrets/ACL validation
-> local DISABLED check
-> reconcile prior in-progress ledger rows
-> find signed ready task
-> verify TTL/signature/worker/repository/ref policy
-> ledger claim
-> queue claim
-> fixed-source sync exact ref/SHA
-> create ephemeral worktree
-> verify file pre-state
-> compile Phase 1 manifest
-> Phase 1 LocalExecutor execute(apply=True)
-> verify final state and patch
-> cleanup worktree/branch
-> build/sign receipt
-> ledger terminal commit
-> post chunks + receipt
```

If cleanup fails, terminal status is `QUARANTINED` even when tests passed. If process restarts with a ledger row between claim and terminal receipt, reconcile worktree evidence but never re-run mutations automatically.

- [ ] **Step 4: Implement bounded polling/backoff**

Default 15 seconds. Retry transport errors with exponential schedule `15, 30, 60, 120, 300` seconds capped at 300; signature/schema/state failures are terminal for that task, not transport retries.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_worker tests.test_astra_worker_ledger -v`

```bash
git add astra_worker/worker.py astra_worker/cli.py scripts/astra_worker.py tests/test_astra_worker_worker.py
git commit -m "feat(astra-worker): add unattended outbound worker loop"
```

---

### Task 11: GitHub-authoritative apply contract

**Files:**
- Create: `astra_worker/apply_contract.py`
- Create: `tests/test_astra_worker_apply_contract.py`

**Interfaces:**
- Produces: `build_apply_plan(task, verified_receipt, remote_snapshot) -> ApplyPlan`; pure validation only, no network mutation.

- [ ] **Step 1: Write RED stale-result tests**

```python
class ApplyContractTests(unittest.TestCase):
    def test_remote_base_advance_rejects_verified_worker_result(self): ...
    def test_remote_file_hash_change_rejects_apply(self): ...
    def test_apply_content_comes_from_signed_task_not_patch_text(self): ...
    def test_observed_final_hash_must_match_signed_intended_hash(self): ...
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_apply_contract -v`

Expected: FAIL.

- [ ] **Step 3: Implement pure apply planning**

`RemoteSnapshot` contains exact base SHA and current bytes/hash/absence for each mutable file. `build_apply_plan` requires receipt status `APPLY_READY`, receipt verification marker supplied from the trusted GitHub gate, exact task/receipt/base binding, fresh pre-state hashes, and matching intended/observed final hashes. It emits ordered create/replace/delete operations using **task content**, never patch text.

No function in this module accepts credentials or calls GitHub. The ChatGPT/GitHub executor uses this contract when it later creates an isolated remote branch from the exact `base_commit_sha`.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_apply_contract -v`

```bash
git add astra_worker/apply_contract.py tests/test_astra_worker_apply_contract.py
git commit -m "feat(astra-worker): add stale-safe authoritative apply contract"
```

---

### Task 12: Windows service installation and non-admin runtime contract

**Files:**
- Create: `deploy/astra-worker/ASTRAWorker.xml.template`
- Create: `scripts/install_astra_worker.ps1`
- Extend: `astra_worker/cli.py`
- Create: `tests/test_astra_worker_install_contract.py`

**Interfaces:**
- Trusted admin install only. Runtime task protocol cannot call installer/provision commands.
- Service identity is the Windows virtual service account `NT SERVICE\ASTRAWorker`, not Administrator/SYSTEM and no reusable account password is stored.

- [ ] **Step 1: Write RED static installer tests**

```python
class InstallContractTests(unittest.TestCase):
    def test_winsw_url_and_hash_are_pinned(self):
        text = Path("scripts/install_astra_worker.ps1").read_text(encoding="utf-8")
        self.assertIn("v2.12.0/WinSW-x64.exe", text)
        self.assertIn("05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da", text.lower())
        self.assertNotIn("/latest/", text)

    def test_service_is_reconfigured_to_virtual_non_admin_identity_before_start(self): ...
    def test_runtime_xml_contains_no_secret_value_or_github_token(self): ...
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_install_contract -v`

Expected: FAIL.

- [ ] **Step 3: Implement pinned WinSW and protected state installation**

PowerShell constants are exact:

```powershell
$WinSWUrl = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
$WinSWSha256 = "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"
$StateRoot = Join-Path $env:ProgramData "ASTRAWorker"
$ServiceName = "ASTRAWorker"
$ServiceAccount = "NT SERVICE\ASTRAWorker"
```

Download with `Invoke-WebRequest`, compute `Get-FileHash -Algorithm SHA256`, delete and abort on mismatch. Create state/config/log/repos/worktrees/empty-hooks directories, install WinSW but do **not** start it, run `sc.exe sidtype ASTRAWorker unrestricted`, reconfigure service identity with `sc.exe config ASTRAWorker obj= "NT SERVICE\ASTRAWorker" password= ""`, then apply `icacls` so only service SID, SYSTEM, and Administrators can access secrets/state. Start only after `python scripts/astra_worker.py validate-install` succeeds.

- [ ] **Step 4: Implement secret provisioning over stdin, not argv**

`python scripts/astra_worker.py provision-secrets --stdin` reads one JSON object from standard input containing three clear values, validates lengths, writes DPAPI-protected `secrets.bin`, then overwrites in-memory bytearrays where practical. It must never echo input. Administrative documentation uses PowerShell `Read-Host -AsSecureString`/explicit conversion only inside the trusted one-time provisioning process; runtime service never provisions secrets.

GitHub Actions secret installation remains an explicit admin command, for example:

```powershell
$env:GH_TOKEN = Read-Host "GitHub admin token"
$taskKey = Read-Host "ASTRA_TASK_HMAC_KEY"
$receiptKey = Read-Host "ASTRA_RECEIPT_HMAC_KEY"
$taskKey | gh secret set ASTRA_TASK_HMAC_KEY --repo Scorp96/customs-buyer-intelligence-ledger
$receiptKey | gh secret set ASTRA_RECEIPT_HMAC_KEY --repo Scorp96/customs-buyer-intelligence-ledger
Remove-Item Env:GH_TOKEN
```

This is installation authority, not worker runtime authority.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_astra_worker_install_contract tests.test_astra_worker_config_security -v`

```bash
git add deploy/astra-worker/ASTRAWorker.xml.template scripts/install_astra_worker.ps1 astra_worker/cli.py tests/test_astra_worker_install_contract.py
git commit -m "feat(astra-worker): add pinned non-admin Windows service install"
```

---

### Task 13: Phase 2A CI, integrated acceptance, and ASTRA skill update

**Files:**
- Create: `.github/workflows/astra-worker-ci.yml`
- Modify: `skills/sol-advisor-astra/SKILL.md`
- Extend worker tests as needed only for missing spec coverage; do not widen capabilities.

**Interfaces:**
- CI is the merge gate for Phase 2A code; task-sign/receipt workflows remain inactive as operational authority until merged to the authoritative branch and secrets are provisioned.

- [ ] **Step 1: Add Phase 2A CI workflow**

```yaml
name: ASTRA worker CI
on:
  push:
    branches: ["astra-phase2-*"]
    paths:
      - "astra_worker/**"
      - "scripts/astra_*worker*.py"
      - "scripts/astra_*gate.py"
      - "scripts/install_astra_worker.ps1"
      - "deploy/astra-worker/**"
      - "tests/test_astra_worker*.py"
      - ".github/workflows/astra-*.yml"
      - "skills/sol-advisor-astra/**"
  pull_request:
    branches: ["cbi-v6-3-demand-expansion"]
permissions:
  contents: read
jobs:
  worker:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.10", "3.11"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m compileall -q astra_worker astra_supervisor scripts/astra_worker.py scripts/astra_task_gate.py scripts/astra_receipt_gate.py
      - run: python -m unittest discover -s tests -p "test_astra_worker*.py" -v
      - run: python -m unittest tests.test_astra_supervisor tests.test_astra_supervisor_executable_boundary -v
      - if: runner.os == 'Linux' && matrix.python-version == '3.11'
        run: python -m pip install --disable-pip-version-check --no-input PyYAML==6.0.2 tzdata==2026.3
      - if: runner.os == 'Linux' && matrix.python-version == '3.11'
        run: python -m unittest discover -s tests -p "test_*.py" -v
```

- [ ] **Step 2: Add an integrated local end-to-end test**

The test creates a temporary pinned source repo + bare mirror, constructs/signs a task, inserts it through a fake queue, executes worker `run_once`, verifies exact file content/test pass/receipt HMAC/patch hashes/cleanup, and proves the original developer checkout is byte-for-byte unchanged.

- [ ] **Step 3: Update the ASTRA skill after tests are green**

Document this exact split:

```text
Sol/ASTRA -> proposed task -> trusted GitHub signer -> outbound-only Windows worker
-> Phase 1 LocalExecutor in ephemeral worktree -> signed receipt -> trusted receipt gate
-> ASTRA review -> GitHub executor exact-base apply -> CI/PR
```

State explicitly that Phase 2A is not an OS sandbox, does not grant arbitrary shell/network/package install, and does not make Codex or ChatGPT usage unlimited.

- [ ] **Step 4: Run focused verification on all supported local test surfaces**

Run:

```bash
python -m compileall -q astra_worker astra_supervisor scripts/astra_worker.py scripts/astra_task_gate.py scripts/astra_receipt_gate.py
python -m unittest discover -s tests -p "test_astra_worker*.py" -v
python -m unittest tests.test_astra_supervisor tests.test_astra_supervisor_executable_boundary -v
```

Expected: all PASS.

- [ ] **Step 5: Run full CBI regression**

Run on Ubuntu/Python 3.11 after installing only the already-pinned regression dependencies:

```bash
python -m pip install --disable-pip-version-check --no-input PyYAML==6.0.2 tzdata==2026.3
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: PASS with no CBI Evidence/WAL/R2/runtime semantic regressions.

- [ ] **Step 6: Fresh diff review against Phase 1 exact baseline**

Run:

```bash
git diff --name-status 7fbf1c15477632f2f36259bd9d91b3074807b3da...HEAD
```

Expected: Phase 2A worker/control-plane/tests/workflows/docs/skill files only. Any CBI business-runtime file in this diff is a stop condition.

- [ ] **Step 7: Commit final integration update**

```bash
git add .github/workflows/astra-worker-ci.yml skills/sol-advisor-astra/SKILL.md tests astra_worker scripts deploy
git commit -m "test(astra-worker): close phase2a acceptance gate"
```

---

## Plan Self-Review Result

- **Spec coverage:** all 40 adversarial-test classes from the Phase 2A spec map to Tasks 1–13: protocol/schema/HMAC (1–4), local secrets/config (2–3/12), replay/crash (5/10), fixed-source synchronization/worktrees (6), capability/pre/final state (7–8), queue/receipt integrity (9), no-listener/kill-switch/cleanup (10), authoritative stale-base apply (11), non-admin service/pinning/ACL (12), Phase 1/full CBI regression (13).
- **Privilege separation:** worker source-write/push/merge authority is absent by construction; authoritative apply remains outside worker and is guarded by Task 11.
- **Continuous-operation gap:** closed by Task 6 fixed-source read-only synchronization rather than manual developer checkout updates.
- **No placeholders:** every task defines concrete files, interfaces, RED command, implementation contract, GREEN command, and commit boundary.
- **Type/interface consistency:** protocol -> models/config -> gates/queue -> ledger/workspace/compiler/evidence -> worker -> apply contract follows one-way dependencies; Phase 1 `ExecutionManifest`/`LocalExecutor` is reused rather than duplicated.
- **Stop condition:** if any implementation task requires arbitrary shell/PowerShell/cmd/Python, task-controlled networking, remote path/refspec authority, worker Contents write, automatic protected-branch push/merge, routine admin/SYSTEM execution, or CBI runtime semantic changes, stop implementation and return to design review.
