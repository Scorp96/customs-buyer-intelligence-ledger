# CBI v6.4 Backup-Retention CLI Repair and Local Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the Sol Advisor Astra bounded Luna implementation route. The Luna worker implements Task 1 only; the primary agent retains review, release, merge and local-upgrade authority.

**Goal:** Repair the direct v6.4 backup-retention acceptance CLI, merge the verified change through an independent PR, and upgrade the installed local CBI plugin from 6.1.0 to the merged 6.4 build without migrating or rewriting production data.

**Architecture:** Add the same repository-root import bootstrap already used by the other direct CBI scripts, prove the actual filesystem entrypoint through subprocess tests, and make GitHub CI start the CLI directly. Keep code repair, protected-branch integration and local plugin promotion as separate gated stages.

**Tech Stack:** Python 3.10/3.11 standard library, `unittest`, Git/GitHub CLI, Codex plugin CLI, PowerShell, Sol Advisor Astra Luna implementer.

**Spec:** `docs/superpowers/specs/2026-09-22-cbi-v64-backup-retention-cli-local-upgrade-design.md`

## Global Constraints

- Base exactly on `3e04baee81a825edaeb9b5e11c5ee39321298c0f` and work only on `fix/cbi-v64-backup-retention-cli-20260922`.
- Never push directly to or locally rewrite `cbi-v6-cloud-runtime-20260901`.
- Do not include PR #71, any other unmerged branch, or the historical request-scoped verified-snapshot patch.
- Do not change schemas, version numbers, performance thresholds, backup policy, Closure, Route, CRM or outreach behavior.
- Do not add dependencies.
- Do not read, migrate, transform or write customer session data during Task 1.
- The Luna worker owns only `scripts/run_v64_backup_retention_acceptance.py`, `tests/test_v64_backup_retention_acceptance.py`, and `.github/workflows/cbi-v64-backup-wal-release-gate.yml`.
- The Luna worker must not spawn other agents, push, create a PR, merge, reinstall plugins, or operate on the production data root.
- The primary agent must inspect the complete diff and independently rerun the local acceptance ladder before any push.
- Merge only after every GitHub PR check is successful or legitimately skipped and all four protected regression checks are successful.
- Local promotion is a 6.1-to-6.4 code/plugin upgrade; never call `migrate_v5_4_1_to_v6` and never switch `CBI_SESSION_ROOT`.

## Review Focus

- Direct execution from the repository root must import `unified_runtime` without relying on an inherited `PYTHONPATH`; Task 1 tests `--help` through `subprocess.run` with a controlled environment.
- A valid sanitized payload supplied on stdin must return exit 0 and verified JSON; Task 1 runs the real CLI and parses stdout.
- Invalid JSON must remain fail-closed with exit 1 and `ACCEPTANCE_INPUT_INVALID`; Task 1 pins the existing error contract through the real CLI.
- Windows and POSIX path handling must use `Path` and `sys.executable`; Task 1 avoids shell pipelines and hard-coded Python names.
- CI must execute the file entrypoint, not merely import its function; Task 1 adds an explicit `--help` workflow step to every matrix job.

---

### Task 1: Repair and gate the direct backup-retention CLI

**Files:**
- Modify: `scripts/run_v64_backup_retention_acceptance.py`
- Modify: `tests/test_v64_backup_retention_acceptance.py`
- Modify: `.github/workflows/cbi-v64-backup-wal-release-gate.yml`

**Interfaces:**
- Consumes: `build_backup_retention_evidence(...)` and the existing JSON stdin/file CLI contract.
- Produces: a directly executable script whose `main(argv)` contract and evidence schema remain unchanged.
- Produces: subprocess regression coverage for help, verified input and invalid input.
- Produces: a GitHub Actions matrix step that starts the real script directly.

- [ ] **Step 1: Add subprocess test imports and path constants**

Add these standard-library imports to the test module:

```python
import json
import os
from pathlib import Path
import subprocess
import sys
```

Define the real entrypoint without a platform-specific path:

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "scripts" / "run_v64_backup_retention_acceptance.py"
```

- [ ] **Step 2: Add a helper that runs the real CLI in a controlled environment**

Add this helper after `_payload`:

```python
def _run_cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=REPO_ROOT,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
```

The explicit `PYTHONPATH` removal proves the script provides its own import
bootstrap rather than inheriting the test runner's environment.

- [ ] **Step 3: Add the three direct-entrypoint tests**

Add a `BackupRetentionAcceptanceCliTests` class:

```python
class BackupRetentionAcceptanceCliTests(unittest.TestCase):
    def test_help_runs_without_repository_pythonpath(self) -> None:
        completed = _run_cli("--help")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "Evaluate sanitized v6.4 backup retention observations.",
            completed.stdout,
        )

    def test_verified_payload_runs_through_real_cli(self) -> None:
        completed = _run_cli(stdin=json.dumps(_payload()))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        evidence = json.loads(completed.stdout)
        self.assertTrue(evidence["verified"], evidence["blockers"])
        self.assertEqual(
            evidence["schema"],
            "cbi.v64-backup-retention-evidence.v1",
        )

    def test_invalid_json_fails_closed_through_real_cli(self) -> None:
        completed = _run_cli(stdin="{not-json")

        self.assertEqual(completed.returncode, 1, completed.stdout)
        evidence = json.loads(completed.stdout)
        self.assertFalse(evidence["verified"])
        self.assertEqual(evidence["blockers"], ["ACCEPTANCE_INPUT_INVALID"])
```

- [ ] **Step 4: Run the new tests and preserve red evidence**

Run:

```powershell
& 'C:\Users\scorp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_v64_backup_retention_acceptance.BackupRetentionAcceptanceCliTests -v
```

Expected before implementation: all three subprocess cases fail because the
script exits before argument or JSON handling with
`ModuleNotFoundError: No module named 'unified_runtime'`.

Record the exact command, exit code and failure summary in the worker report.

- [ ] **Step 5: Implement the minimal repository-root bootstrap**

In `scripts/run_v64_backup_retention_acceptance.py`, after standard-library
imports and before the `unified_runtime` import, add:

```python
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

Do not change `evaluate_backup_retention_acceptance`, `_read_payload`, `main`,
return codes or schemas.

- [ ] **Step 6: Re-run the focused module and require green**

Run:

```powershell
& 'C:\Users\scorp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_v64_backup_retention_acceptance -v
```

Expected: all ten tests pass, including all three real subprocess cases.

- [ ] **Step 7: Add the direct CLI workflow gate**

In `.github/workflows/cbi-v64-backup-wal-release-gate.yml`, immediately after
the focused acceptance step, add:

```yaml
      - name: Run direct backup retention CLI smoke
        run: python scripts/run_v64_backup_retention_acceptance.py --help
```

This runs on all four existing OS/Python matrix combinations.

- [ ] **Step 8: Run task-level static and direct checks**

Run:

```powershell
& 'C:\Users\scorp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts/run_v64_backup_retention_acceptance.py --help
& 'C:\Users\scorp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m compileall -q scripts tests
git diff --check
git status --short
```

Expected: the help command exits 0; compileall and diff check exit 0; only the
three owned files plus the already approved spec/plan documents are changed.

- [ ] **Step 9: Self-review and commit the implementation**

Review `git diff -- scripts/run_v64_backup_retention_acceptance.py tests/test_v64_backup_retention_acceptance.py .github/workflows/cbi-v64-backup-wal-release-gate.yml` and confirm no policy logic changed. Then run:

```powershell
git add scripts/run_v64_backup_retention_acceptance.py tests/test_v64_backup_retention_acceptance.py .github/workflows/cbi-v64-backup-wal-release-gate.yml
git commit -m "fix(v64): make backup retention CLI directly executable"
```

Write the worker report with status, commit SHA, red/green commands and outputs,
changed files, self-review findings and any concern. Return only the short
status contract to the primary agent.

---

## Primary-agent acceptance after Task 1

The primary agent must inspect the complete `3e04bae..HEAD` diff and confirm
that it contains only the two approved documents and the three Task 1 files.
Then run, in this order:

```powershell
$pythonExe='C:\Users\scorp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe -m unittest tests.test_v64_backup_retention_acceptance -v
& $pythonExe scripts/run_v64_backup_retention_acceptance.py --help
& $pythonExe -m unittest discover -s tests -p 'test_*.py'
& $pythonExe tests/privacy_scan.py
& $pythonExe -m compileall -q mcp unified_runtime scripts
& $pythonExe scripts/run_v6_load_acceptance.py --profile smoke --enforce-targets
git diff --check 3e04baee81a825edaeb9b5e11c5ee39321298c0f..HEAD
git status --porcelain=v1
```

Any nonzero exit, dirty uncommitted state, changed performance threshold or
out-of-scope path stops the workflow before push.

## Push, PR and GitHub CI gate

After local acceptance is green:

```powershell
git push -u origin fix/cbi-v64-backup-retention-cli-20260922
$prBody='C:\Users\scorp\Documents\Codex\2026-08-21\referenced-chatgpt-conversation-this-is-an\work\cbi-v64-backup-retention-cli-fix\.superpowers\cbi-v64-backup-cli-pr-body.md'
gh pr create --base cbi-v6-cloud-runtime-20260901 --head fix/cbi-v64-backup-retention-cli-20260922 --title "fix(v64): make backup retention CLI directly executable" --body-file $prBody
```

Attach the returned PR URL to the current Codex task. Observe all check runs on
the PR head. Do not merge while any check is queued, in progress, failed,
cancelled, timed out or action-required. Require successful completion of:

- `regression (ubuntu-latest, py3.10)`
- `regression (ubuntu-latest, py3.11)`
- `regression (windows-latest, py3.10)`
- `regression (windows-latest, py3.11)`
- every additional check reported for the PR head, except checks explicitly
  marked skipped by their own workflow conditions.

After all checks are green, merge through the PR using squash merge. Never push
the merge commit directly:

```powershell
gh pr merge --squash
```

Fetch and record the new protected-branch head and merged PR commit before local
promotion.

## Post-merge local 6.1-to-6.4 promotion

1. Record the current source SHA, `codex plugin list`, installed 6.1 cache
   manifest, Runtime health and full production session-root fingerprint.
2. Invoke the current installed 6.1 operator backup command with reason
   `BEFORE_PLUGIN_6_4_UPGRADE`, validate the returned snapshot using the current
   backup manager, and confirm that the backup root is outside the live session
   root.
3. Fetch the protected base and prove the merged PR is an ancestor of its head.
4. In `C:\Users\scorp\plugins\customs-buyer-intelligence`, require a clean
   worktree and fast-forward only:

```powershell
git fetch origin cbi-v6-cloud-runtime-20260901
git merge --ff-only origin/cbi-v6-cloud-runtime-20260901
```

5. Install the merged source through the configured marketplace:

```powershell
codex plugin add customs-buyer-intelligence@personal --json
```

6. Verify `codex plugin list`, the new cache manifest and the new cached
   `UnifiedRuntime` contract all report 6.4.0. Run health against the unchanged
   production session root and require `READY`, 35 checked sessions, 27
   canonical accounts and no errors.
7. Recompute the data fingerprint and require the accepted pre-upgrade identity.
8. Preserve the 6.1 cache and recorded source SHA for rollback. Do not delete
   the repair worktree while PR feedback or post-merge audit remains possible.

If any post-install check fails, switch the clean local source back to the
recorded pre-upgrade SHA, reinstall through the personal marketplace, and verify
that 6.1 health and the data fingerprint are restored. Never rewrite session
logs as a rollback technique.
