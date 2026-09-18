# ASTRA Phase 2A Default-Branch Gate Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate Phase 2A `issues`/`issue_comment` GitHub Actions gates from repository default branch `main` without moving CBI business/runtime code onto `main` and without letting event payloads select executable workflow code.

**Architecture:** Phase 2A implementation remains on the CBI development lineage. After a reviewed CI-green Phase 2A release commit exists, generate two tiny workflow shims containing that exact 40-hex commit SHA, create a separate branch from `main`, add only those shims, and open a human-reviewed activation PR against `main`.

**Tech Stack:** GitHub Actions, existing Phase 2A Python gate scripts, exact Git commit pinning.

**Spec:** `docs/superpowers/specs/2026-09-09-astra-phase2-default-branch-gate-amendment.md`

## Global Constraints

- Repository default branch is `main`.
- `issues`/`issue_comment` workflows become operational only from `main`.
- Gate workflow code must checkout one exact reviewed Phase 2A 40-hex commit SHA; no branch/tag/event-supplied ref is allowed.
- `main` activation changes only `.github/workflows/astra-task-sign.yml` and `.github/workflows/astra-receipt-verify.yml` plus no CBI business/runtime source.
- Activation is a separate PR and is never auto-merged.
- Windows worker never gets permission to create/merge this activation PR.

---

### Task A1: Add deterministic gate-workflow renderer

**Files:**
- Create: `astra_worker/gate_activation.py`
- Create: `scripts/render_astra_gate_workflows.py`
- Create: `tests/test_astra_worker_gate_activation.py`

**Interfaces:**
- Produces: `render_task_gate_workflow(control_plane_sha: str) -> str`, `render_receipt_gate_workflow(control_plane_sha: str) -> str`.

- [ ] **Step 1: Write RED tests**

```python
class GateActivationTests(unittest.TestCase):
    def test_only_exact_40_hex_sha_is_accepted(self):
        with self.assertRaises(ActivationError):
            render_task_gate_workflow("astra-phase2-current")
        text = render_task_gate_workflow("a" * 40)
        self.assertIn("ref: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", text)
        self.assertNotIn("github.event", text.split("ref:", 1)[1].splitlines()[0])

    def test_task_and_receipt_triggers_are_default_branch_event_types(self):
        self.assertIn("issues:", render_task_gate_workflow("b" * 40))
        self.assertIn("issue_comment:", render_receipt_gate_workflow("b" * 40))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_astra_worker_gate_activation -v`

Expected: FAIL because renderer does not exist.

- [ ] **Step 3: Implement literal-SHA workflow rendering**

Task workflow must use:

```yaml
on:
  issues:
    types: [opened, edited, labeled]
permissions:
  contents: read
  issues: write
```

Receipt workflow must use:

```yaml
on:
  issue_comment:
    types: [created]
permissions:
  contents: read
  issues: write
```

Both must checkout `Scorp96/customs-buyer-intelligence-ledger` with `ref: <literal control_plane_sha>` and then run the corresponding Phase 2A Python gate script. Refuse any SHA not matching `^[0-9a-fA-F]{40}$`.

- [ ] **Step 4: Run GREEN and commit on Phase 2A implementation branch**

Run: `python -m unittest tests.test_astra_worker_gate_activation -v`

```bash
git add astra_worker/gate_activation.py scripts/render_astra_gate_workflows.py tests/test_astra_worker_gate_activation.py
git commit -m "feat(astra-worker): render default-branch gate shims"
```

---

### Task A2: Generate activation shims only after final Phase 2A release SHA exists

**Files:**
- Generated output only for the later `main` activation branch:
  - `.github/workflows/astra-task-sign.yml`
  - `.github/workflows/astra-receipt-verify.yml`

- [ ] **Step 1: Capture exact CI-green release SHA**

Run after the complete Phase 2A implementation has passed final exact-head CI:

```bash
CONTROL_PLANE_SHA=$(git rev-parse HEAD)
python scripts/render_astra_gate_workflows.py --control-plane-sha "$CONTROL_PLANE_SHA" --output-dir /tmp/astra-gates
```

Expected: both generated workflows contain the same literal `$CONTROL_PLANE_SHA` and no mutable checkout ref.

- [ ] **Step 2: Create a branch from `main`, not from the CBI/Phase 2A branch**

Using GitHub branch operations, create an activation branch such as `astra-phase2-gates-main-<date>` from current `main` HEAD.

- [ ] **Step 3: Add only the two generated workflow shims**

Before writing, compare the activation branch to `main`. After writing, the changed-file set must be exactly:

```text
.github/workflows/astra-task-sign.yml
.github/workflows/astra-receipt-verify.yml
```

Any additional source/runtime file is a stop condition.

- [ ] **Step 4: Open a Draft PR against `main`**

PR body must record:

```text
Phase 2A control-plane SHA: <exact 40-hex SHA>
Activation scope: default-branch event shims only
Auto-merge: disabled
Worker source-write authority: none
```

Keep the PR Draft until human review.

- [ ] **Step 5: Verify activation semantics without merging**

Static checks must prove:

- issue/task event cannot alter checkout SHA;
- workflow permissions are only Contents read + Issues write;
- no `pull-requests: write`, `actions: write`, `contents: write`, or administration authority;
- both scripts executed come from the exact reviewed Phase 2A SHA.

- [ ] **Step 6: Human merge gate**

Do not merge automatically. Operational task signing/receipt verification begins only after explicit human approval of this separate `main` PR and repository Actions secrets have been provisioned.
