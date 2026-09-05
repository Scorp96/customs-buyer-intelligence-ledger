# CBI v6.4 Production Promotion Topology Checkpoint

Date: 2026-09-05

## Authoritative refs

- Source: `cbi-v6-3-demand-expansion@58e14973c62cca5a9daefa7b4012e427135736d5`
- Release candidate: `cbi-v64-release-candidate-58e14973@4733a9b3e7286b58828750542c7ad54057cfb8ad`
- Production: `cbi-v6-cloud-runtime-20260901@a311a2a57ee43a1f1a3b2819bf28946566b05692`
- Integrated promotion candidate: `cbi-v64-release-candidate-integrated-4733a9b3-a311a2a5@17f4fe160c0908a602224eab95d172ba4eb753c6`

## Original topology defect

Fresh compare initially showed candidate and production diverged from merge base `58e14973c62cca5a9daefa7b4012e427135736d5`: candidate ahead 11 commits and production ahead 6. Temporary rehearsal PR #20 from the unintegrated candidate reported a real merge conflict and was closed without merge.

Production-only changes relative to source were confined to:

1. `.github/workflows/cbi-v6-ci.yml`
2. `tests/test_v63_adapter_patch_compiler.py`
3. `tests/test_v63_render_r2_workflow_contract.py`
4. `tests/test_v6_windows_portability.py`

Mechanical ours/theirs resolution was rejected because candidate and production both carried meaningful test/CI semantics.

## Semantic reconciliation

### `tests/test_v6_windows_portability.py`

The candidate remains authoritative. It preserves `environment = dict(os.environ)` and strengthens the old fixed-count checks into declared core/production tool-surface equality. No regression to the production Windows environment-preservation behavior was introduced.

### `tests/test_v63_render_r2_workflow_contract.py`

Candidate explicit external-coordinate hygiene remains authoritative, with two production semantics restored:

- `CBI_V63_R2_REGION` is included in the cleared external configuration set;
- `environment["PYTHONHASHSEED"] = "0"` preserves deterministic subprocess behavior.

### `tests/test_v63_adapter_patch_compiler.py`

Candidate semantics remain authoritative. Comparison found no production-only assertion that needed to be restored.

### `.github/workflows/cbi-v6-ci.yml`

The integrated tree preserves the exact production blob `8d21efa150a8c5c18a60060d08a7846360c74921`, including the production CI dependency line `PyYAML==6.0.2 tzdata==2026.3`.

## TDD evidence

A test-only RED commit was created on the isolated integration branch:

- RED commit: `97c49cc497108e3d77f0cff5d7d5173ffd5fec31`
- parent: exact release candidate `4733a9b3e7286b58828750542c7ad54057cfb8ad`
- test: `tests/test_v64_promotion_integration_contract.py`

GitHub Actions run `33941295839` produced the expected RED: 1005 tests ran and only the two new missing-integration assertions failed (production CI portability and Render/R2 region/hashseed semantics). The candidate Windows semantic assertion passed.

## Integrated merge commit

A real two-parent merge commit was created without rewriting either authoritative branch:

- integrated SHA: `17f4fe160c0908a602224eab95d172ba4eb753c6`
- tree: `ee83e3756015ad1aaf1206f5fc346c9c69b9f5f6`
- first parent: RED RC descendant `97c49cc497108e3d77f0cff5d7d5173ffd5fec31`
- second parent: exact production `a311a2a57ee43a1f1a3b2819bf28946566b05692`
- message: `merge(v64): reconcile production lineage into release candidate`

Fresh production-to-integrated comparison reports `ahead_by=13`, `behind_by=0`, with production itself as merge base. Therefore the integrated candidate is a descendant of the exact production ref while retaining the RC lineage.

## Exact-SHA release CI

Permanent release-candidate CI automatically ran against exact integrated SHA `17f4fe160c0908a602224eab95d172ba4eb753c6`:

- run: `33941452053`
- `regression (ubuntu-latest, py3.10)` — SUCCESS
- `regression (ubuntu-latest, py3.11)` — SUCCESS
- `regression (windows-latest, py3.10)` — SUCCESS
- `regression (windows-latest, py3.11)` — SUCCESS

Linux Python 3.11 also completed the Docker cloud Runtime smoke; the other matrix combinations skipped that Linux-3.11-only step as designed. Full unittest, load/performance acceptance, MCP protocol gates, privacy scan, compatibility/intelligence/outreach/strategic self-tests and deterministic v3 checks passed in the applicable jobs.

## GitHub mergeability rehearsal

Temporary draft PR #21 was opened from the exact integrated branch to unchanged production solely to force GitHub's mergeability calculation.

After GitHub calculation settled:

- base SHA: `a311a2a57ee43a1f1a3b2819bf28946566b05692`
- head SHA: `17f4fe160c0908a602224eab95d172ba4eb753c6`
- `mergeable=true`
- `mergeable_state=clean`

PR #21 was immediately closed without merge. Its final state is `closed`, `merged=false`, `merged_at=null`.

## Safety / authoritative refs after integration

Fresh checks confirm:

- release candidate branch remains `4733a9b3e7286b58828750542c7ad54057cfb8ad`;
- production branch remains `a311a2a57ee43a1f1a3b2819bf28946566b05692`;
- no production branch update, Render deploy, Render environment mutation, R2 write, CRM mutation, or live Runtime mutation occurred.

## Result

**Production-lineage integration gate: GREEN.**

The earlier merge conflict blocker is resolved on the isolated integrated promotion candidate. It does not by itself authorize promotion.

Two external blockers remain before production promotion:

1. **C279 authoritative current-cloud root:** provide an authorized read-only generation-669 production runtime-root/archive path or bytes, then run the SAFE isolated full-runtime C279 verifier and prove `prepare_outreach` on the isolated copy produces `sends_message=false`.
2. **Production ruleset:** create and verify active `protect-cbi-production` protection for `cbi-v6-cloud-runtime-20260901` with deletion/non-fast-forward protection, PR requirement, resolved review threads, strict checks, and the four exact regression contexts.

Until both are green, keep PR #19 draft and do not promote production.
