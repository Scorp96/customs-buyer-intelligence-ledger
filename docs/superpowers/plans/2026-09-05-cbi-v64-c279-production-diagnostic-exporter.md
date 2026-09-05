# CBI v6.4 C279 Production Diagnostic Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a temporary, static-admin-only, zero-write production diagnostic endpoint that can export exactly one precommitted C279 session JSONL and a capture client that persists only AEAD ciphertext.

**Architecture:** Work on temporary diagnostic branch `cbi-v64-release-candidate-c279-diagnostic-a311a2a5` derived from exact production SHA `a311a2a57ee43a1f1a3b2819bf28946566b05692`. The exporter reads only one fixed server-side JSONL from the already-bound production session root and validates a stable two-read snapshot plus the existing append-only hash chain. A separate capture client validates the response and encrypts it with X25519 + HKDF-SHA256 + ChaCha20-Poly1305. The branch is diagnostic-only and never becomes part of the final v6.4 release candidate.

**Tech Stack:** Python 3.10/3.11, stdlib `unittest`/HTTP stack, existing `unified_runtime.core.digest`, capture-only `cryptography==50.0.1`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-05-cbi-v64-c279-single-session-export-design.md`

## Global Constraints

- Base exact production SHA: `a311a2a57ee43a1f1a3b2819bf28946566b05692`.
- No implementation step changes production branch, Render service/environment/deployment, R2, CRM, or live Runtime.
- Production deployment remains a separate explicit approval gate.
- No private C279 id/hash/route, production bearer, R2 credential, or raw production JSONL is committed or logged.
- Exporter must not call `SessionStore.read()` or `read_valid_prefix()` against production because those acquire lock files.
- Endpoint: `POST /internal/v64/c279-session-export`.
- Exact request body: `{}` with `Content-Type: application/json`; any query string is rejected.
- Auth: exact static `CBI_REMOTE_BEARER_TOKEN` only; GitHub OAuth fallback is rejected.
- Disabled/invalid/expired config => 404.
- Default response cap: 2 MiB. Config values above 8 MiB are invalid.
- Capture dependency never enters production image/runtime.
- Permanent four-matrix release CI and dedicated crypto CI must both be green on the exact diagnostic SHA before a deployment proposal.

---

### Task 1: Diagnostic CI harness and zero-write snapshot validator

**Files:**
- Create test infrastructure: `.github/workflows/cbi-release-ci.yml` copied byte-for-byte from integrated SHA `17f4fe160c0908a602224eab95d172ba4eb753c6`.
- Create RED test: `tests/test_v64_c279_single_session_export.py`.
- Create after RED: `mcp/c279_single_session_export_v64.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class C279ExportConfig:
    investigation_id: str
    expected_tail_seq: int
    expected_tail_hash: str
    expires_at: datetime
    max_bytes: int

@dataclass(frozen=True)
class C279SessionSnapshot:
    payload: bytes
    snapshot_sha256: str
    byte_length: int
    tail_seq: int
    tail_event_hash: str

class C279ExportError(RuntimeError):
    def __init__(self, code: str, http_status: int): ...

def load_export_config(env: Mapping[str, str], *, process_started_at: datetime) -> C279ExportConfig | None: ...
def capture_stable_session(config: C279ExportConfig, session_root: Path) -> C279SessionSnapshot: ...
```

The interface names above are normative; implementation bodies are written only after RED.

- [ ] **Step 1: Create branch from exact production SHA**

Create `cbi-v64-release-candidate-c279-diagnostic-a311a2a5` from `a311a2a57ee43a1f1a3b2819bf28946566b05692`.

- [ ] **Step 2: Add permanent release CI test infrastructure**

Copy `.github/workflows/cbi-release-ci.yml` exactly from `17f4fe160c0908a602224eab95d172ba4eb753c6`. Do not edit production's `.github/workflows/cbi-v6-ci.yml`.

- [ ] **Step 3: Write failing config/snapshot tests**

The test module imports the missing exporter. It must contain concrete assertions for these behaviors:

```python
self.assertIsNone(load_export_config({}, process_started_at=started))
self.assertIsNone(load_export_config({"CBI_V64_C279_EXPORT_ENABLED": "true"}, process_started_at=started))
```

For a valid synthetic fixture created with `SessionStore`, assert:

```python
snapshot = capture_stable_session(config, sessions_root)
self.assertEqual(snapshot.payload, before_bytes)
self.assertEqual(snapshot.byte_length, len(before_bytes))
self.assertEqual(snapshot.tail_seq, expected_seq)
self.assertEqual(snapshot.tail_event_hash, expected_hash)
self.assertEqual(_inventory(sessions_root), before_inventory)
```

Separate tests must mutate fixture bytes/metadata and assert exact `C279ExportError.code` values:

- `SNAPSHOT_INVALID` for malformed UTF-8/JSON, missing header, sequence gap, previous-hash mismatch, event-hash mismatch;
- `SNAPSHOT_COMMITMENT_MISMATCH` for expected seq/hash mismatch;
- `SNAPSHOT_TOO_LARGE` for size cap;
- `SNAPSHOT_NOT_STABLE` when injected first/second read results differ;
- `SNAPSHOT_TARGET_INVALID` for symlink, path escape, non-regular target, or filename/header id mismatch.

- [ ] **Step 4: Witness RED**

```bash
python -m unittest tests.test_v64_c279_single_session_export -v
```

Expected: import failure because `mcp.c279_single_session_export_v64` does not exist. Commit only the failing test and record the exact RED CI run/job ids.

- [ ] **Step 5: Implement configuration parser**

`load_export_config()` uses these exact server-side names:

- `CBI_V64_C279_EXPORT_ENABLED`
- `CBI_V64_C279_EXPORT_EXPIRES_AT`
- `CBI_V64_C279_EXPORT_INVESTIGATION_ID`
- `CBI_V64_C279_EXPORT_EXPECTED_TAIL_SEQ`
- `CBI_V64_C279_EXPORT_EXPECTED_TAIL_HASH`
- `CBI_V64_C279_EXPORT_MAX_BYTES`

Rules:

- missing/false enable => `None`;
- enabled with invalid/missing field => `None`;
- id regex equals existing CBI investigation id regex;
- expected hash regex `[0-9a-f]{64}`;
- expiry parses as timezone-aware UTC, is later than `process_started_at`, and no later than `process_started_at + timedelta(minutes=30)`;
- max bytes default `2 * 1024 * 1024`; accepted range `1..8 * 1024 * 1024`.

- [ ] **Step 6: Implement direct two-read snapshot validation**

Use no Runtime/SessionStore read helper. Exact algorithm:

```python
root = session_root.resolve(strict=True)
candidate = session_root / f"{config.investigation_id}.jsonl"
if candidate.is_symlink():
    raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
resolved = candidate.resolve(strict=True)
if resolved.parent != root:
    raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
pre = os.stat(resolved, follow_symlinks=False)
if not stat.S_ISREG(pre.st_mode):
    raise C279ExportError("SNAPSHOT_TARGET_INVALID", 409)
if pre.st_size > config.max_bytes:
    raise C279ExportError("SNAPSHOT_TOO_LARGE", 413)
first = _bounded_read(resolved, config.max_bytes)
mid = os.stat(resolved, follow_symlinks=False)
second = _bounded_read(resolved, config.max_bytes)
post = os.stat(resolved, follow_symlinks=False)
if first != second or _file_identity(pre) != _file_identity(mid) or _file_identity(mid) != _file_identity(post):
    raise C279ExportError("SNAPSHOT_NOT_STABLE", 409)
```

`_bounded_read()` opens binary read-only and reads at most `max_bytes + 1`; more than `max_bytes` raises 413.

Validate strict UTF-8 and the existing CBI chain contract exactly:

```python
text = first.decode("utf-8")
events = []
previous = "0" * 64
for line_number, line in enumerate(text.splitlines(), 1):
    event = json.loads(line)
    if event.get("seq") != line_number or event.get("prev_hash") != previous:
        raise C279ExportError("SNAPSHOT_INVALID", 409)
    claimed = event.get("event_hash")
    unsigned = {key: value for key, value in event.items() if key != "event_hash"}
    if claimed != digest(unsigned):
        raise C279ExportError("SNAPSHOT_INVALID", 409)
    previous = claimed
    events.append(event)
if not events or events[0].get("event_type") != "INVESTIGATION_STARTED":
    raise C279ExportError("SNAPSHOT_INVALID", 409)
```

Then require start payload investigation id == configured id, tail seq == expected seq, and tail hash == expected hash.

- [ ] **Step 7: Verify GREEN**

```bash
python -m unittest tests.test_v64_c279_single_session_export -v
python -m unittest tests.test_v61_resume_read_only tests.test_v6_properties_and_crash -v
```

- [ ] **Step 8: Commit Task 1 GREEN**

Commit `feat(v64): add zero-write C279 single-session snapshot validator`.

---

### Task 2: Static-admin-only HTTP transport hook

**Files:**
- Create RED test: `tests/test_v64_c279_export_transport.py`.
- Modify after RED: `mcp/remote_transport.py`.
- Modify after RED: `mcp/chatgpt_oauth_transport.py`.

**Interfaces:**

```python
def require_static_bearer(headers: Mapping[str, str], expected_token: str) -> None: ...
```

Extend:

```python
def serve(
    dispatch,
    *,
    health=None,
    host=None,
    port=None,
    diagnostic_export=None,
    diagnostic_static_bearer="",
) -> int: ...
```

- [ ] **Step 1: Write failing HTTP tests**

Start a synthetic local server with callback `lambda: {"schema": "cbi.v64-c279-single-session-export.v1", "snapshot_sha256": "0" * 64, "byte_length": 2, "tail_seq": 1, "tail_event_hash": "1" * 64, "payload_encoding": "base64", "payload": "e30="}` and static token `"S" * 64`.

Assertions:

- callback `None`: diagnostic POST and GET => 404;
- enabled callback, no Authorization => 401;
- bearer `"O" * 64` => 401 and callback counter remains zero;
- URL with `?id=x` => 404;
- Content-Type `text/plain` => 400;
- malformed JSON => 400;
- body `{"x":1}` => 400;
- exact `Authorization: Bearer ` + `"S" * 64` and body `{}` => 200 and callback counter == 1;
- GET/DELETE enabled route => 405;
- success headers include `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`;
- existing `/healthz`, `/mcp`, and OAuth metadata tests remain unchanged.

- [ ] **Step 2: Witness RED**

```bash
python -m unittest tests.test_v64_c279_export_transport -v
```

Commit the failing test before transport code.

- [ ] **Step 3: Implement static bearer primitive**

`require_static_bearer()` parses only `Authorization: Bearer <token>` and uses `hmac.compare_digest`. Errors contain only `Bearer authentication required` or `Invalid bearer credential`.

- [ ] **Step 4: Implement optional route**

In `ChatGPTOAuthRequestHandler`, intercept exactly `/internal/v64/c279-session-export`. If no callback is installed, return 404 before auth. If query exists, return 404. For enabled route require exact static bearer, `application/json`, and parsed `{}`. Call callback once and emit fixed JSON response. Do not register route in MCP discovery, OAuth metadata, or health.

- [ ] **Step 5: Verify GREEN**

```bash
python -m unittest tests.test_v64_c279_export_transport -v
python -m unittest discover -s tests -p "test_*remote*transport*.py" -v
python mcp/v6_protocol_test.py
python mcp/v61_hardening_protocol_test.py
```

- [ ] **Step 6: Commit Task 2**

Commit `feat(v64): add static-admin-only diagnostic HTTP hook`.

---

### Task 3: Production entrypoint binding without R2 side effects

**Files:**
- Create RED test: `tests/test_v64_c279_export_entrypoint_contract.py`.
- Modify after RED: `mcp/c279_single_session_export_v64.py`.
- Modify after RED: `mcp/server_v61_remote.py`.

**Interfaces:**

```python
def build_export_callback(
    session_root: Path,
    env: Mapping[str, str],
    *,
    process_started_at: datetime,
) -> Callable[[], dict[str, Any]] | None: ...
```

- [ ] **Step 1: Write RED tests**

Assert `build_export_callback(..., env={}, ...) is None`; valid synthetic env returns a callable; callback response contains only fixed export schema fields; full live-root inventory and hashes before/after callback are identical.

Also add a structural assertion against `mcp/server_v61_remote.py` that exporter binding uses `_RUNTIME.store.root` and does not call `_PERSISTENCE.restore_into` or `sync_if_changed` from the export callback path.

- [ ] **Step 2: Witness RED**

```bash
python -m unittest tests.test_v64_c279_export_entrypoint_contract -v
```

- [ ] **Step 3: Implement callback builder and entrypoint wiring**

Record `_PROCESS_STARTED_AT = datetime.now(timezone.utc)` at process start. After `_RUNTIME` is bound, call `build_export_callback(_RUNTIME.store.root, os.environ, process_started_at=_PROCESS_STARTED_AT)`. Pass callback plus `CBI_REMOTE_BEARER_TOKEN` to ChatGPT HTTP transport. Do not instantiate another Runtime and do not invoke R2 recovery/sync for an export request.

- [ ] **Step 4: Verify GREEN**

Run focused test and `python mcp/v61_hardening_protocol_test.py`.

- [ ] **Step 5: Commit Task 3**

Commit `feat(v64): bind C279 diagnostic export to production session root`.

---

### Task 4: Ciphertext-only capture client and dedicated crypto CI

**Files:**
- Create RED test: `tests/test_v64_c279_capture.py`.
- Create after RED: `scripts/capture_v64_c279_single_session.py`.
- Create: `requirements/cbi-v64-c279-capture.txt`.
- Create: `.github/workflows/cbi-v64-c279-diagnostic-ci.yml`.

**Interfaces:**

```python
def encrypt_snapshot(payload: bytes, *, snapshot_sha256: str, recipient_public_key_b64: str) -> dict[str, str]: ...
def capture_and_encrypt(*, base_url: str, bearer: str, recipient_public_key_b64: str) -> dict[str, object]: ...
```

Ciphertext schema: `cbi.v64-c279-ciphertext.v1`.

- [ ] **Step 1: Write RED crypto/capture tests**

With synthetic X25519 recipient key and synthetic endpoint response, assert:

- decrypt(encrypt(payload)) == payload;
- ciphertext byte flip raises `cryptography.exceptions.InvalidTag`;
- snapshot hash/AAD change raises `InvalidTag`;
- response byte-length mismatch raises before encryption;
- response SHA mismatch raises before encryption;
- serialized envelope has exact keys `{schema, ephemeral_public_key, salt, nonce, snapshot_sha256, ciphertext}` and does not contain plaintext/base64 plaintext;
- captured exception/log strings never contain synthetic bearer `"B" * 64`;
- CLI writes only ciphertext JSON and creates no persistent plaintext file.

The test class uses `@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography capture dependency not installed")` so ordinary four-matrix CI does not gain a production dependency. Dedicated crypto CI must prove the tests execute, not skip.

- [ ] **Step 2: Add exact capture requirement and dedicated CI before implementation**

`requirements/cbi-v64-c279-capture.txt`:

```text
cryptography==50.0.1
```

Dedicated Ubuntu/Python 3.11 CI downloads one wheel before installation:

```bash
python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: cryptography==50.0.1 -d "$RUNNER_TEMP/c279-crypto"
python - <<'PY'
import hashlib
from pathlib import Path
root = Path(__import__('os').environ['RUNNER_TEMP']) / 'c279-crypto'
files = list(root.glob('cryptography-50.0.1-*.whl'))
assert len(files) == 1, files
sha = hashlib.sha256(files[0].read_bytes()).hexdigest()
allowed = {
    '51afcfceb15597cf2635068e4ac9a56b2abde622edde17f37d85fd7b5306497a',
    '51593d180cf6d179bde5c5d065bed81386b1f381656ae7d042b7ffc87a9895ad',
    'ff838d62ec1bfce4f9ba7fa16f4a7b554cd8d0c299e6be37502161a660c84eef',
}
assert sha in allowed, sha
print('CRYPTOGRAPHY_WHEEL_SHA256_VERIFIED=' + sha)
PY
python -m pip install "$RUNNER_TEMP"/c279-crypto/cryptography-50.0.1-*.whl
```

Those three hashes are the published CPython 3.11+ x86-64 Linux wheels for manylinux 2.34, 2.28 and 2.17 compatibility tiers. If GitHub's runner selects another artifact, CI fails closed until the plan is reviewed and updated.

- [ ] **Step 3: Witness RED in dedicated CI**

Run focused `tests.test_v64_c279_capture`; it must fail because capture implementation does not exist, and the job must show the crypto test was not skipped.

- [ ] **Step 4: Implement exact AEAD**

```python
shared = ephemeral_private.exchange(recipient_public)
salt = os.urandom(32)
nonce = os.urandom(12)
key = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=salt,
    info=b"cbi-v64-c279-export-v1",
).derive(shared)
aad = b"cbi.v64-c279-ciphertext.v1|" + snapshot_sha256.encode("ascii")
ciphertext = ChaCha20Poly1305(key).encrypt(nonce, payload, aad)
```

Serialize raw ephemeral X25519 public key, salt, nonce and ciphertext as base64 strings. Private recipient key never enters capture runner or production.

- [ ] **Step 5: Implement HTTP capture validation**

Use `urllib.request` to POST exact `{}`. Validate export schema, `payload_encoding == "base64"`, decoded length, and SHA-256 before encryption. Never log response body, bearer, investigation id, or tail hash.

- [ ] **Step 6: Verify GREEN**

Dedicated CI must show crypto test execution and PASS. Run permanent four-matrix release CI too; crypto-only test may skip there, but all exporter/transport/entrypoint tests must execute and pass on all four matrices.

- [ ] **Step 7: Commit Task 4**

Commit `feat(v64): add ciphertext-only C279 diagnostic capture client`.

---

### Task 5: Exact-SHA diagnostic verification

- [ ] **Step 1: Require permanent four-matrix CI GREEN**

Required contexts:

- `regression (ubuntu-latest, py3.10)`
- `regression (ubuntu-latest, py3.11)`
- `regression (windows-latest, py3.10)`
- `regression (windows-latest, py3.11)`

- [ ] **Step 2: Require dedicated crypto CI GREEN**

Logs must show one allowed `CRYPTOGRAPHY_WHEEL_SHA256_VERIFIED=<hash>` and capture tests executed rather than skipped.

- [ ] **Step 3: Inspect privacy and branch scope**

Run `python tests/privacy_scan.py`. Compare branch against `a311a2a57ee43a1f1a3b2819bf28946566b05692`; changes must be limited to diagnostic exporter/transport/entrypoint, capture client, tests, diagnostic requirements/workflows and checkpoint docs.

- [ ] **Step 4: Fresh production invariants**

Fetch production branch and Render live deploy. Production must still be `a311a2a57ee43a1f1a3b2819bf28946566b05692` because deployment is not yet authorized.

---

### Task 6: Pre-production review package — mandatory stop

**Files:**
- Create: `docs/superpowers/checkpoints/2026-09-05-v64-c279-diagnostic-preproduction-review.md`.

- [ ] **Step 1: Record exact evidence**

Include diagnostic HEAD SHA, RED/green run ids, four matrix results, dedicated crypto result/hash, changed-file list, endpoint-disabled-by-default proof, zero-live-root-mutation proof, and `PRODUCTION_MUTATION_PERFORMED=false`.

- [ ] **Step 2: Record future deployment sequence without executing it**

A later explicit approval must cover: fresh production SHA/health, secure static-bearer caller channel, auditable fast-forward diagnostic Git commits, private Render env configuration, deployment, one-session capture, immediate ciphertext handoff, disable, fast-forward revert restoring ordinary code tree, redeploy, endpoint absence, and production durable/R2 continuity.

- [ ] **Step 3: STOP**

Do not update production branch, Render environment/deploy, R2, CRM, live Runtime, PR merge state, or repository ruleset. Present this review package for explicit production-deployment approval.
