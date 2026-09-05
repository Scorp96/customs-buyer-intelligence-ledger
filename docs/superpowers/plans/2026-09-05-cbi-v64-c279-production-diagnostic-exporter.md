# CBI v6.4 C279 Production Diagnostic Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a temporary, static-admin-only, zero-write production diagnostic endpoint that can export exactly one precommitted C279 session JSONL and a capture client that persists only AEAD ciphertext.

**Architecture:** Work on a temporary diagnostic branch derived from exact production SHA `a311a2a57ee43a1f1a3b2819bf28946566b05692`. The exporter reads one fixed server-side target from the already-bound production session root, validates a stable two-read snapshot and the existing append-only hash chain, and returns it only through a fixed authenticated endpoint. A separate capture client encrypts the response with X25519 + HKDF-SHA256 + ChaCha20-Poly1305. This branch is diagnostic-only and is not merged into the final v6.4 candidate.

**Tech Stack:** Python 3.10/3.11, stdlib HTTP server and unittest, existing `unified_runtime.core.digest`, `cryptography==50.0.1` for capture-only AEAD, GitHub Actions. PyPI source distribution SHA256 for `cryptography-50.0.1.tar.gz`: `693c99b49bd37d0d096e4334c10232c77248c415b98d35236094cdf96d57258b`.

**Spec:** `docs/superpowers/specs/2026-09-05-cbi-v64-c279-single-session-export-design.md`

## Global Constraints

- Base exact production SHA: `a311a2a57ee43a1f1a3b2819bf28946566b05692`.
- Branch name: `cbi-v64-release-candidate-c279-diagnostic-a311a2a5`.
- The branch may contain diagnostic code and test infrastructure only; it is never merged into the final v6.4 release candidate.
- No private C279 id/hash/route, production bearer, R2 credential, or raw production JSONL may be committed or logged.
- No implementation step mutates Render, production branch, production environment, R2, or live Runtime.
- Production deployment remains a separate explicit approval gate after all implementation and security evidence is green.
- `SessionStore.read()` / `read_valid_prefix()` must not be used by the exporter because they acquire live-root lock files.
- The diagnostic endpoint is `POST /internal/v64/c279-session-export`, takes exact body `{}`, accepts no query string, and requires the exact static `CBI_REMOTE_BEARER_TOKEN`; GitHub OAuth alone is rejected.
- Disabled/invalid/expired configuration makes the route 404.
- Default response cap is 2 MiB; values above 8 MiB make configuration invalid.
- The capture dependency is not installed into the production image/runtime.

---

### Task 1: Diagnostic branch CI harness and snapshot-validator RED

**Files:**
- Create: `.github/workflows/cbi-release-ci.yml` by copying the already-approved permanent release CI from integrated SHA `17f4fe160c0908a602224eab95d172ba4eb753c6` unchanged.
- Create: `tests/test_v64_c279_single_session_export.py`
- Create after RED: `mcp/c279_single_session_export_v64.py`

**Interfaces:**
- Produces `C279ExportConfig` dataclass.
- Produces `C279ExportError(code: str, http_status: int)`.
- Produces `load_export_config(env: Mapping[str, str], *, process_started_at: datetime) -> C279ExportConfig | None`.
- Produces `capture_stable_session(config: C279ExportConfig, session_root: Path) -> C279SessionSnapshot`.
- `C279SessionSnapshot` fields: `payload: bytes`, `snapshot_sha256: str`, `byte_length: int`, `tail_seq: int`, `tail_event_hash: str`.

- [ ] **Step 1: Create branch from exact production SHA**

Create `cbi-v64-release-candidate-c279-diagnostic-a311a2a5` from `a311a2a57ee43a1f1a3b2819bf28946566b05692`.

- [ ] **Step 2: Add permanent release CI workflow as diagnostic test infrastructure**

Copy `.github/workflows/cbi-release-ci.yml` byte-for-byte from integrated SHA `17f4fe160...`. This gives the diagnostic branch the same four OS/Python contexts without changing production.

- [ ] **Step 3: Write failing snapshot/config tests**

The first test imports the missing module and therefore must fail before implementation.

Required test cases:

```python
class V64C279SingleSessionExportTests(unittest.TestCase):
    def test_disabled_configuration_returns_none(self): ...
    def test_enabled_configuration_requires_exact_private_fields(self): ...
    def test_expiry_more_than_30_minutes_after_process_start_is_invalid(self): ...
    def test_max_bytes_defaults_to_2_mib_and_rejects_over_8_mib(self): ...
    def test_valid_exact_session_is_captured_without_live_root_mutation(self): ...
    def test_symlink_target_is_rejected(self): ...
    def test_non_regular_target_is_rejected(self): ...
    def test_oversized_target_is_rejected_before_returning_payload(self): ...
    def test_sequence_break_is_rejected(self): ...
    def test_previous_hash_break_is_rejected(self): ...
    def test_event_hash_break_is_rejected(self): ...
    def test_tail_sequence_mismatch_is_rejected(self): ...
    def test_tail_hash_mismatch_is_rejected(self): ...
    def test_first_and_second_read_change_is_rejected(self): ...
```

Use a synthetic `SessionStore` only to create fixture bytes before taking the inventory snapshot. The exporter itself must operate directly on bytes and may not call `SessionStore.read()`.

- [ ] **Step 4: Witness RED**

Run focused unittest. Expected: FAIL because `mcp.c279_single_session_export_v64` does not exist. Commit RED test only and record the exact CI run/job failure.

- [ ] **Step 5: Implement configuration parser and pure snapshot validator**

Core configuration contract:

```python
@dataclass(frozen=True)
class C279ExportConfig:
    investigation_id: str
    expected_tail_seq: int
    expected_tail_hash: str
    expires_at: datetime
    max_bytes: int = 2 * 1024 * 1024
```

`load_export_config()` behavior:

- false/missing `CBI_V64_C279_EXPORT_ENABLED` -> `None`;
- enabled but any required field invalid -> `None`;
- expected hash must match `[0-9a-f]{64}`;
- id must match existing CBI investigation regex;
- expiry must be UTC, in the future, and `<= process_started_at + 30 minutes`;
- max bytes defaults 2 MiB and must be `1..8 MiB`.

Snapshot algorithm:

```python
root = session_root.resolve(strict=True)
candidate = session_root / f"{config.investigation_id}.jsonl"
if candidate.is_symlink(): reject
resolved = candidate.resolve(strict=True)
if resolved.parent != root: reject
pre = os.stat(resolved, follow_symlinks=False)
if not stat.S_ISREG(pre.st_mode): reject
if pre.st_size > config.max_bytes: raise SNAPSHOT_TOO_LARGE
first = _bounded_read(resolved, config.max_bytes)
mid = os.stat(resolved, follow_symlinks=False)
second = _bounded_read(resolved, config.max_bytes)
post = os.stat(resolved, follow_symlinks=False)
if first != second or _identity(pre) != _identity(mid) or _identity(mid) != _identity(post):
    raise SNAPSHOT_NOT_STABLE
```

Validate strict UTF-8 JSONL using the same contract as `SessionStore._read_unlocked`:

```python
previous = "0" * 64
for line_number, line in enumerate(text.splitlines(), 1):
    event = json.loads(line)
    if event.get("seq") != line_number or event.get("prev_hash") != previous:
        reject SNAPSHOT_INVALID
    claimed = event.get("event_hash")
    unsigned = {key: value for key, value in event.items() if key != "event_hash"}
    if claimed != digest(unsigned):
        reject SNAPSHOT_INVALID
    previous = claimed
if not events or events[0].get("event_type") != "INVESTIGATION_STARTED": reject
```

Also require `events[0]["payload"]["investigation_id"] == config.investigation_id`, exact expected tail seq, and exact expected tail hash.

- [ ] **Step 6: Verify GREEN**

Run focused tests, then:

```bash
python -m unittest tests.test_v61_resume_read_only tests.test_v6_properties_and_crash -v
```

- [ ] **Step 7: Commit Task 1 GREEN**

Commit with `feat(v64): add zero-write C279 single-session snapshot validator`.

---

### Task 2: Static-admin-only HTTP transport hook

**Files:**
- Create: `tests/test_v64_c279_export_transport.py`
- Modify after RED: `mcp/remote_transport.py`
- Modify after RED: `mcp/chatgpt_oauth_transport.py`

**Interfaces:**
- Produce `require_static_bearer(headers: Mapping[str, str], expected_token: str) -> None` in `mcp.remote_transport`.
- Extend `chatgpt_oauth_transport.serve(..., diagnostic_export: Callable[[], dict[str, Any]] | None = None, diagnostic_static_bearer: str = "")`.
- Exact path constant: `/internal/v64/c279-session-export`.

- [ ] **Step 1: Write failing transport tests**

Tests instantiate the HTTP handler/server with a synthetic callback and prove:

- callback `None` -> POST/GET diagnostic path is 404;
- valid callback but no bearer -> 401;
- OAuth-looking bearer that differs from exact static token -> 401 without invoking GitHub verifier;
- query string -> 404;
- wrong Content-Type -> 400;
- malformed JSON -> 400;
- body other than `{}` -> 400;
- exact static bearer + `{}` -> 200 callback result;
- GET/DELETE on enabled route -> 405;
- `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` on JSON response;
- `/mcp`, `/healthz`, OAuth metadata remain unchanged.

- [ ] **Step 2: Witness RED**

Run focused transport tests and commit the failing test before transport code.

- [ ] **Step 3: Implement `require_static_bearer`**

Use `hmac.compare_digest`; never expose token in exception text. Existing auth behavior must remain unchanged.

- [ ] **Step 4: Implement optional diagnostic route**

In `ChatGPTOAuthRequestHandler`, intercept only the exact diagnostic path. Do not add it to MCP discovery or OAuth metadata. `server.diagnostic_export` and `server.diagnostic_static_bearer` are set only when a callback is supplied.

Success response schema must contain only:

```json
{
  "schema": "cbi.v64-c279-single-session-export.v1",
  "snapshot_sha256": "...",
  "byte_length": 123,
  "tail_seq": 27,
  "tail_event_hash": "...",
  "payload_encoding": "base64",
  "payload": "..."
}
```

All failure responses omit session bytes and private expected/actual values.

- [ ] **Step 5: Verify GREEN and existing transport regressions**

Run focused test plus existing OAuth/remote-transport tests and MCP protocol tests.

- [ ] **Step 6: Commit Task 2**

Commit `feat(v64): add static-admin-only diagnostic HTTP hook`.

---

### Task 3: Production entrypoint binding without R2/export side effects

**Files:**
- Create: `tests/test_v64_c279_export_entrypoint_contract.py`
- Modify after RED: `mcp/server_v61_remote.py`

**Interfaces:**
- `build_export_callback(session_root: Path, env: Mapping[str, str], process_started_at: datetime) -> Callable[[], dict[str, Any]] | None` lives in `mcp/c279_single_session_export_v64.py`.
- Production entrypoint passes the callback and `CBI_REMOTE_BEARER_TOKEN` to `chatgpt_oauth_transport.main` only when config is valid.

- [ ] **Step 1: Write structural/behavioral RED tests**

Prove disabled/invalid env produces no callback; valid synthetic env binds only `_RUNTIME.store.root`; callback invocation changes neither live-root inventory/hashes nor object-store generation surrogate in the synthetic fixture.

- [ ] **Step 2: Witness RED**

Focused test fails because entrypoint callback binding is absent.

- [ ] **Step 3: Implement minimal entrypoint wiring**

At process start record `_PROCESS_STARTED_AT = datetime.now(timezone.utc)`. After `_RUNTIME` is bound, build the callback using `_RUNTIME.store.root`. Do not instantiate another Runtime, call `_PERSISTENCE.restore_into`, `sync_if_changed`, or touch `_LIVE_ROOT` manifests for export.

- [ ] **Step 4: Verify GREEN**

Run entrypoint contract test, production-adapter protocol test, and Docker smoke through CI.

- [ ] **Step 5: Commit Task 3**

Commit `feat(v64): bind C279 diagnostic export to production session root`.

---

### Task 4: Capture client TDD and pinned AEAD envelope

**Files:**
- Create: `tests/test_v64_c279_capture.py`
- Create after RED: `scripts/capture_v64_c279_single_session.py`
- Create: `requirements/cbi-v64-c279-capture.txt`
- Create: `.github/workflows/cbi-v64-c279-diagnostic-ci.yml`

**Interfaces:**
- Produce `encrypt_snapshot(payload: bytes, *, snapshot_sha256: str, recipient_public_key_b64: str) -> dict[str, str]`.
- Produce `capture_and_encrypt(*, base_url: str, bearer: str, recipient_public_key_b64: str) -> dict[str, object]`.
- Ciphertext schema: `cbi.v64-c279-ciphertext.v1`.

- [ ] **Step 1: Write failing capture/crypto tests**

Tests use synthetic keys and HTTP fixture. Required cases:

- byte-identical encrypt/decrypt roundtrip;
- ciphertext tamper -> `InvalidTag`;
- associated-data snapshot hash tamper -> `InvalidTag`;
- response byte length mismatch rejected before encryption;
- response SHA mismatch rejected before encryption;
- bearer never appears in exception/log capture;
- output envelope contains no plaintext/base64 plaintext field;
- temporary plaintext file, when CLI path is exercised, is removed before exit.

Use `unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography capture dependency not installed")` only so permanent four-matrix CI can run without adding the dependency to ordinary production CI. The dedicated diagnostic CI below must install it and must show these tests actually execute rather than skip.

- [ ] **Step 2: Witness RED in dedicated diagnostic CI**

Create the diagnostic workflow before implementation. It runs Ubuntu latest / Python 3.11, installs capture requirements, asserts `cryptography.__version__ == "50.0.1"`, runs focused tests and then all `test_v64_c279_*` tests.

`requirements/cbi-v64-c279-capture.txt` must pin:

```text
cryptography==50.0.1
```

The plan/checkpoint records PyPI source SHA256 `693c99b49bd37d0d096e4334c10232c77248c415b98d35236094cdf96d57258b`; the diagnostic CI must download the sdist metadata or package artifact and verify the selected package provenance/hash before running capture tests. If the exact artifact hash cannot be deterministically verified, the diagnostic CI fails closed rather than silently installing an unverified version.

- [ ] **Step 3: Implement exact X25519/HKDF/ChaCha20-Poly1305 envelope**

Use:

```python
shared = ephemeral_private.exchange(recipient_public)
key = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=salt,
    info=b"cbi-v64-c279-export-v1",
).derive(shared)
aad = b"cbi.v64-c279-ciphertext.v1|" + snapshot_sha256.encode("ascii")
ciphertext = ChaCha20Poly1305(key).encrypt(nonce, payload, aad)
```

Envelope fields: `schema`, `ephemeral_public_key`, `salt`, `nonce`, `snapshot_sha256`, `ciphertext`; all binary values base64url/standard base64 consistently documented in code.

- [ ] **Step 4: Implement capture HTTP validation**

Use `urllib.request`; POST exact `{}` with static bearer; validate response schema, payload encoding, decoded byte length and SHA before encryption. Never print response body or bearer.

- [ ] **Step 5: Verify GREEN**

Dedicated diagnostic CI must show capture tests executed and passed. Permanent release CI may skip crypto-only tests if dependency is absent but all non-crypto diagnostic tests must pass on all four matrices.

- [ ] **Step 6: Commit Task 4**

Commit `feat(v64): add ciphertext-only C279 diagnostic capture client`.

---

### Task 5: Full diagnostic exact-SHA verification

**Files:**
- No new runtime files unless a regression requires a TDD fix.

- [ ] **Step 1: Wait for both workflows on exact diagnostic head**

Required:

1. four permanent release contexts green;
2. dedicated `CBI v6.4 C279 diagnostic CI` green with crypto tests executed.

- [ ] **Step 2: Inspect all jobs and logs**

Confirm no private values, no plaintext session fixture beyond synthetic data, no secret echo, and Docker smoke remains green.

- [ ] **Step 3: Run privacy scan and compare branch scope**

Changed files must be limited to diagnostic exporter, transport/entrypoint changes, capture client, focused tests, diagnostic test requirements/workflows, and review/checkpoint docs.

- [ ] **Step 4: Verify production remained untouched**

Fresh-fetch production branch SHA and Render live deployment. Both must still be exact pre-diagnostic state because no deployment has been authorized.

---

### Task 6: Pre-production deployment review package — STOP before mutation

**Files:**
- Create: `docs/superpowers/checkpoints/2026-09-05-v64-c279-diagnostic-preproduction-review.md`

- [ ] **Step 1: Record exact implementation evidence**

Include exact diagnostic SHA, RED run ids, GREEN run ids, four-matrix results, dedicated crypto CI result, changed-file list, and proof endpoint defaults to 404.

- [ ] **Step 2: Record exact future mutation sequence without executing it**

The package must state that a later separately approved deployment would require:

1. fresh production SHA/health check;
2. secure production static-bearer caller channel;
3. fast-forward diagnostic commits from the exact production baseline;
4. private env configuration through Render without printing values;
5. deployment and health check;
6. fixed endpoint capture and immediate ciphertext handoff;
7. explicit disable;
8. fast-forward revert commit restoring ordinary production tree;
9. redeploy and verify endpoint absent;
10. verify production durable state/R2 generation continuity.

- [ ] **Step 3: STOP**

Do not update the production branch, Render environment, Render deployment, R2, or production ruleset. Present the pre-production review package for explicit human approval.
