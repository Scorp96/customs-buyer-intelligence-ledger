# CBI v6.4 Backup-Retention CLI Repair and Local Upgrade Design

## Goal

Repair the direct v6.4 backup-retention acceptance CLI on an independent Git
branch, prove the repair locally and in GitHub CI, merge it only through a pull
request into the protected `cbi-v6-cloud-runtime-20260901` branch, and only then
upgrade the local Codex plugin from 6.1.0 to the merged 6.4 build.

## Verified starting state

- Remote repository: `Scorp96/customs-buyer-intelligence-ledger`.
- Protected base branch: `cbi-v6-cloud-runtime-20260901`.
- Audited base commit: `3e04baee81a825edaeb9b5e11c5ee39321298c0f`.
- Independent repair branch: `fix/cbi-v64-backup-retention-cli-20260922`.
- The base manifest version is `6.4.0+codex.20260918`.
- The local source checkout is clean at `cab4537ff318d86d3cd4fff970eb83215edff4bb`
  and is 456 commits behind the audited base branch.
- The installed and enabled Codex plugin is
  `6.1.0+codex.20260829173100`.
- The active production session root is already a v6 data root. It contains 36
  files and 1,314,763 bytes with aggregate SHA-256
  `8d7e502220285893b9a740b468b0b90c4a7324fe4be31a6fd11a7a4fe4ac8957`.
- The 6.4 base reads a disposable copy of that data as `READY`, with 35 checked
  sessions, 27 canonical accounts and no errors, without changing either tree.
- The exact Git base passed 1,168 local tests, privacy scan, compileall,
  `git diff --check`, and the unchanged performance thresholds.
- `python scripts/run_v64_backup_retention_acceptance.py --help` fails on the
  audited base with `ModuleNotFoundError: No module named 'unified_runtime'`.

## Root cause

`scripts/run_v64_backup_retention_acceptance.py` imports
`unified_runtime.backup_retention_evidence_v64` before adding the repository
root to `sys.path`. Direct script execution makes `scripts/`, rather than the
repository root, Python's first import path. All other directly executable CBI
scripts that import `unified_runtime` already insert the repository root before
the import.

The existing acceptance unit tests import the script as a module from a test
process whose working directory is the repository root. They therefore test the
policy logic but not the real command-line entrypoint. The release workflow has
the same coverage gap: it runs the module-level tests but never starts this
script directly.

## Repair design

1. In `scripts/run_v64_backup_retention_acceptance.py`, define
   `ROOT = Path(__file__).resolve().parents[1]` and insert `str(ROOT)` at the
   beginning of `sys.path` when it is absent. This must occur after standard
   library imports and before importing `unified_runtime`.
2. Extend `tests/test_v64_backup_retention_acceptance.py` with subprocess tests
   that invoke the script by filesystem path using `sys.executable` from the
   repository root:
   - `--help` exits 0 and prints the argparse description;
   - a valid synthetic JSON payload on stdin exits 0 and returns verified
     evidence;
   - invalid JSON exits 1 and returns the existing fail-closed
     `ACCEPTANCE_INPUT_INVALID` evidence.
3. Extend `.github/workflows/cbi-v64-backup-wal-release-gate.yml` with a direct
   cross-platform CLI smoke step that runs
   `python scripts/run_v64_backup_retention_acceptance.py --help`.

No new dependency, CLI option, schema, version number, backup policy, evidence
policy, or production state mutation is permitted.

## Git and integration boundaries

- All repair work is based on exact commit `3e04bae` in the independent branch.
- The worker must not check out, merge, rebase, or push the protected base
  branch.
- Open PR #71 and every other unmerged branch are outside scope.
- The historical request-scoped verified-snapshot patch is outside scope; the
  audited base already meets performance thresholds and the historical patch
  has a known store-less-runtime regression.
- The repair branch is pushed only after the complete local acceptance ladder
  is green.
- A pull request targets `cbi-v6-cloud-runtime-20260901`.
- The pull request is merged only after every reported GitHub check is
  successful or legitimately skipped and the four protected regression checks
  are successful on the PR head.
- No direct push or local merge into the protected branch is allowed.

## Local acceptance ladder before push

Run from the repair worktree with the bundled Codex Python runtime:

1. Direct CLI red/green evidence for `--help`.
2. Focused acceptance module, including the three subprocess cases.
3. Full discovery: `python -m unittest discover -s tests -p "test_*.py"`.
4. Privacy scan: `python tests/privacy_scan.py`.
5. Compilation: `python -m compileall -q mcp unified_runtime scripts`.
6. Enforced performance acceptance:
   `python scripts/run_v6_load_acceptance.py --profile smoke --enforce-targets`.
7. Whitespace and repository cleanliness checks: `git diff --check` and
   `git status --porcelain=v1`.

The performance thresholds remain bundle `<5s`, warm median `<0.5s`, warm
tail/max `<=1.0s`, and resume `<3s`. The measurement protocol remains one cold
query, one unmeasured warm-up and exactly five warm samples.

## Post-merge local upgrade design

The local upgrade is code-only. It must not invoke `migrate_v5_4_1_to_v6` and
must not switch `CBI_SESSION_ROOT`.

1. Fetch the protected base and verify that the merged PR commit is an ancestor
   of the new protected-branch head.
2. Record the pre-upgrade source SHA, installed version, active cache manifest,
   Runtime health, data file count, byte count and aggregate SHA-256.
3. Create a product-supported pre-upgrade backup using the currently installed
   6.1 runtime, then validate the created snapshot. The backup destination must
   remain outside the live session root.
4. Fast-forward the local source checkout to the exact merged protected-branch
   head using `--ff-only`.
5. Reinstall from the configured personal marketplace with
   `codex plugin add customs-buyer-intelligence@personal --json`.
6. Verify that `codex plugin list` and the installed cache manifest report
   `6.4.0+codex.20260918`.
7. Instantiate the newly cached 6.4 Runtime against the existing production
   session root and require `READY`, 35 checked sessions, 27 canonical accounts
   and no errors.
8. Recompute the production data fingerprint and require the original 36 files,
   1,314,763 bytes and exact aggregate SHA-256. If the supported backup action
   changes a Runtime-owned file inside the session root, stop and compare the
   pre-backup and post-backup inventories instead of treating the expected
   backup as an unexplained mutation.
9. Keep the prior 6.1 cache and the recorded source SHA as rollback material.
10. Treat the current conversation's already-loaded 6.1 skill snapshot as
    stale. Final end-to-end plugin discovery requires a new Codex task or an app
    restart after installation.

## Rollback

If post-install validation fails, do not rewrite any session log. Switch the
local source checkout back to the recorded pre-upgrade SHA, reinstall the 6.1
plugin from the personal marketplace, and re-run the same health and fingerprint
checks. Preserve the failed 6.4 cache and logs for diagnosis.

## Success criteria

- The direct CLI subprocess tests demonstrate red before the repair and green
  after it.
- The complete local acceptance ladder is green on the repair branch.
- Parent inspection finds no out-of-scope diff.
- The independent branch is pushed and the PR is attached to this task.
- Every GitHub PR check is green or legitimately skipped; all protected
  regression checks are successful.
- The PR is merged through GitHub into the protected base branch.
- The local source reaches the exact merged protected-branch head by fast-forward.
- The installed plugin reports 6.4.0 and the post-install Runtime is `READY`.
- Production data identity, count and aggregate hash remain unchanged except for
  a separately explained, product-supported backup artifact outside the live
  root.
- No deployment, CRM mutation, outreach, cloud migration or customer-data
  transformation occurs.

## Stop conditions

Stop at the current stage if any of these occurs:

- A local test, privacy scan, compilation, performance, diff, or direct CLI gate
  fails.
- The worker changes files outside the three owned repair surfaces and the two
  approved spec/plan documents.
- The remote base moves incompatibly or the repair cannot be rebased without
  semantic judgment.
- Any GitHub check fails, is cancelled, or remains pending beyond the active
  observation window.
- The protected branch cannot be merged through the PR ruleset.
- The installed cache does not report the expected version.
- Runtime health is not `READY`, errors are present, or production data identity
  changes unexpectedly.
