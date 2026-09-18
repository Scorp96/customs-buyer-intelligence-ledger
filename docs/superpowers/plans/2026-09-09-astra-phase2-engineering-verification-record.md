# ASTRA Phase 2A Engineering Verification Record

**Execution plan:** `docs/superpowers/plans/2026-09-09-astra-phase2-github-pull-worker.md`

**Design:** `docs/superpowers/specs/2026-09-09-astra-phase2-github-pull-worker-design.md`

**Phase 1 exact baseline:** `7fbf1c15477632f2f36259bd9d91b3074807b3da`

**Development branch:** `astra-phase2-pull-worker-design-20260909`

This record closes the implementation-side Phase 2A acceptance work without rewriting the original execution plan. The final post-commit exact-head CI, repeated baseline diff, and draft-PR state are intentionally recorded outside the repository head after this commit so that documenting those observations cannot invalidate the exact commit they verify.

## Verified implementation state before this closure commit

The last code/skill candidate before this record was `a939bcdf2abb594f7cd3767bc9a0fffac6b423ae`.

GitHub Actions run `#78` (`34324014408`) verified that exact commit on the complete Phase 2A matrix:

- Ubuntu / Python 3.10: success.
- Ubuntu / Python 3.11: success.
- Windows / Python 3.10: success.
- Windows / Python 3.11: success.
- Phase 2A worker suite on Ubuntu / Python 3.11: 125 tests, `OK (skipped=5)`.
- Phase 1 ASTRA regression on Ubuntu / Python 3.11: 35 tests, `OK`.
- Full repository regression on Ubuntu / Python 3.11: 1099 tests, `OK (skipped=9)`.

## Integrated end-to-end acceptance

Task 13 added a real local integration test that uses the production protocol/model/compiler/worker/evidence/executor path rather than a second implementation:

1. create a temporary developer checkout and exact base commit;
2. construct and HMAC-sign a real `astra.task.v1` envelope;
3. feed it through a fake transport that still performs real task-HMAC verification;
4. use a real `TaskLedger`, `GitWorkspaceManager`, `TaskCompiler`, Phase 1 `LocalExecutor`, and `Worker.run_once`;
5. execute an actual repository-contained unittest in an ephemeral worktree;
6. verify exact final file bytes, execution success, receipt HMAC, final-state hashes, patch/chunk hashes, and cleanup;
7. prove the original developer checkout is byte-for-byte unchanged and the ephemeral worktree/branch is removed.

The first integrated RED correctly quarantined the result. A diagnostic RED proved the cause was undeclared Python bytecode side effects (`__pycache__/*.pyc`) created by successful unittest execution. The production fix did **not** weaken final-evidence confinement or whitelist caches; the Phase 1 executor now forces `PYTHONDONTWRITEBYTECODE=1` in its sanitized Python environment. The integrated contract now requires cleanup-prestate to contain only the signed `feature.py` mutation.

Exact-head run `#75` (`34323504412`) verified that fix on all four OS/Python matrix jobs, including the integrated acceptance test and full repository regression.

## Windows service / installation acceptance

Task 12 is engineering-complete and install-contract verified. The reviewed boundary includes:

- WinSW x64 v2.12.0 pinned to `https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe`;
- pinned SHA-256 `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`;
- routine runtime identity `NT SERVICE\ASTRAWorker`, not Administrator or LocalSystem;
- state beneath installer-owned `%ProgramData%\ASTRAWorker`;
- DACL allow principals restricted to the exact service SID, `SYSTEM`, and local `Administrators`;
- machine-scope DPAPI secret bundle;
- task/receipt HMAC keys independent from each other;
- secret provisioning through `provision-secrets --stdin`, with no secret command-line flags;
- service start only after ACL/config/secret validation succeeds.

Exact full-tree Task 12 run `#67` (`34322499181`) was green on all four matrix jobs.

This is **not** evidence that a real user Windows host has already installed, provisioned, started, or production-activated the service.

## CI control-plane coverage

Task 13 expanded `.github/workflows/astra-worker-ci.yml` so Phase 2A CI is triggered by all relevant control-plane surfaces, including:

- `astra_worker/**`;
- `astra_supervisor/**`;
- worker/gate launchers and the Windows installer;
- `deploy/astra-worker/**`;
- worker and Phase 1 ASTRA tests;
- ASTRA workflows;
- `skills/sol-advisor-astra/**`;
- Phase 2A plans/specifications.

The pull-request CI target is restricted to the authoritative development branch `cbi-v6-3-demand-expansion`. Actions checkout/setup-python remain commit-pinned and job permissions remain `contents: read`.

Exact workflow candidate run `#77` (`34323790792`) was green on all four matrix jobs.

## ASTRA skill synchronization

`skills/sol-advisor-astra/SKILL.md` now documents the implemented Phase 2A authority split:

```text
Sol/ASTRA
  -> proposed task
  -> trusted GitHub signer
  -> outbound-only Windows worker
  -> Phase 1 LocalExecutor in an ephemeral worktree
  -> signed receipt
  -> trusted receipt gate
  -> ASTRA review
  -> GitHub executor exact-base apply
  -> CI / PR
```

It explicitly states that Phase 2A is not an OS sandbox, grants no arbitrary shell/PowerShell/cmd/package-install/task-controlled-network authority, gives the worker no GitHub source-write/push/merge authority, and does not alter ChatGPT/Codex plan limits or billing.

## Fresh release-surface diff before this closure commit

A fresh compare from Phase 1 baseline `7fbf1c15477632f2f36259bd9d91b3074807b3da` to `a939bcdf2abb594f7cd3767bc9a0fffac6b423ae` returned:

- status: ahead;
- ahead by 81 commits;
- behind by 0;
- 46 changed files.

Every changed file was confined to ASTRA/Phase 2A surfaces: ASTRA workflows, `astra_worker/**`, the Phase 1 local executor hardening, worker installer/service template, ASTRA launchers, Phase 2A plans/specs, ASTRA skill, and ASTRA/worker tests.

No CBI business-runtime, Evidence semantics, canonical identity, WAL/recovery, R2, Decision Saturation, CRM/outreach, product/domain logic, or production-deployment semantic file appeared in that compare.

## Trust boundary retained

Phase 2A remains fail-closed around the reviewed scope:

- unsigned GitHub issue text is not execution authority;
- remote tasks cannot choose local paths, Git remotes/refspecs, arbitrary executables/shell text, credentials, push destinations, or protected-branch overrides;
- worker synchronization is read-only and exact-base pinned;
- worker execution is confined to derived ephemeral worktrees;
- only signed declared mutations may survive final evidence;
- worker receipts are independently authenticated and receipt-gate verified;
- returned patch text is evidence, not remote mutation authority;
- GitHub-authoritative apply must re-check exact base and per-file pre-state and derive final bytes from the signed task;
- no worker auto-push or auto-merge exists;
- local Administrator compromise, malicious trusted repository code/dependencies, and replacement of trusted Python/Git executables remain outside the Phase 2A OS trust boundary.

## Final post-commit gate

This file is the final repository mutation planned for Phase 2A engineering verification unless CI reveals a real defect. After this commit:

1. run exact-head Phase 2A CI on all four OS/Python matrix jobs;
2. read the Ubuntu / Python 3.11 exact-head log and record the actual focused/full counts;
3. repeat the baseline compare from `7fbf1c15477632f2f36259bd9d91b3074807b3da` and confirm the only additional file is this verification record;
4. confirm the authoritative base branch and draft PR state are current and unmerged;
5. place the final exact-head SHA, CI run, counts, diff summary, trust boundary, and no-auto-merge policy in the draft PR body.

Only after those observations are fresh may the Phase 2A branch be described as **engineering-verification merge-ready**. That term does not mean the Windows worker is installed, secrets are provisioned, the default-branch operational gates are activated, or production operation has begun.
