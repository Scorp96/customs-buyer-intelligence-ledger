# ASTRA Supervisor Multi-Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested ASTRA supervisor contract plus a fail-closed Local Executor fallback so CBI engineering can continue when Codex allowance is unavailable.

**Architecture:** Keep CBI runtime untouched. Add an independent `astra_supervisor` Python package for executor selection and local-manifest execution, a `$sol-advisor-astra` skill for supervisor behavior, and a focused CI workflow. `codex-with-chatgpt` remains an optional external read-only bridge and is not vendored.

**Tech Stack:** Python 3.10+, stdlib `dataclasses`, `enum`, `json`, `pathlib`, `subprocess`, `unittest`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-astra-supervisor-multi-executor-design.md`

## Global Constraints

- Do not modify CBI evidence, WAL, R2, canonical identity, closure, CRM, or send-gating semantics.
- Do not write directly to `main`, `master`, or `production` through the Local Executor.
- Default Local Executor behavior is dry-run.
- Never invoke a shell for manifest commands.
- No session-token scraping, unofficial ChatGPT web API, or vendored third-party bridge source.
- GitHub is a first-class no-Codex executor for repository-authoritative work.

---

### Task 1: Executor-selection contract

**Files:**
- Create: `astra_supervisor/__init__.py`
- Create: `astra_supervisor/contracts.py`
- Create: `astra_supervisor/policy.py`
- Test: `tests/test_astra_supervisor.py`

**Interfaces:**
- Produces: `TaskKind`, `ExecutorName`, `ExecutorAvailability`, `NoExecutorAvailable`, `select_executor()`.

- [ ] **Step 1: Write failing selection tests**

```python
self.assertEqual(
    select_executor(TaskKind.REPOSITORY_EDIT, ExecutorAvailability(github=True)),
    ExecutorName.GITHUB,
)
self.assertEqual(
    select_executor(TaskKind.LOCAL_WORKSPACE, ExecutorAvailability(codex=False, local=True, github=True)),
    ExecutorName.LOCAL,
)
self.assertEqual(
    select_executor(TaskKind.REVIEW_ONLY, ExecutorAvailability()),
    ExecutorName.NONE,
)
```

- [ ] **Step 2: Run targeted test and confirm RED**

Run: `python -m unittest tests.test_astra_supervisor -v`
Expected: import failure because `astra_supervisor` does not yet exist.

- [ ] **Step 3: Implement minimal enums/dataclass/policy**

`REPOSITORY_EDIT` preference order is GitHub, Codex, Local. `LOCAL_WORKSPACE` preference order is Codex, Local. `REVIEW_ONLY` returns NONE. Raise `NoExecutorAvailable` when no eligible executor exists.

- [ ] **Step 4: Run targeted tests and confirm GREEN**

Run: `python -m unittest tests.test_astra_supervisor -v`
Expected: selection tests pass.

### Task 2: Manifest model and fail-closed validation

**Files:**
- Create: `astra_supervisor/manifest.py`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- Produces: `Operation`, `ExecutionManifest`, `ManifestValidationError`.

- [ ] **Step 1: Add failing tests** for path traversal, absolute path, `.git` mutation, empty task id, unsupported operation kind, and malformed argv.
- [ ] **Step 2: Run and confirm RED** because manifest classes do not exist.
- [ ] **Step 3: Implement parsing/validation** with `ExecutionManifest.from_dict()` and preflight validation of all operations.
- [ ] **Step 4: Run and confirm GREEN**.

### Task 3: Local Executor dry-run and branch gates

**Files:**
- Create: `astra_supervisor/local_executor.py`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- Produces: `LocalExecutor`, `ExecutionResult`, `ExecutionStepResult`, `LocalExecutionError`.

- [ ] **Step 1: Add failing tests** using a temporary Git repository. Assert dry-run does not create files, protected branch apply is rejected, expected-branch mismatch is rejected, and dirty-tree apply is rejected.
- [ ] **Step 2: Run and confirm RED**.
- [ ] **Step 3: Implement repository preflight** using argv-only Git subprocess calls.
- [ ] **Step 4: Run and confirm GREEN**.

### Task 4: Safe file operations and command policy

**Files:**
- Modify: `astra_supervisor/local_executor.py`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- `write_text` and `delete_file` operate only under the repository root.
- `run` permits only Python `-m unittest`, Python `-m compileall`, and read-only Git inspection subcommands in v1.

- [ ] **Step 1: Add failing tests** for allowed write+unittest execution and rejection of `python -c`, shell executables, `git push`, and escaped cwd.
- [ ] **Step 2: Run and confirm RED**.
- [ ] **Step 3: Implement command validation and sequential execution** with `shell=False`, timeout, captured output, and stop-on-failure.
- [ ] **Step 4: Run and confirm GREEN on Windows and Linux**.

### Task 5: CLI and supervisor skill

**Files:**
- Create: `astra_supervisor/cli.py`
- Create: `scripts/astra_local_executor.py`
- Create: `skills/sol-advisor-astra/SKILL.md`
- Create: `skills/sol-advisor-astra/references/execution-manifest.example.json`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- CLI: `python scripts/astra_local_executor.py --manifest PATH [--apply] [--result PATH]`
- Skill: instructs Sol/ASTRA to select GitHub/Codex/Local based on authoritative state and availability, independently review evidence, and preserve CBI runtime boundaries.

- [ ] **Step 1: Add failing CLI serialization test**.
- [ ] **Step 2: Run and confirm RED**.
- [ ] **Step 3: Implement CLI and skill assets**.
- [ ] **Step 4: Run targeted tests and confirm GREEN**.

### Task 6: Focused CI and integration verification

**Files:**
- Create: `.github/workflows/astra-supervisor-ci.yml`

**Interfaces:**
- Runs on the isolated ASTRA branch and pull requests touching ASTRA files.
- Matrix: Ubuntu + Windows, Python 3.10 + 3.11.

- [ ] **Step 1: Commit tests + workflow before production code and observe RED**.
- [ ] **Step 2: Implement Tasks 1-5**.
- [ ] **Step 3: Observe GREEN on all matrix jobs**.
- [ ] **Step 4: Review diff against the design spec and confirm no CBI runtime files changed**.
- [ ] **Step 5: Open a draft PR against `cbi-v6-3-demand-expansion`; do not merge automatically**.
