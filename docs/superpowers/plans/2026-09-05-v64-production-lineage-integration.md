# CBI v6.4 Production Lineage Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a non-production integration candidate that is a descendant of both `cbi-v64-release-candidate-58e14973@4733a9b3e7286b58828750542c7ad54057cfb8ad` and `cbi-v6-cloud-runtime-20260901@a311a2a57ee43a1f1a3b2819bf28946566b05692`, preserving v6.4 candidate semantics plus still-relevant production CI/Windows portability behavior.

**Architecture:** Build the integration branch from the exact release candidate, prove the unresolved production semantics with a RED structural contract test, then create a two-parent merge commit whose tree uses the candidate as semantic authority while restoring the exact production `.github/workflows/cbi-v6-ci.yml` blob and semantically reconciling the Render/R2 blocked-external test. No runtime feature code changes are permitted.

**Tech Stack:** GitHub Git Data/Contents APIs, GitHub Actions, Python `unittest`, YAML workflow contracts.

**Spec:** `docs/superpowers/checkpoints/2026-09-05-v64-promotion-topology.md`

## Global Constraints

- Production branch `cbi-v6-cloud-runtime-20260901` must remain unchanged.
- Release candidate branch `cbi-v64-release-candidate-58e14973` must remain unchanged.
- The integrated branch must be a descendant of both exact refs above.
- Candidate tree is the v6.4 semantic authority.
- Preserve production `.github/workflows/cbi-v6-ci.yml` unchanged.
- Preserve candidate Windows tool-surface equality assertions and full inherited process environment.
- Reconcile `tests/test_v63_render_r2_workflow_contract.py` by keeping candidate explicit external-coordinate hygiene while adding production `CBI_V63_R2_REGION` cleanup and `PYTHONHASHSEED=0` determinism.
- Prefer the candidate `tests/test_v63_adapter_patch_compiler.py` unless a production-only assertion is found; current comparison found none.
- Add no runtime feature behavior.
- Integrated branch name must match `cbi-v*-release-candidate-*` so permanent release CI runs automatically.
- Require all four exact-SHA jobs green: Ubuntu/Windows × Python 3.10/3.11.
- After green, re-prove mergeability against unchanged production using a draft rehearsal PR; close rehearsal without merge.
- Keep PR #19 draft; do not deploy Render, mutate R2, CRM, or live runtime.

---

### Task 1: RED integration contract

**Files:**
- Create: `tests/test_v64_promotion_integration_contract.py`

**Interfaces:**
- Consumes: repository files only.
- Produces: structural proof that production CI portability and reconciled Render/R2 environment hygiene are present.

- [ ] **Step 1: Create isolated integration branch from exact RC SHA**

Branch: `cbi-v64-release-candidate-integrated-4733a9b3-a311a2a5` from `4733a9b3e7286b58828750542c7ad54057cfb8ad`.

- [ ] **Step 2: Write failing test**

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class V64PromotionIntegrationContractTests(unittest.TestCase):
    def test_production_ci_portability_is_preserved(self):
        text = (ROOT / ".github/workflows/cbi-v6-ci.yml").read_text(encoding="utf-8")
        self.assertIn("PyYAML==6.0.2 tzdata==2026.3", text)

    def test_render_r2_blocked_external_env_is_semantically_reconciled(self):
        text = (ROOT / "tests/test_v63_render_r2_workflow_contract.py").read_text(encoding="utf-8")
        self.assertIn('"CBI_V63_R2_REGION",', text)
        self.assertIn('environment["PYTHONHASHSEED"] = "0"', text)

    def test_candidate_windows_semantics_remain_authoritative(self):
        text = (ROOT / "tests/test_v6_windows_portability.py").read_text(encoding="utf-8")
        self.assertIn("environment = dict(os.environ)", text)
        self.assertIn("_declared_production_tool_names()", text)
        self.assertIn("_declared_core_tool_names()", text)
```

- [ ] **Step 3: Push test-only commit and verify RED on GitHub Actions**

Expected: release-candidate CI starts automatically and fails specifically because the candidate has not yet absorbed production `tzdata`, `CBI_V63_R2_REGION`, and `PYTHONHASHSEED=0` semantics.

### Task 2: GREEN semantic merge tree

**Files:**
- Preserve exact production blob: `.github/workflows/cbi-v6-ci.yml`
- Modify: `tests/test_v63_render_r2_workflow_contract.py`
- Preserve candidate versions: `tests/test_v6_windows_portability.py`, `tests/test_v63_adapter_patch_compiler.py`
- Keep: `tests/test_v64_promotion_integration_contract.py`

**Interfaces:**
- Consumes: RED branch tree, production exact blobs, both exact parent SHAs.
- Produces: one two-parent merge commit.

- [ ] **Step 1: Build reconciled Render/R2 test**

Use candidate file as base. Add `CBI_V63_R2_REGION` to `EXTERNAL_CONFIGURATION_KEYS`; after setting PATH, add `environment["PYTHONHASHSEED"] = "0"`. Change nothing else.

- [ ] **Step 2: Build Git tree**

Use RED commit tree as base. Replace `.github/workflows/cbi-v6-ci.yml` with the exact production blob. Replace only the reconciled Render/R2 test. Do not replace candidate Windows or adapter tests.

- [ ] **Step 3: Create two-parent merge commit**

First parent: RED integration commit (descendant of exact RC). Second parent: exact production SHA `a311a2a57ee43a1f1a3b2819bf28946566b05692`.

Commit message: `merge(v64): reconcile production lineage into release candidate`.

- [ ] **Step 4: Advance only integration branch**

Fast-forward the isolated integration branch to the merge commit. Do not update RC or production refs.

### Task 3: Exact-SHA verification and mergeability rehearsal

**Files:** none unless debugging is required.

**Interfaces:**
- Consumes: exact integrated merge SHA.
- Produces: four-matrix green evidence and GitHub mergeability evidence.

- [ ] **Step 1: Verify commit topology**

Assert two parents include the RED RC-descendant commit and exact production SHA; compare integrated head against production must report `behind_by=0`.

- [ ] **Step 2: Verify all four release CI jobs green for exact integrated SHA**

Required contexts:
- `regression (ubuntu-latest, py3.10)`
- `regression (ubuntu-latest, py3.11)`
- `regression (windows-latest, py3.10)`
- `regression (windows-latest, py3.11)`

- [ ] **Step 3: Run draft mergeability rehearsal against unchanged production**

Open a temporary draft PR from integrated branch to `cbi-v6-cloud-runtime-20260901`, read GitHub mergeability, then close it without merge.

- [ ] **Step 4: Update sanitized checkpoint / PR #19 body**

Record exact integrated SHA, four-matrix run ID, mergeability result, and confirm C279 + production-ruleset remain the only external blockers. Keep PR #19 draft and do not promote.
