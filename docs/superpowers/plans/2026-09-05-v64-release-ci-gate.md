# CBI v6.4 Permanent Release CI Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permanent GitHub Actions release-candidate gate that runs the exact required four-platform regression matrix on each v6.x release-candidate head SHA without retargeting to `main` or mutating production.

**Architecture:** Add one release-specific workflow, `.github/workflows/cbi-release-ci.yml`, whose automatic push trigger is restricted to `cbi-v*-release-candidate-*`. Preserve the existing regression job name/matrix/commands so the release evidence maps directly to the required status-check names. Protect the contract with a focused structural test; the structural test supplements but never replaces the actual four-platform Actions run.

**Tech Stack:** GitHub Actions YAML, Python 3.10/3.11, `unittest`, existing CBI regression/MCP/load/privacy/self-test commands.

**Spec:** `docs/superpowers/specs/2026-09-05-v64-release-ci-gate-design.md`

## Global Constraints

- Do not modify `main`.
- Do not modify `cbi-v6-cloud-runtime-20260901`.
- Do not merge PR #19 or promote production in this plan.
- Do not mutate Render, R2, or live Runtime state.
- Exact candidate head SHA is the only valid four-platform acceptance subject.
- Any candidate-head change invalidates prior four-platform evidence.
- Release CI does not waive C279 current-cloud or production-ruleset gates.
- Required matrix job names remain `regression (ubuntu-latest, py3.10)`, `regression (ubuntu-latest, py3.11)`, `regression (windows-latest, py3.10)`, and `regression (windows-latest, py3.11)`.

---

### Task 1: Release CI Contract Test

**Files:**
- Create: `tests/test_release_ci_contract.py`

**Interfaces:**
- Consumes: repository file `.github/workflows/cbi-release-ci.yml` as plain UTF-8 text.
- Produces: fail-closed structural assertions for release trigger, matrix, job naming, fail-fast, unittest discovery, and forbidden push branches.

- [ ] **Step 1: Write the failing contract test**

Create `tests/test_release_ci_contract.py` with tests that read `.github/workflows/cbi-release-ci.yml` and assert the following literal contract fragments are present: `cbi-v*-release-candidate-*`, `workflow_dispatch:`, `ubuntu-latest`, `windows-latest`, `"3.10"`, `"3.11"`, `fail-fast: false`, `regression (${{ matrix.os }}, py${{ matrix.python-version }})`, and `python -m unittest discover -s tests -p "test_*.py" -v`. Assert the push branch block does not contain `main` or `cbi-v6-cloud-runtime-20260901`.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest -v tests.test_release_ci_contract`

Expected: FAIL because `.github/workflows/cbi-release-ci.yml` does not exist.

- [ ] **Step 3: Commit the RED test only**

Commit message: `test(v64): define permanent release CI contract`

---

### Task 2: Permanent Release Workflow

**Files:**
- Create: `.github/workflows/cbi-release-ci.yml`
- Reference: `.github/workflows/cbi-v6-ci.yml`

**Interfaces:**
- Consumes: release-candidate branch push and the current repository test/runtime layout.
- Produces: GitHub Actions workflow with the same regression matrix and verification commands as the current independent CI workflow, but a release-candidate-specific trigger.

- [ ] **Step 1: Create the minimal workflow implementation**

Copy the current `.github/workflows/cbi-v6-ci.yml` job body and pinned Action SHAs. Change only the workflow identity/trigger/concurrency as required by the approved spec: name `CBI release candidate CI`; push branches only `cbi-v*-release-candidate-*`; retain `workflow_dispatch`; use `contents: read`; concurrency keyed by `${{ github.ref }}`; no `pull_request` trigger is required.

- [ ] **Step 2: Run the focused contract test and verify GREEN**

Run: `python -m unittest -v tests.test_release_ci_contract`

Expected: PASS.

- [ ] **Step 3: Run regression suite in the isolated non-authoritative verification workspace**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`

Expected: all tests PASS with only the already-known intentional skips.

- [ ] **Step 4: Check workflow parity**

Compare the release workflow regression job body to `.github/workflows/cbi-v6-ci.yml`; aside from workflow name, triggers, and concurrency key, the matrix, pinned Action SHAs, test commands, load acceptance, MCP checks, Docker smoke condition/body, privacy scan, and self-tests must remain semantically identical.

- [ ] **Step 5: Commit GREEN implementation**

Commit message: `ci(v64): add permanent release candidate gate`

---

### Task 3: Apply to Release Candidate and Verify Exact SHA

**Files:**
- Candidate branch: `cbi-v64-release-candidate-58e14973`
- Existing PR: #19

**Interfaces:**
- Consumes: reviewed design/plan, RED test commit, GREEN workflow commit.
- Produces: candidate head SHA containing the permanent gate and exact-SHA GitHub Actions evidence.

- [ ] **Step 1: Fast-forward the candidate only with reviewed release-gate commits**

Before update, re-fetch candidate/source/production refs and PR #19. Abort if candidate is no longer the expected lineage or production/source changed unexpectedly.

- [ ] **Step 2: Verify the candidate push triggered the release workflow**

Read Actions runs for the new candidate head SHA / release workflow. The run SHA must equal the candidate head SHA.

- [ ] **Step 3: Verify all four matrix jobs**

Require successful conclusions for exactly the four required regression matrix names. Missing, cancelled, skipped, timed-out, or failed jobs keep the lifecycle gate RED.

- [ ] **Step 4: Verify repository and production invariants**

Re-fetch source, production, candidate, PR #19, and repository rulesets. Confirm production SHA unchanged, PR #19 remains Draft, no merge occurred, and no new production mutation was introduced.

- [ ] **Step 5: Record lifecycle result**

If all four jobs are green on the exact candidate SHA, advance only `RELEASE_CI_GATE` to GREEN. Keep overall `Production Ready = NO` until C279 current-cloud and `protect-cbi-production` are independently GREEN.
