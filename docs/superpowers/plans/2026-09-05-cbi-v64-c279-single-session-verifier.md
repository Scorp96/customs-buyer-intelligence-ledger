# CBI v6.4 C279 Single-Session Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that one authoritative C279 session JSONL is sufficient for the integrated v6.4 Runtime regression and provide a reusable isolated verifier that never needs the complete production runtime root.

**Architecture:** Work on an isolated candidate-proof branch derived from integrated candidate `17f4fe160c0908a602224eab95d172ba4eb753c6`. The verifier copies exactly one JSONL into a fresh temporary `sessions/` root, instantiates the integrated `UnifiedRuntime` there, verifies the bridge tail, evaluates readiness and closure, calls `prepare_outreach`, and emits sanitized pass/fail metadata only. No production exporter code belongs on this branch.

**Tech Stack:** Python 3.10/3.11, stdlib `unittest`, `tempfile`, `pathlib`, existing `UnifiedRuntime` APIs, GitHub Actions permanent release CI.

**Spec:** `docs/superpowers/specs/2026-09-05-cbi-v64-c279-single-session-export-design.md`

## Global Constraints

- Base exact integrated candidate SHA: `17f4fe160c0908a602224eab95d172ba4eb753c6`.
- Branch name: `cbi-v64-release-candidate-c279-proof-17f4fe16` so the existing permanent release CI runs automatically.
- Never commit a private C279 investigation id, tail hash, route value, bridge JSON, bearer, R2 credential, or raw production JSONL.
- Private authoritative inputs are supplied only through file paths in environment variables at execution time.
- The source JSONL is never mutated. The verifier operates only on a copied JSONL inside `TemporaryDirectory`.
- `prepare_outreach` may mutate only the isolated copy and must return `sends_message == false`.
- If one JSONL proves insufficient, stop and return to design; do not broaden production export automatically.

---

### Task 1: Single-session sufficiency TDD gate

**Files:**
- Create: `tests/test_v64_c279_single_session_verifier.py`
- Create after RED: `scripts/verify_v64_c279_single_session.py`

**Interfaces:**
- Produces: `verify_single_session(*, bridge: dict, source_jsonl: Path) -> dict[str, object]`.
- Receipt keys: `status`, `tail_match`, `outreach_readiness`, `closure_closed`, `prepared`, `sends_message`, `source_unchanged`.

- [ ] **Step 1: Create the proof branch from exact integrated SHA**

Create `cbi-v64-release-candidate-c279-proof-17f4fe16` from `17f4fe160c0908a602224eab95d172ba4eb753c6`.

- [ ] **Step 2: Write the failing synthetic sufficiency test**

Create `tests/test_v64_c279_single_session_verifier.py`. The import below must fail before the implementation exists:

```python
from pathlib import Path
import tempfile
import unittest

from unified_runtime import UnifiedRuntime
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG
from scripts.verify_v64_c279_single_session import verify_single_session


def _observation(claim_key: str, index: int) -> dict:
    value: object = {"fixture": claim_key}
    if claim_key == "contact.company_route":
        value = {
            "channel": "EMAIL",
            "value": "buyer@example.invalid",
            "verified": True,
            "current": True,
            "owned_by_account": True,
            "masked": False,
            "guessed": False,
        }
    return {
        "claim_key": claim_key,
        "result": "POSITIVE",
        "owner_type": "ACCOUNT",
        "owner_id": "C-SINGLE-SESSION",
        "value": value,
        "source": {
            "source_family": "synthetic_single_session",
            "source_type": "OFFICIAL",
            "reference_type": "PUBLIC_URL",
            "url": f"https://example.invalid/single/{index}",
            "locator": f"https://example.invalid/single/{index}#fact",
            "raw_excerpt": f"Synthetic single-session fixture {index}",
            "authority_level": "A1_OFFICIAL_PRIMARY",
            "freshness": "CURRENT",
            "observed_at": "2026-09-05T00:00:00Z",
        },
        "boundary": "Synthetic test fixture only.",
    }


def _build_fixture(runtime: UnifiedRuntime) -> tuple[str, dict]:
    started = runtime.start_investigation({
        "account": {
            "account_id": "C-SINGLE-SESSION",
            "country": "Synthetic",
            "name": "Single Session Buyer",
        },
        "mode": "EXHAUSTIVE",
        "history": {"events": []},
        "priority_grade": "A",
    })
    investigation_id = started["investigation_id"]
    runtime.compile_and_append_research_bundle({
        "investigation_id": investigation_id,
        "bundle": {
            "bundle_id": "BUNDLE-SINGLE-SESSION",
            "observations": [
                _observation(claim_key, index)
                for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG)
            ],
        },
    })
    state = runtime.get_investigation_state({"investigation_id": investigation_id})
    bridge = {
        "investigation_id": investigation_id,
        "durable_state": {
            "last_safe_seq": state["last_safe_seq"],
            "last_safe_event_hash": state["last_safe_event_hash"],
        },
    }
    return investigation_id, bridge


class V64C279SingleSessionVerifierTests(unittest.TestCase):
    def test_one_jsonl_is_sufficient_for_full_isolated_outreach_proof(self):
        with tempfile.TemporaryDirectory(prefix="cbi-v64-single-test-") as temp:
            source_sessions = Path(temp) / "source" / "sessions"
            runtime = UnifiedRuntime(source_sessions)
            investigation_id, bridge = _build_fixture(runtime)
            source_jsonl = runtime.store.path(investigation_id)
            before = source_jsonl.read_bytes()

            receipt = verify_single_session(bridge=bridge, source_jsonl=source_jsonl)

            self.assertEqual(receipt["status"], "PASS")
            self.assertTrue(receipt["tail_match"])
            self.assertTrue(receipt["closure_closed"])
            self.assertTrue(receipt["prepared"])
            self.assertFalse(receipt["sends_message"])
            self.assertTrue(receipt["source_unchanged"])
            self.assertEqual(source_jsonl.read_bytes(), before)
```

- [ ] **Step 3: Run the focused test and witness RED**

Run:

```bash
python -m unittest tests.test_v64_c279_single_session_verifier -v
```

Expected: import failure because `scripts.verify_v64_c279_single_session` does not exist. Fix only fixture/syntax mistakes if needed; do not add implementation until the failure is specifically feature-missing.

- [ ] **Step 4: Commit RED evidence**

Commit only the failing test and record the permanent release CI run/job ids for that exact RED SHA.

- [ ] **Step 5: Implement the minimal isolated verifier**

Create `scripts/verify_v64_c279_single_session.py` with this constant and callable:

```python
SAFE_FIRST_TOUCH_BODY = (
    "Hello, I’m contacting your company from XingHuai New Materials. We manufacture PVC foam board "
    "and related rigid panel materials for distribution, cabinetry, interior fabrication, signage and "
    "general sheet applications. I would like to understand whether your purchasing team is open to "
    "evaluating an additional qualified supply source. We can provide a concise product overview and "
    "then prepare technical information only against requirements that your team confirms. Could you "
    "please direct this message to the colleague responsible for purchasing or sourcing sheet materials? "
    "If this category is not relevant, no further action is needed. Best regards, Mark Zhou"
)


def verify_single_session(*, bridge: dict, source_jsonl: Path) -> dict[str, object]:
    investigation_id = str(bridge["investigation_id"])
    expected = dict(bridge["durable_state"])
    if source_jsonl.name != f"{investigation_id}.jsonl":
        raise AssertionError("source session filename does not match bridge")
    source_before = source_jsonl.read_bytes()
    with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-single-") as temp:
        sessions = Path(temp) / "sessions"
        sessions.mkdir(parents=True)
        isolated_jsonl = sessions / source_jsonl.name
        isolated_jsonl.write_bytes(source_before)
        runtime = UnifiedRuntime(sessions)
        state = runtime.get_investigation_state({"investigation_id": investigation_id})
        tail_match = (
            state["last_safe_seq"] == int(expected["last_safe_seq"])
            and state["last_safe_event_hash"] == str(expected["last_safe_event_hash"])
        )
        if not tail_match:
            raise AssertionError("authoritative tail commitment mismatch")
        readiness = runtime.evaluate_outreach_readiness({"investigation_id": investigation_id})
        routes = [row for row in readiness.get("canonical_route_view", []) if isinstance(row, dict)]
        if not routes:
            raise AssertionError("canonical route unavailable")
        closure = runtime.evaluate_investigation_closure({"investigation_id": investigation_id})
        if not closure.get("closed"):
            raise AssertionError("investigation did not close on isolated copy")
        start = runtime._v6_state(investigation_id)["start"]
        prepared = runtime.prepare_outreach({
            "investigation_id": investigation_id,
            "closure_id": closure["closure_id"],
            "route": routes[0],
            "history_digest": start.get("history_digest"),
            "authority_digest": start.get("authority_digest"),
            "subject": "PVC sheet sourcing contact",
            "body": SAFE_FIRST_TOUCH_BODY,
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        })
    source_after = source_jsonl.read_bytes()
    return {
        "status": "PASS",
        "tail_match": True,
        "outreach_readiness": readiness.get("outreach_readiness") or readiness.get("readiness"),
        "closure_closed": bool(closure.get("closed")),
        "prepared": bool(prepared.get("prepared")),
        "sends_message": bool(prepared.get("sends_message")),
        "source_unchanged": source_before == source_after,
    }
```

Imports are exactly `json`, `os`, `tempfile`, `datetime`, `timedelta`, `timezone`, `Path`, and `UnifiedRuntime` as required by callable/CLI code.

- [ ] **Step 6: Run focused test and witness GREEN**

Run the same unittest. Expected: one test PASS; source bytes unchanged; `sends_message == false`.

- [ ] **Step 7: Run neighboring runtime regressions**

```bash
python -m unittest tests.test_v61_resume_read_only tests.test_v61_outreach_hardening tests.test_v6_architecture -v
```

Expected: all PASS.

- [ ] **Step 8: Commit Task 1 GREEN**

Commit `test(v64): prove C279 single-session isolated runtime sufficiency`.

---

### Task 2: Authoritative-input CLI without private repository data

**Files:**
- Modify: `scripts/verify_v64_c279_single_session.py`
- Create: `tests/test_v64_c279_single_session_authoritative.py`

**Interfaces:**
- Reads env paths `CBI_V64_C279_BRIDGE_EVIDENCE` and `CBI_V64_C279_SOURCE_SESSION_JSONL`.
- CLI argument: `--output <path>`.
- Output schema: `cbi.v64-c279-single-session-proof.v1`.

- [ ] **Step 1: Write failing CLI-contract tests**

Tests must use synthetic temporary bridge/session files and assert these exact behaviors:

```python
self.assertEqual(main(["--output", str(output)]), 2)  # missing required env
self.assertFalse(output.exists())
```

For a successful synthetic run, parse the output and assert its key set equals exactly:

```python
{
    "schema",
    "status",
    "tail_match",
    "outreach_readiness",
    "closure_closed",
    "prepared",
    "sends_message",
    "source_unchanged",
}
```

Assert that serialized output does not contain the synthetic investigation id, expected tail hash, or route value `buyer@example.invalid`.

- [ ] **Step 2: Witness RED**

```bash
python -m unittest tests.test_v64_c279_single_session_authoritative -v
```

Expected: FAIL because CLI/env adapter does not yet exist.

- [ ] **Step 3: Implement CLI/env adapter**

`main(argv=None) -> int` reads both env paths, loads JSON bridge, validates the source filename, calls `verify_single_session`, writes only this shape, and returns zero:

```python
safe_receipt = {
    "schema": "cbi.v64-c279-single-session-proof.v1",
    "status": receipt["status"],
    "tail_match": receipt["tail_match"],
    "outreach_readiness": receipt["outreach_readiness"],
    "closure_closed": receipt["closure_closed"],
    "prepared": receipt["prepared"],
    "sends_message": receipt["sends_message"],
    "source_unchanged": receipt["source_unchanged"],
}
```

Missing env/invalid input returns 2 and writes no output. Verification failure returns 1 and writes no private data.

- [ ] **Step 4: Verify GREEN and privacy scan**

```bash
python -m unittest tests.test_v64_c279_single_session_authoritative -v
python tests/privacy_scan.py
```

- [ ] **Step 5: Commit Task 2**

Commit `feat(v64): add sanitized C279 single-session verifier CLI`.

---

### Task 3: Exact-SHA candidate proof verification

**Files:**
- Create after GREEN: `docs/superpowers/checkpoints/2026-09-05-v64-c279-single-session-verifier-green.md`

- [ ] **Step 1: Require all permanent Release CI contexts on Task 2 exact SHA**

- `regression (ubuntu-latest, py3.10)`
- `regression (ubuntu-latest, py3.11)`
- `regression (windows-latest, py3.10)`
- `regression (windows-latest, py3.11)`

- [ ] **Step 2: Inspect jobs**

Require unittest regression, load acceptance, MCP self-tests, privacy scan and Linux Docker smoke all green.

- [ ] **Step 3: Verify topology**

Compare base `17f4fe160c0908a602224eab95d172ba4eb753c6` to proof head. Require `behind_by == 0`. Changed files before the checkpoint must be only the two verifier tests and `scripts/verify_v64_c279_single_session.py`.

- [ ] **Step 4: Record sanitized checkpoint**

Record exact RED SHA/run, exact GREEN SHA/run, four matrix results, and `PRODUCTION_STATE_ACCESSED=false`, `PRODUCTION_STATE_MUTATED=false`.

---

### Task 4: Hold authoritative C279 execution until ciphertext capture exists

- [ ] **Step 1: Do not substitute non-authoritative inputs**

Do not use generation-0 migration archives, acceptance namespace artifacts, semantic MCP projections, or reconstructed JSONL.

- [ ] **Step 2: Run only after Plan B yields the decrypted exact JSONL**

The private environment must set real filesystem paths outside Git; the public command is:

```bash
python scripts/verify_v64_c279_single_session.py --output "$CBI_V64_C279_SANITIZED_OUTPUT"
```

`CBI_V64_C279_BRIDGE_EVIDENCE`, `CBI_V64_C279_SOURCE_SESSION_JSONL`, and `CBI_V64_C279_SANITIZED_OUTPUT` are supplied through the private execution environment.

- [ ] **Step 3: Accept only sanitized release evidence**

The public checkpoint may record pass/fail booleans and readiness class but not investigation id, source hash, tail hash, route value, or source path.
