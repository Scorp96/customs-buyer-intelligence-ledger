# ASTRA Supervisor Multi-Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep GPT-5.6 Sol / ASTRA as an independent engineering supervisor while removing Codex execution availability or allowance as a single point of failure for repository-authoritative CBI development.

**Architecture:** Introduce a small, CBI-independent `astra_supervisor` package. ASTRA selects an executor by authoritative-state location: GitHub first for repository-authoritative changes, Codex or a fail-closed Local Executor for local-workspace changes, and no executor for review-only tasks. The Local Executor accepts a narrow manifest, defaults to dry-run, validates every operation before mutation, refuses protected branches, and exposes only bounded file operations plus allowlisted verification commands. `codex-with-chatgpt` remains an optional external read-only workspace bridge and is not vendored.

**Tech Stack:** Python 3.10+, unittest, GitHub Actions, existing repository Git workflow.

**Spec:** `docs/superpowers/specs/2026-09-09-astra-supervisor-multi-executor-design.md`

## Global Constraints

- Do not modify CBI evidence, WAL, R2, canonical identity, Closure, CRM or outreach semantics.
- Do not write directly to `main`, `master`, or `production` from Local Executor.
- Local Executor apply mode requires the exact expected branch and a clean Git working tree.
- Dry-run is the Local Executor default.
- Do not expose arbitrary shell, PowerShell, CMD, package install, network commands, `git push`, or `python -c` through the Local Executor.
- All manifest paths and command path targets must remain under the declared repository root; nested `.git` metadata is inaccessible.
- User-supplied executable paths may not bypass the command allowlist by presenting an allowlisted basename; path-form executables are rejected except for the exact current Python interpreter path used by the supported Python invocation contract.
- Inherited `GIT_*` control variables may not redirect branch or clean-tree gates to another repository.
- Known Git configuration-driven external execution surfaces used by the allowed inspection path (`core.fsmonitor`, external diff, textconv) must be neutralized.
- Repository-authoritative work should prefer GitHub execution rather than pretending Codex is mandatory.
- `codex-with-chatgpt` is read-only workspace visibility only; it is not an execution authority, a quota bypass, or proof that ChatGPT/Codex quota pools are universally independent.
- Local Executor v1 is a command-boundary hardening layer, not an OS sandbox; allowlisted repository test/module execution still trusts repository code.
- Phase 1 assumes the local OS account, executable search path and installed Python/Git binaries are trusted. A compromised local `PATH` or replaced binary is outside the Phase 1 threat model and must be addressed before any unattended control plane.
- Any future unattended local control plane must pin allowed repository roots in trusted local configuration; remote manifests may not choose arbitrary roots.
- No automatic merge into the active CBI development branch or production branch.

---

### Task 1: Executor selection contract

**Files:**
- Create: `astra_supervisor/contracts.py`
- Create: `astra_supervisor/policy.py`
- Create: `astra_supervisor/__init__.py`
- Test: `tests/test_astra_supervisor.py`

**Interfaces:**
- Consumes: `TaskKind`, `ExecutorAvailability`.
- Produces: `select_executor(task_kind, availability) -> ExecutorName`.

- [x] Write failing executor-policy tests covering repository-authoritative preference `GitHub -> Codex -> Local`, local-workspace preference `Codex -> Local`, review-only `NONE`, and fail-closed behavior.
- [x] Observe initial RED because `astra_supervisor` did not exist.
- [x] Implement minimal enums/dataclass/policy without CBI runtime dependency.
- [x] Verify executor-selection tests GREEN.

### Task 2: Manifest validation

**Files:**
- Create: `astra_supervisor/manifest.py`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- Produces: `ExecutionManifest.from_dict(...)`, `Operation.from_dict(...)`, `ManifestValidationError`.

- [x] Test rejection of empty task IDs, absolute paths, traversal, `.git` writes including nested `.git`, unknown operations, and string-form commands.
- [x] Implement narrow manifest parsing with exactly `write_text`, `delete_file`, and `run`.
- [x] Verify targeted validation tests GREEN.

### Task 3: Fail-closed Local Executor dry-run and branch gates

**Files:**
- Create: `astra_supervisor/local_executor.py`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- Consumes: validated `ExecutionManifest`.
- Produces: `LocalExecutor.execute(manifest, apply=False) -> ExecutionResult`.

- [x] Test dry-run, protected branch, expected-branch mismatch, and dirty-tree apply rejection.
- [x] Implement Git worktree, exact branch, protected-branch and clean-tree preflight.
- [x] Verify branch/tree gates GREEN.

### Task 4: Safe file operations and command policy

**Files:**
- Modify: `astra_supervisor/local_executor.py`
- Modify: `astra_supervisor/manifest.py`
- Modify: `tests/test_astra_supervisor.py`
- Create: `tests/test_astra_supervisor_executable_boundary.py`

**Interfaces:**
- File mutations: repository-confined UTF-8 atomic writes and explicit deletes.
- Commands: `shell=False`, timeout, captured output, allowlisted semantics only.

- [x] Happy path: write a module and execute `python -m unittest`.
- [x] First security RED exposed six containment gaps: nested `.git`, Python-lookalike executable, out-of-root unittest target, out-of-root compileall target, `git diff --output`, and `git diff --ext-diff`.
- [x] Harden Python/Git argument validation, nested `.git` protection and repository path containment.
- [x] Independent follow-up review found a seventh command-origin gap: arbitrary paths whose basename was `python` or `git` could pass the executable-name allowlist.
- [x] Add the executable-origin regression first and observe RED with two failing subcases proving `.../tools/python` and `.../tools/git` path spoofing were accepted before the fix.
- [x] Reject user-selected executable paths at manifest validation, except the exact current Python interpreter path needed by the supported Python invocation contract.
- [x] Add the new executable-origin regression to the focused Windows/Linux CI matrix.
- [x] Independent branch-gate review found inherited `GIT_DIR` / `GIT_WORK_TREE` could redirect internal Git inspection to a decoy repository while file mutation still targeted the declared repository.
- [x] Add the branch-gate redirection regression first and observe RED proving `LocalExecutionError` was not raised before the fix.
- [x] Sanitize inherited `GIT_*` variables for internal and manifest Git execution, preserving only bounded noninteractive controls.
- [x] Independent Git-config review found three external-execution surfaces reachable through otherwise allowlisted Git operations: `core.fsmonitor`, `diff.external`, and `diff.<driver>.textconv`.
- [x] Add all three regressions first and observe RED: 32 focused tests with exactly three failures, each proving the configured helper actually executed.
- [x] Force `core.fsmonitor=false` for branch/clean-tree inspection and force `--no-ext-diff --no-textconv` on allowed `git diff`, `git log`, and `git show` execution.
- [x] Verify the focused ASTRA suite is now 32 tests and GREEN on Ubuntu/Windows × Python 3.10/3.11.

### Task 5: CLI and ASTRA skill contract

**Files:**
- Create: `astra_supervisor/cli.py`
- Create: `scripts/astra_local_executor.py`
- Create: `skills/sol-advisor-astra/SKILL.md`
- Create: `skills/sol-advisor-astra/references/execution-manifest.example.json`
- Modify: `tests/test_astra_supervisor.py`

**Interfaces:**
- CLI: `python scripts/astra_local_executor.py --manifest <file> [--apply] [--result <file>]`.
- Skill: supervisor state, anti-path-dependence, executor selection, CBI boundaries and verification requirements.

- [x] Add CLI dry-run structured-result contract test.
- [x] Implement CLI, structured JSON result, ASTRA skill and safe example manifest.
- [x] Verify focused suite GREEN.

### Task 6: CI and integration verification

**Files:**
- Create/Modify: `.github/workflows/astra-supervisor-ci.yml`

**Interfaces:**
- Focused gate: compile + ASTRA tests on Ubuntu/Windows × Python 3.10/3.11.
- Integration gate: full CBI unittest discovery on Ubuntu/Python 3.11.

- [x] Add focused matrix workflow.
- [x] Add full CBI regression gate without modifying CBI runtime files.
- [x] Verify the earlier implementation head: focused 27/27 tests pass on all four matrix jobs; full CBI regression runs 966 tests and returns `OK (skipped=4)`.
- [x] Verify executable-origin hardening head `ef0c5e120e0b323db6bc23a548905a4599e3721c`: focused 28/28 tests pass on all four matrix jobs; full CBI regression runs 967 tests and returns `OK (skipped=4)`.
- [x] Verify Git-environment hardening head `30dac327a56ce17052e9a72eba2105262572bd30`: focused 29/29 tests pass on all four matrix jobs; full CBI regression runs 968 tests and returns `OK (skipped=4)`.
- [x] Verify Git-config-helper hardening head `a030bb8a01115b905353dec7ae5dfbac48fea004`: GitHub Actions run #55 is GREEN on all four focused matrix jobs; focused suite runs 32 tests and returns `OK`; Ubuntu/Python 3.11 full CBI regression runs 971 tests in 59.362s and returns `OK (skipped=4)`.
- [x] Compare `a030bb8a01115b905353dec7ae5dfbac48fea004` to base `f59731cb412e194052d16e81c8137c507964350d`: 14 changed files, all limited to ASTRA supervisor/tests/skill/docs/script/workflow; no CBI runtime/evidence/WAL/R2 file is changed.
- [x] Keep draft PR #23 targeting `cbi-v6-3-demand-expansion`; do not auto-merge.
- [ ] After authoritative docs are updated, run one final exact-head CI and repeat the base-diff/PR-state gate before declaring Phase 1 merge-ready.

## Verification record

- Initial TDD RED: `07b3d22becbc69916fec1d82fc398c117d080154` — missing `astra_supervisor` import as expected.
- First security RED: `4ab75ff45db02da72117be29e384957398c62efe` — six containment failures intentionally exposed before fixing them.
- First security fixes: `b8580ab15850d1e4c233045a6b08bf5df7232678` and `b3d5220ac663e5cbb649d6ce08b884f8a2270fab`.
- Zero-diff history cleanup: the pre-cleanup feature head was preserved as `astra-supervisor-local-executor-20260909-precleanup-backup`; the feature branch was safely moved back to the last effective tree before continuing.
- Executable-origin RED path: dedicated regression introduced at `c7295e1b842d29d5b0e4f754a02fb06f30bf8cbd`; focused CI was then wired to run it at `44f1089728e3c7390b7aef776da28604bb1f977d` and produced two expected failures for user-selected Python/Git executable paths.
- Executable-origin production fix: `1de1227151543311fe7373ef40f1b7cb719701a3` — rejection moved into manifest validation. The first post-fix run showed the unsafe paths were rejected but the test over-specified the exception layer; `ef0c5e120e0b323db6bc23a548905a4599e3721c` corrected that test contract without weakening production behavior.
- Git environment RED: `a43a502b22ba799741bf68d802bca7261dc53d3b` — `GIT_DIR` / `GIT_WORK_TREE` successfully redirected the branch/clean-tree safety gate to a decoy repository before the fix.
- Git environment fix: `30dac327a56ce17052e9a72eba2105262572bd30` — inherited `GIT_*` control variables are stripped and bounded noninteractive controls are reintroduced. Post-fix focused 29/29 and full 968-test regression were GREEN.
- Git config helper RED: `e74dcd7856cc1e41b4219c10ff0a118905eeb98e` — focused CI ran 32 tests and produced exactly three failures proving execution through configured `core.fsmonitor`, external diff, and textconv helpers.
- Git config helper production fix: `a030bb8a01115b905353dec7ae5dfbac48fea004` — internal Git inspection forces `core.fsmonitor=false`; allowed diff/log/show execution forces `--no-ext-diff --no-textconv`.
- Security-hardened verification at `a030bb8a01115b905353dec7ae5dfbac48fea004`: GitHub Actions run #55 — all four focused matrix jobs GREEN, 32 tests `OK`; Ubuntu/Python 3.11 full CBI regression GREEN with 971 tests in 59.362s and `skipped=4`.
- Fresh base check at the same verification point: `cbi-v6-3-demand-expansion` remained pinned at `f59731cb412e194052d16e81c8137c507964350d`; the ASTRA diff contained 14 changed files and no CBI runtime/evidence/WAL/R2 file.

## Remaining boundary

This phase removes Codex as the single point of failure for **repository-authoritative GitHub work** and supplies a fail-closed Local Executor implementation. It does **not** create a writable ChatGPT-to-PC bridge. `codex-with-chatgpt` remains read-only, so fully autonomous mutation of uncommitted local-only state still requires an explicitly invoked local process.

The Local Executor remains transition-grade rather than an OS sandbox. Repository Python tests/modules are trusted code, and Phase 1 assumes a trusted local OS account, executable search path, Python binary and Git binary. These assumptions are acceptable for explicit local invocation but are not acceptable as implicit trust in a remotely reachable service.

The next architectural phase, if approved, is an unattended local control plane. That changes the threat model and must not be obtained by simply exposing the Phase 1 CLI. Before such a phase can be implemented, its design must pin trusted repository roots outside remote manifests, establish independent authentication/authorization, establish a trusted executable environment, preserve exact branch/clean-tree gates and auditability, and continue to deny unrestricted shell/package/network/Git-push authority.
