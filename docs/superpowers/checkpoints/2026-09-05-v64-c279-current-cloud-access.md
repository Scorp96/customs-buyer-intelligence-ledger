# CBI v6.4 C279 Current-Cloud Access Checkpoint

Date: 2026-09-05

## Scope

This checkpoint records read-only evidence collected while attempting the required v6.4 C279 current-cloud isolated full-runtime regression. It contains no production credential values, no raw C279 investigation identifier, and no runtime archive contents.

## Release candidate state

- Authoritative source: `cbi-v6-3-demand-expansion@58e14973c62cca5a9daefa7b4012e427135736d5`.
- Current release candidate: `cbi-v64-release-candidate-58e14973@4733a9b3e7286b58828750542c7ad54057cfb8ad`.
- PR #19 remains draft/open and must not be merged or promoted while either hard blocker below remains.
- Exact-candidate release CI run `33936239839` completed successfully at head SHA `4733a9b3e7286b58828750542c7ad54057cfb8ad`.
- All four required regression contexts were green:
  - `regression (ubuntu-latest, py3.10)`
  - `regression (ubuntu-latest, py3.11)`
  - `regression (windows-latest, py3.10)`
  - `regression (windows-latest, py3.11)`

## Production state pinned read-only

- Production branch: `cbi-v6-cloud-runtime-20260901@a311a2a57ee43a1f1a3b2819bf28946566b05692`.
- Current Render live deploy remains on the same production SHA.
- Production object-store archive format is `object_state_v2`.
- Current production generation observed repeatedly: `669`.
- C279 is located without publishing its raw investigation id by commitment:
  `SHA256(investigation_id|last_safe_seq|last_safe_event_hash) = 4881a1e3ab093e48a22ef990c26a871445aaddf24074ab38300f863e62d09165`.
- Read-only production MCP probes uniquely matched that commitment.
- Current pre-forward-port C279 semantics remain:
  - outreach readiness: `IDENTITY_ONLY`
  - blocker: `VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED`
  - canonical route count: `0`
  - valid company-route observation count: `0`
  - valid information-route count: `0`
- Latest post-diagnostic production MCP probe: run `33940077267`, job `101235628926`, success.
- That probe verified generation stayed at `669`, recovery fingerprint stayed stable, no mutating tool was called, and no private raw or secret value was printed.

## Exhausted non-mutating runtime-root access paths

### Existing GitHub Actions R2 credentials

The existing `CBI_V63_R2_*` acceptance credential set was tested with a GET-only AWS SigV4 request against the actual production pointer `cbi-v61-production/cbi-v61/current.json`.

- Run: `33939252095`.
- Result: HTTP `403`.
- `PRODUCTION_R2_POINTER_READABLE_WITH_EXISTING_ACCEPTANCE_CREDENTIAL=false`.
- No write method was used.

Conclusion: the existing acceptance R2 credential set does not authorize production object-store reads.

### Anonymous production R2 GET

A no-Authorization GET-only probe was run against the same production pointer.

- Final classification run: `33940077328`, job `101235629241`, success.
- HTTP status: `400`.
- R2 error code: `InvalidArgument`.
- Error class: `AUTH_REQUIRED`.
- Object body was not printed.
- Authorization header used: false.
- Write method used: false.

Conclusion: production R2 object bytes are not anonymously readable.

### Production MCP surface

A `tools/list` schema-only probe found 65 production MCP tools. The available state/history/portfolio/journal/health surfaces do not expose a raw runtime-root export, object-store archive download, snapshot download, backup download, or restore-byte interface.

Conclusion: production MCP can prove semantic state but cannot supply the authoritative filesystem bytes required by the full-runtime isolated verifier.

### Production HTTP transport

Source inspection confirms the remote transport only exposes read GET health/readiness endpoints; `/mcp` GET is not a runtime bundle download route and there is no hidden raw-root export endpoint in the production transport.

### Render control plane

The production Render service is bound to the production branch/SHA and holds object-store configuration at runtime. The currently connected Render control plane does not expose a read action for secret environment-variable values and does not expose shell/SSH execution. Available environment actions are mutation actions and were not used.

### GitHub secret availability

Presence-only probes found no separate production object-store credential, Render API credential, Render SSH key, or private C279 bridge under the tested production-oriented secret names. Secret values were never printed.

## Authoritative restore contract

The repository object-store recovery implementation defines the authoritative restore chain as:

`current.json -> archive_key -> archive SHA verification -> object_state_v2 extraction -> sessions/recovery fingerprint validation`.

Once authenticated read access to the production pointer/archive or authorized read-only production filesystem access is available, the required C279 verifier can restore/copy the exact current-cloud root into a temporary isolated root and execute candidate semantics without mutating production.

## Hard blockers

### 1. C279 current-cloud isolated full-runtime proof

Status: `BLOCKED_EXTERNAL / AUTHORITATIVE_SOURCE_RUNTIME_ROOT_UNAVAILABLE`.

Required unblock is exactly one of:

1. authenticated read-only access to the current production R2 pointer/archive bytes; or
2. authorized read-only Render shell/SSH/filesystem access sufficient to copy the current runtime root; or
3. explicit owner approval for a production mutation that creates a temporary, tightly scoped read-only export channel.

Option 3 is a production mutation and must not be performed without explicit approval.

After the root is available, run `tests.test_v64_c279_full_runtime.V64C279FullRuntimeRegression.test_c279_canonical_route_can_prepare_outreach_full_runtime` against an isolated copy, bind the durable tail, prove candidate readiness reaches at least company-route-ready, call `prepare_outreach` only on the isolated copy, and prove `sends_message=false`.

### 2. Production governance ruleset

Status: `BLOCKED_EXTERNAL / PRODUCTION_RULESET_MISSING`.

Fresh repository ruleset inspection shows only active ruleset `protect-main` (id `21810779`). Production branch `cbi-v6-cloud-runtime-20260901` remains unprotected and `protect-cbi-production` is absent.

The connected GitHub application exposes ruleset reads but not administration writes. Do not mutate `protect-main` as a substitute.

## Safety / mutation statement

During this evidence cycle:

- production branch was not updated;
- PR #19 was not merged or marked ready;
- no Render deploy was triggered;
- no Render environment variable was changed;
- no production R2 object was written or deleted;
- no live CBI/CRM/runtime state mutation tool was called;
- no production credential value or raw runtime archive was printed or committed.

## Exact next execution point

1. Revalidate candidate head remains `4733a9b3e7286b58828750542c7ad54057cfb8ad` and release CI run `33936239839` remains the exact-head green evidence.
2. Revalidate production branch/live deploy remains `a311a2a57ee43a1f1a3b2819bf28946566b05692`.
3. If a new read-only production R2 or Render filesystem authorization becomes available, immediately restore/copy generation 669 and run the isolated C279 full-runtime verifier.
4. If GitHub administration capability becomes available, create and verify `protect-cbi-production` with the required release controls and four exact regression contexts.
5. Only after both hard blockers are green may PR #19 move out of draft and promotion proceed.
