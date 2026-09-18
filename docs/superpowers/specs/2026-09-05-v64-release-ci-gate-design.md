# CBI v6.4 Permanent Release CI Gate Design

## Purpose

Make release-candidate verification a permanent, repeatable lifecycle gate instead of depending on ad-hoc workflow dispatch, a PR retargeted to `main`, or a temporary proof branch.

## Scope

This design changes only GitHub Actions release verification. It does not merge PR #19, update `cbi-v6-cloud-runtime-20260901`, deploy Render, mutate R2, change runtime data, or create/modify repository rulesets.

## Current problem

The existing `.github/workflows/cbi-v6-ci.yml` runs the required four-platform regression matrix, but its automatic triggers are tied to the old `cbi-v6-20260828` push branch and pull requests targeting `main`. The current v6.4 release candidate targets `cbi-v6-3-demand-expansion`, while `main` is materially divergent. The available GitHub connector cannot start a new `workflow_dispatch` run. Therefore the current workflow cannot produce candidate-SHA four-platform evidence without an unsafe or semantically misleading trigger workaround.

## Decision

Add a permanent release-candidate workflow at `.github/workflows/cbi-release-ci.yml`.

It will trigger on pushes to branches matching `cbi-v*-release-candidate-*` and retain `workflow_dispatch` for human or future-tool use. It will execute the same four required regression jobs as the existing CI matrix:

- `regression (ubuntu-latest, py3.10)`
- `regression (ubuntu-latest, py3.11)`
- `regression (windows-latest, py3.10)`
- `regression (windows-latest, py3.11)`

The workflow will verify the SHA actually checked out by Actions. Evidence is valid only when all four matrix jobs are green for the exact release-candidate head SHA being considered for acceptance.

## Architecture

The release workflow is a thin release-specific entry point over the repository's existing regression contract. To avoid two independently drifting test implementations, the workflow reuses the same test commands and pinned Actions versions currently present in `cbi-v6-ci.yml`. The first v6.4 implementation may duplicate the job body because GitHub Actions does not currently expose a reusable workflow in this repository; behavioral parity is enforced by a repository test that checks trigger, matrix, job name, and required command coverage.

A later refactor to a reusable workflow is explicitly out of scope for v6.4 because it would increase release risk without reducing the current blocker.

## Trigger contract

The workflow MUST:

1. Run automatically on `push` for `cbi-v*-release-candidate-*` branches.
2. Support `workflow_dispatch`.
3. NOT trigger on pushes to `main`, production, or arbitrary feature branches.
4. NOT require retargeting a release PR to `main`.
5. Use concurrency keyed by branch/ref so superseded candidate runs cancel safely.

## Verification contract

The release workflow MUST:

1. Use `ubuntu-latest` and `windows-latest`.
2. Use Python `3.10` and `3.11`.
3. Keep `fail-fast: false`, so one failure cannot hide the other matrix results.
4. Run `python -m unittest discover -s tests -p "test_*.py" -v`.
5. Run the existing load acceptance, MCP protocol checks, privacy scan, compatibility/intelligence/outreach/strategic/v3 self-tests, and the Linux/Python-3.11 Docker cloud-runtime smoke currently used by `cbi-v6-ci.yml`.
6. Pin the same `actions/checkout` and `actions/setup-python` revisions as the existing CI workflow at implementation time.
7. Require no repository write permissions; `contents: read` is sufficient.

## Candidate SHA semantics

A release candidate is not four-platform verified merely because an ancestor or equivalent-looking tree passed CI. The acceptance record must identify the exact candidate head SHA and all four successful matrix jobs for that SHA.

Any subsequent commit to the candidate branch invalidates the previous four-platform acceptance evidence and requires a new four-matrix run.

## Fail-closed behavior

The lifecycle gate remains RED/blocked if:

- any matrix job is missing, cancelled, timed out, skipped unexpectedly, or failed;
- the run SHA differs from the current candidate head SHA;
- only a historical/ancestor SHA is green;
- a run was produced by retargeting to divergent `main` solely to obtain CI;
- the candidate branch changed after the recorded run.

## Repository test

Add a focused test (for example `tests/test_release_ci_contract.py`) that parses `.github/workflows/cbi-release-ci.yml` and asserts:

- release-candidate push glob is present;
- `workflow_dispatch` is present;
- matrix OS set is exactly `{ubuntu-latest, windows-latest}`;
- matrix Python set is exactly `{3.10, 3.11}`;
- regression job name preserves the four required status-check names;
- `fail-fast` is false;
- unittest discovery uses `test_*.py`;
- production and `main` are not included as release-workflow push targets.

The test is structural governance protection; it does not replace the actual four-platform run.

## Lifecycle integration

The v6.4 release lifecycle becomes:

`SOURCE_VERIFIED`
→ `SEMANTIC_FORWARD_PORT_GREEN`
→ `RELEASE_CANDIDATE_CREATED`
→ `RELEASE_CI_GATE_INSTALLED`
→ `FOUR_MATRIX_GREEN`
→ `C279_CURRENT_CLOUD_GREEN`
→ `PRODUCTION_RULESET_GREEN`
→ `RELEASE_ACCEPTANCE_GREEN`
→ `PR_READY`
→ `MERGED`
→ `PRODUCTION_PROMOTION`
→ `POST_PROMOTION_VERIFIED`

The three pre-merge release gates remain independent. Installing or passing Release CI does not waive C279 or production-ruleset requirements.

## Migration strategy

Implementation occurs without production mutation:

1. Add the contract test and prove it fails before the workflow exists or satisfies the contract.
2. Add `.github/workflows/cbi-release-ci.yml` with the permanent trigger and four-matrix regression body.
3. Run targeted governance tests and the repository regression suite.
4. Apply the verified workflow/test change to the release-candidate branch.
5. Let the candidate push create an actual GitHub Actions run.
6. Verify all four matrix jobs and exact run SHA from GitHub.
7. Keep PR #19 draft while C279 and production-ruleset gates remain blocked.

## Non-goals

- No change to `main`.
- No change to the production branch.
- No merge or production promotion.
- No Render deployment.
- No R2 mutation.
- No ruleset bypass.
- No substitution of historical C279 evidence.
- No claim that release acceptance is complete until all three independent gates are green.

## Success criteria

This design is successful when the current v6.4 release candidate has a permanent release workflow committed, GitHub automatically executes the exact four matrix jobs against the resulting candidate SHA, all four are green, and the remaining lifecycle blockers are reduced to C279 current-cloud evidence and the production ruleset.