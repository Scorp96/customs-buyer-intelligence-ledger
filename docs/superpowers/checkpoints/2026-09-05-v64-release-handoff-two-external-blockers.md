# CBI v6.4 Release Handoff — Two External Blockers

Date: 2026-09-05

## Current lifecycle state

`RELEASE_CANDIDATE_VERIFIED`
→ `PERMANENT_RELEASE_CI_GREEN`
→ `PRODUCTION_LINEAGE_INTEGRATED`
→ `INTEGRATED_EXACT_SHA_FOUR_MATRIX_GREEN`
→ `PRODUCTION_MERGEABILITY_CLEAN`
→ **WAITING_ON_TWO_EXTERNAL_GATES**

Production promotion is not authorized yet.

## Authoritative refs

- Source: `cbi-v6-3-demand-expansion@58e14973c62cca5a9daefa7b4012e427135736d5`
- Original RC: `cbi-v64-release-candidate-58e14973@4733a9b3e7286b58828750542c7ad54057cfb8ad`
- Production: `cbi-v6-cloud-runtime-20260901@a311a2a57ee43a1f1a3b2819bf28946566b05692`
- Integrated promotion candidate: `cbi-v64-release-candidate-integrated-4733a9b3-a311a2a5@17f4fe160c0908a602224eab95d172ba4eb753c6`

## Integration gate — GREEN

- TDD RED commit: `97c49cc497108e3d77f0cff5d7d5173ffd5fec31`
- RED run: `33941295839`, failed exactly the two intended missing integration semantics.
- Two-parent integrated merge commit: `17f4fe160c0908a602224eab95d172ba4eb753c6`
- Parents: `97c49cc497108e3d77f0cff5d7d5173ffd5fec31` and exact production `a311a2a57ee43a1f1a3b2819bf28946566b05692`.
- Exact integrated release CI run: `33941452053`.
- Ubuntu 3.10: SUCCESS.
- Ubuntu 3.11: SUCCESS.
- Windows 3.10: SUCCESS.
- Windows 3.11: SUCCESS.
- Rehearsal PR #21: GitHub settled to `mergeable=true`, `mergeable_state=clean`; then closed, `merged=false`, `merged_at=null`.
- Fresh production→integrated topology: production is an ancestor; `behind_by=0`.

## External gate 1 — C279 authoritative generation-669 root

### Current verified state

- Production Runtime: READY.
- Production object store: `object_state_v2`, generation 669, restore generation 669.
- Production SHA: `a311a2a57ee43a1f1a3b2819bf28946566b05692`.
- C279 durable tail: seq 27 / event hash `cf5d92ecf7f7d4842306cc39134bdd09aced5fd087179da1ab6b0da5ca19b498`.
- Current production readiness: `IDENTITY_ONLY`.
- Current blocker: `VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED`.
- Canonical/effective account-owned route count remains zero.

### Non-mutating routes already exhausted

- Existing `CBI_V63_R2_*` Actions credentials against production pointer: HTTP 403.
- Anonymous production R2 pointer: AUTH_REQUIRED.
- Production MCP: 65 tools, but no raw runtime-root/archive/snapshot/backup export surface.
- Remote HTTP transport: GET only exposes health/readiness metadata, no bundle download route.
- Render connector: no shell/SSH execution and no secret-value read.
- GitHub secret-presence probes: tested production R2/Render/SSH/C279 aliases absent.
- Plugin discovery: no Cloudflare R2 or Render-shell integration available beyond current Render connector.
- Further broad secret-alias workflow creation was blocked by platform safety checks; do not attempt to bypass that safety control.

### Accepted unlock paths

Any one of these is sufficient to resume:

1. authenticated **read-only** production R2/archive access capable of retrieving generation-669 state bytes;
2. authorized **read-only** Render filesystem/SSH access capable of copying `/var/lib/cbi/live` or the exact authoritative sessions/state bundle without mutating it;
3. explicit user approval for a narrowly scoped temporary production export channel. This is a production configuration/code mutation and must not be inferred from generic continuation instructions.

### Required proof after unlock

- bind private C279 bridge tail to authoritative source JSONL;
- copy source root into a temporary isolated root;
- instantiate full current v6.4 Runtime on isolated copy;
- run readiness/health;
- call `prepare_outreach` only on isolated copy;
- prove `sends_message=false`;
- prove live/source root did not change.

## External gate 2 — production branch ruleset

### Current verified state

- Only active repository ruleset: `protect-main`, id `21810779`.
- Production branch reports `protected=false`.
- `protect-cbi-production` does not exist.
- Current GitHub connector can read rulesets but exposes no repository-administration write action for creating/updating them.
- Plugin discovery found no alternate GitHub ruleset/branch-protection administration integration.

### Required ruleset semantics

Create active `protect-cbi-production` scoped only to `cbi-v6-cloud-runtime-20260901` with at minimum:

- deletion protection;
- non-fast-forward protection;
- pull-request requirement;
- review-thread resolution requirement;
- strict required status checks;
- exact required contexts:
  - `regression (ubuntu-latest, py3.10)`
  - `regression (ubuntu-latest, py3.11)`
  - `regression (windows-latest, py3.10)`
  - `regression (windows-latest, py3.11)`

Creating or weakening production governance is a high-impact repository administration operation. Do not substitute changes to `protect-main` and do not infer authorization to create the production ruleset from ordinary continuation instructions.

## Release safety state

- PR #19 remains OPEN, DRAFT, UNMERGED.
- Rehearsal PR #21 is CLOSED, UNMERGED.
- Production branch remains `a311a2a57ee43a1f1a3b2819bf28946566b05692`.
- Original RC remains `4733a9b3e7286b58828750542c7ad54057cfb8ad`.
- No Render deploy, Render environment mutation, R2 write, CRM mutation, live Runtime mutation, or production branch update was performed during production-lineage integration.

## Exact next-window starting point

Do not repeat merge-conflict analysis or release CI work. Start by checking whether either external unlock has become available:

1. authorized read-only production Runtime/R2/Render filesystem access for C279; and/or
2. GitHub repository-administration capability / explicit ruleset-creation approval.

If neither has changed, report `PRODUCTION_READY=NO` with exactly those two blockers and do not perform production promotion.
