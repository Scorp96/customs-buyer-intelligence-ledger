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
- RED run: `33941295839`, failed exactly the intended missing integration semantics.
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
- C279 durable tail remains seq 27 with the previously bound private event hash.
- Current production readiness: `IDENTITY_ONLY`.
- Current blocker: `VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED`.
- Canonical/effective account-owned route count remains zero.
- Fresh post-exhaustion semantic probe: run `33942814266`, job `101243365731`; generation 669 and recovery fingerprint stable; no mutating tool, private raw value, or secret value was emitted.

### Non-mutating routes exhausted

- Existing `CBI_V63_R2_*` Actions credentials against production pointer: HTTP 403.
- Anonymous production R2 pointer: AUTH_REQUIRED.
- The exact production runtime secret names `CBI_OBJECT_STORE_MODE`, `CBI_OBJECT_STORE_ENDPOINT`, `CBI_OBJECT_STORE_BUCKET`, `CBI_OBJECT_STORE_ACCESS_KEY_ID`, `CBI_OBJECT_STORE_SECRET_ACCESS_KEY`, `CBI_OBJECT_STORE_REGION`, `CBI_OBJECT_STORE_PREFIX`, and `CBI_OBJECT_STORE_RETENTION` were all absent in GitHub Actions in presence-only run `33942814272`; no network call or secret value output occurred.
- Existing production/release workflows have no GitHub Actions `environment:` binding and no alternate committed production object-store credential mapping.
- Production MCP: 65 tools, but no raw append-event/session JSONL/runtime-root/archive/snapshot/backup export surface.
- Remote HTTP transport: `/mcp` GET is disabled; there is no independent `resources/list` / `resources/read` download surface.
- Render connector: no shell/SSH execution and no secret-value read. Service previews remain disabled/off; no reusable environment-group inheritance path is exposed by the connected control plane.
- Plugin discovery: no Cloudflare R2 connector is available.
- Library/file-name and semantic searches found no saved valid production R2 credential, Render SSH private key, generation-669 archive, C279 session JSONL, or readonly-minimal runtime export.
- Historical Windows migration archive is generation 0 / rollback-only and cannot replace generation 669.
- Historical security record states the formerly exposed R2 token was revoked and replaced; the valid bucket-scoped token was stored only in Render Environment. The revoked token must not be recovered or reused.

### GitHub Actions artifacts audited byte-for-byte

- C279 current-cloud preflight artifact `9960768288`: one 1337-byte JSON file only; ZIP SHA256 `44fe4e8fa1c72cb7bb3814cf4c1b2edd75e7b18a5871fddd34c2a4e5ac8e2042`; no runtime/session/archive bytes.
- Source exact-checkout live-acceptance run `33760447567`, artifact `9895310327`: four JSON acceptance/recovery/correlation files only; no runtime archive.
- All four historical isolated Render/R2 workflow-dispatch runs were enumerated. Successful artifacts `9893653145` and `9892512260` both use isolated prefix `cbi-v63-acceptance-20260903-r01`, not production `cbi-v61`; failed-run artifacts are only 394/498 bytes.

Detailed sanitized evidence is in `docs/superpowers/checkpoints/2026-09-05-v64-c279-access-exhaustion-final.md` at checkpoint commit `5894cba9cf212af25f853bb4953aeadfb5590ba3`.

### Accepted unlock paths

Any one of these is sufficient to resume:

1. authenticated **read-only** production R2/archive access capable of retrieving generation-669 state bytes;
2. authorized **read-only** Render filesystem/SSH access capable of copying `/var/lib/cbi/live` or the exact authoritative sessions/state bundle without mutating it;
3. explicit user approval for a narrowly scoped temporary production export channel. This is a production configuration/code mutation and must not be inferred from generic continuation instructions.

### Required proof after unlock

- bind private C279 bridge tail to authoritative source JSONL;
- copy source root into a temporary isolated root;
- instantiate full current integrated v6.4 Runtime on isolated copy;
- run readiness/health;
- call `prepare_outreach` only on isolated copy;
- prove `sends_message=false`;
- prove live/source root did not change.

## External gate 2 — production branch ruleset

### Current verified state

- Only active repository ruleset: `protect-main`, id `21810779`.
- Production branch reports `protected=false`.
- `protect-cbi-production` does not exist.
- Current GitHub connector can read rulesets/protection but exposes no repository-administration write action.
- Plugin Management permission modes do not change GitHub OAuth/admin scopes.
- Plugin discovery found no alternate GitHub repository-administration provider.
- Production `.github/workflows` contains only CI/load/bootstrap/live-acceptance/isolated-R2-acceptance workflows; no repository-admin/ruleset workflow exists.
- Repository code search found no `ruleset`, branch-protection management, or `gh api` governance automation that could safely apply the missing rule through an existing controlled workflow.

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
- Integrated promotion candidate remains `17f4fe160c0908a602224eab95d172ba4eb753c6`.
- No Render deploy, Render environment mutation, R2 write/delete, CRM mutation, live Runtime mutation, production branch update, or production ruleset mutation was performed during this access-exhaustion cycle.

## Exact next-window starting point

Do not repeat merge-conflict analysis, release CI, hidden-secret-name probes, MCP-resource probing, historical artifact inspection, or workflow-admin searches.

Start only from a newly available external unlock:

1. authorized read-only production Runtime/R2/Render filesystem access for C279; and/or
2. GitHub repository-administration capability with explicit authority to create `protect-cbi-production`.

If neither external capability has changed, `PRODUCTION_READY=NO`; do not perform production promotion.
