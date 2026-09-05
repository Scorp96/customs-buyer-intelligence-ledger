# CBI v6.4 Production Promotion Topology Checkpoint

Date: 2026-09-05

## Authoritative refs

- Source: `cbi-v6-3-demand-expansion@58e14973c62cca5a9daefa7b4012e427135736d5`
- Release candidate: `cbi-v64-release-candidate-58e14973@4733a9b3e7286b58828750542c7ad54057cfb8ad`
- Production: `cbi-v6-cloud-runtime-20260901@a311a2a57ee43a1f1a3b2819bf28946566b05692`

## Topology result

Fresh compare shows candidate and production are diverged from the same merge base `58e14973c62cca5a9daefa7b4012e427135736d5`:

- candidate is 11 commits ahead of the merge base;
- production is 6 commits ahead of the merge base;
- candidate compared with production is `ahead 11 / behind 6`;
- therefore the current candidate cannot be promoted to production by fast-forward.

A temporary remote rehearsal base was created from exact production SHA and a draft rehearsal PR was opened from the exact candidate SHA. GitHub reported `mergeable=false`. Temporary PR #20 was then closed without merge. Production was never modified.

## Production-only change surface

Compared with the authoritative source, the production-only lineage changes only four paths:

1. `.github/workflows/cbi-v6-ci.yml`
2. `tests/test_v63_adapter_patch_compiler.py`
3. `tests/test_v63_render_r2_workflow_contract.py`
4. `tests/test_v6_windows_portability.py`

The release candidate also changes the three test paths, while `.github/workflows/cbi-v6-ci.yml` is production-only. This overlap explains why a mechanical history merge is unsafe.

## Semantic overlap findings

### `tests/test_v6_windows_portability.py`

The production hotfix preserved the full Windows subprocess system environment and validated the v6.3 tool surface. The current candidate keeps `environment = dict(os.environ)` and strengthens the test by replacing fixed tool counts with declared core/production tool-surface equality checks. A resolution must retain the candidate's stronger assertions and must not regress the production environment-preservation behavior.

### `tests/test_v63_render_r2_workflow_contract.py`

The source test launched the blocked-external CLI with a minimal `PATH`-only environment. Production changed this to start from `dict(os.environ)`, remove external coordinates, preserve PATH, and set deterministic `PYTHONHASHSEED=0`. The current candidate also starts from `dict(os.environ)` and removes an explicit external-configuration key set before running the CLI. A resolution must preserve the candidate's explicit configuration hygiene while retaining all production portability/determinism guarantees that remain applicable, including handling of `CBI_V63_R2_REGION` if it is considered part of the external coordinate set.

### `tests/test_v63_adapter_patch_compiler.py`

The production and candidate versions are semantically near-equivalent around the overlapping hotfix surface; the current candidate contains later v6.4-compatible test state. Resolution should prefer current candidate semantics unless a production-only assertion is identified during TDD comparison.

### `.github/workflows/cbi-v6-ci.yml`

This path is production-only relative to the authoritative source and must be retained unchanged in the integrated promotion candidate unless a separately reviewed reason requires modification.

## Proposed bounded integration design — NOT YET IMPLEMENTED

This is an existing release-flow reconciliation, not a new runtime feature.

1. Create a new integration branch whose merge commit is a descendant of both the exact current release candidate and exact current production SHA. Do not rewrite or mutate either existing branch.
2. Use the candidate tree as the v6.4 semantic authority.
3. Preserve the production-only `.github/workflows/cbi-v6-ci.yml` state.
4. Resolve the three overlapping test files semantically, retaining all current candidate v6.4 assertions plus the still-relevant production Windows/environment portability guarantees.
5. Add no runtime feature behavior and no production deployment mutation as part of this reconciliation.
6. Name the integrated branch so the permanent release-candidate CI workflow runs automatically on its exact head SHA.
7. Require Ubuntu/Windows × Python 3.10/3.11 all green on the integrated exact SHA, then run another GitHub mergeability rehearsal against the unchanged production branch.
8. Keep PR #19 draft and production unchanged until C279 and production-ruleset blockers are also green.

Per Superpowers brainstorming governance, implementation of this bounded integration requires explicit user approval of the design above before any merged tree/commit is created.
