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
- Produces: `verify_single_session(*, bridge: dict, source_jsonl: Path) -> dict[str, object]`
- Produces sanitized receipt keys: `status`, `tail_match`, `outreach_readiness`, `closure_closed`, `prepared`, `sends_message`, `source_unchanged`.

- [ ] **Step 1: Create the proof branch from exact integrated SHA**

Create `cbi-v64-release-candidate-c279-proof-17f4fe16` from `17f4fe160c0908a602224eab95d172ba4eb753c6`.

- [ ] **Step 2: Write the failing synthetic sufficiency test**

The test must import a function that does not exist yet and must exercise the real integrated Runtime. Use a synthetic investigation with every `DEFAULT_CLAIM_CATALOG` claim resolved and with a verified account-owned email route.

Core test shape:

```python
from pathlib import Path
import tempfile
import unittest

from unified_runtime import UnifiedRuntime
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG
from scripts.verify_v64_c279_single_session import verify_single_session


def build_saturated_fixture(runtime: UnifiedRuntime) -> tuple[str, dict]:
    started = runtime.start_investigation({
        "account": {"account_id": "C-SINGLE-SESSION", "country": "Synthetic", "name": "Single Session Buyer"},
        "mode": "EXHAUSTIVE",
        "history": {"events": []},
        "priority_grade": "A",
    })
    investigation_id = started["investigation_id"]
    observations = []
    for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG):
        value = {"fixture": claim_key}
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
        observations.append({
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
        })
    runtime.compile_and_append_research_bundle({
        "investigation_id": investigation_id,
        "bundle": {"bundle_id": "BUNDLE-SINGLE-SESSION", "observations": observations},
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
        with tempfile.TemporaryDirectory() as temp:
            source_sessions = Path(temp) / "source" / "sessions"
            runtime = UnifiedRuntime(source_sessions)
            investigation_id, bridge = build_saturated_fixture(runtime)
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

Expected: FAIL because `scripts.verify_v64_c279_single_session` does not exist or `verify_single_session` is missing. The failure must be feature-missing, not a fixture syntax failure.

- [ ] **Step 4: Commit RED evidence**

Commit only the failing test. Allow the permanent release CI to run on that exact RED SHA and record the failed job/run ids.

- [ ] **Step 5: Implement the minimal isolated verifier**

Create `scripts/verify_v64_c279_single_session.py` with a pure callable and CLI. The callable must:

```python
def verify_single_session(*, bridge: dict, source_jsonl: Path) -> dict[str, object]:
    investigation_id = str(bridge["investigation_id"])
    expected = dict(bridge["durable_state"])
    source_before = source_jsonl.read_bytes()
    with tempfile.TemporaryDirectory(prefix="cbi-v64-c279-single-") as temp:
        sessions = Path(temp) / "sessions"
        sessions.mkdir(parents=True)
        isolated_jsonl = sessions / f"{investigation_id}.jsonl"
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

`SAFE_FIRST_TOUCH_BODY` must be 80-110 words, contain no private company/contact data, and be identical for synthetic and authoritative regression use.

- [ ] **Step 6: Run focused test and witness GREEN**

Run the same focused unittest. Expected: PASS with one JSONL copied into a fresh root, source unchanged, `sends_message == false`.

- [ ] **Step 7: Run neighboring runtime regressions**

Run:

```bash
python -m unittest tests.test_v61_resume_read_only tests.test_v61_outreach_hardening tests.test_v6_architecture -v
```

Expected: all PASS.

- [ ] **Step 8: Commit Task 1 GREEN**

Commit test + verifier with message `test(v64): prove C279 single-session isolated runtime sufficiency`.

---

### Task 2: Authoritative-input wrapper without private repository data

**Files:**
- Modify: `scripts/verify_v64_c279_single_session.py`
- Create: `tests/test_v64_c279_single_session_authoritative.py`

**Interfaces:**
- Consumes env paths `CBI_V64_C279_BRIDGE_EVIDENCE` and `CBI_V64_C279_SOURCE_SESSION_JSONL`.
- Produces sanitized JSON receipt to an explicit output path; receipt never contains investigation id, route value, or tail hash.

- [ ] **Step 1: Write failing CLI-contract tests**

Test missing env, malformed bridge, wrong source filename, tail mismatch, and sanitized receipt keys. The private authoritative test itself must `skipTest` unless both environment paths are supplied.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest tests.test_v64_c279_single_session_authoritative -v
```

Expected: FAIL on missing CLI/env behavior before implementation; the private live case may remain skipped.

- [ ] **Step 3: Implement CLI/env adapter**

The CLI must read the bridge and source path, assert `source_jsonl.name == f"{bridge['investigation_id']}.jsonl"`, call `verify_single_session`, and write only:

```json
{
  "schema": "cbi.v64-c279-single-session-proof.v1",
  "status": "PASS",
  "tail_match": true,
  "outreach_readiness": "COMPANY_ROUTE_READY",
  "closure_closed": true,
  "prepared": true,
  "sends_message": false,
  "source_unchanged": true
}
```

No hash/id/route data is written.

- [ ] **Step 4: Verify GREEN and privacy scan**

Run the focused test and `python tests/privacy_scan.py`.

- [ ] **Step 5: Commit Task 2**

Commit with message `feat(v64): add sanitized C279 single-session verifier CLI`.

---

### Task 3: Exact-SHA candidate proof verification

**Files:**
- No new production files.

- [ ] **Step 1: Wait for the branch's permanent Release CI on the Task 2 exact SHA**

Required contexts:

- `regression (ubuntu-latest, py3.10)`
- `regression (ubuntu-latest, py3.11)`
- `regression (windows-latest, py3.10)`
- `regression (windows-latest, py3.11)`

- [ ] **Step 2: Inspect every job**

All unittest regression, load acceptance, MCP tests, privacy scan and Linux Docker smoke must be green.

- [ ] **Step 3: Verify branch topology**

Compare exact integrated base `17f4fe160...` to candidate-proof head. `behind_by` must be zero; changed files must be limited to verifier/tests and any sanitized receipt documentation required by this plan.

- [ ] **Step 4: Record sanitized checkpoint**

Create `docs/superpowers/checkpoints/2026-09-05-v64-c279-single-session-verifier-green.md` containing exact SHA, RED run evidence, GREEN run evidence, and the statement that no production state was accessed or mutated.

---

### Task 4: Hold authoritative C279 execution until ciphertext capture exists

**Files:**
- None.

- [ ] **Step 1: Do not fabricate the current-cloud input**

The authoritative verifier must not run against migration generation 0, acceptance namespace data, semantic MCP projections, or a reconstructed JSONL.

- [ ] **Step 2: Gate on exact captured JSONL**

Only after Plan B has safely captured and decrypted the production single-session JSONL may this command run with private file paths:

```bash
CBI_V64_C279_BRIDGE_EVIDENCE=/private/bridge.json \
CBI_V64_C279_SOURCE_SESSION_JSONL=/private/INV-...jsonl \
python scripts/verify_v64_c279_single_session.py --output /private/sanitized-receipt.json
```

- [ ] **Step 3: Verify source immutability and `sends_message=false`**

No source hash/id is printed or persisted in public CI. Only sanitized proof is eligible for release checkpointing.
