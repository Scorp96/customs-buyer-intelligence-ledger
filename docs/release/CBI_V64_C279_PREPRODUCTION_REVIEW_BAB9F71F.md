# CBI v6.4 C279 Pre-Production Review — bab9f71f

Status snapshot: 2026-09-05

## Decision state

- `CODE_VERIFIED=TRUE`
- `TASK_5_EXACT_SHA_GATE=GREEN`
- `PRODUCTION_READY=FALSE`
- `PRODUCTION_DIAGNOSTIC_DEPLOYMENT_APPROVED=FALSE`
- `CURRENT_CLOUD_C279_PROOF=UNPROVEN`
- `PRODUCTION_BRANCH_PROTECTED=FALSE`
- `PRODUCTION_MUTATION_PERFORMED=FALSE`

This checkpoint records the exact non-production code and external state reviewed before any production diagnostic deployment. It is not deployment authorization and must not be interpreted as approval to modify the production branch, Render environment variables, Render deployment state, or R2.

## Immutable code pins

- Verified diagnostic branch: `cbi-v64-release-candidate-c279-diagnostic-a311a2a5`
- Verified diagnostic code SHA: `bab9f71fc13faba8fda972b49deec098c59a69f2`
- Verified diagnostic tree: `635a7c61e74551cbc2ffbe827ec0bdf7cb68590e`
- Production branch: `cbi-v6-cloud-runtime-20260901`
- Production base SHA: `a311a2a57ee43a1f1a3b2819bf28946566b05692`
- Production is the merge base of the diagnostic branch; GitHub compare reports `ahead_by=23`, `behind_by=0`.

The review branch `cbi-v64-c279-preproduction-review-bab9f71f` was created directly from the verified diagnostic SHA. Review-document commits belong on this branch only so the verified code SHA remains frozen.

## Permanent Release CI evidence

Workflow: `CBI release candidate CI`

- Run: `33960212057`
- Exact head SHA: `bab9f71fc13faba8fda972b49deec098c59a69f2`
- Final run attempt: `2`
- Overall conclusion: `success`
- Ubuntu / Python 3.10: `success`
- Ubuntu / Python 3.11: `success`
- Windows / Python 3.10: `success`
- Windows / Python 3.11: `success`
- Ubuntu / Python 3.11 Docker build and real cloud Runtime smoke: `success`

Windows / Python 3.11 attempt-2 performance acceptance:

- `bundle_100_seconds=0.081052`, target `5.0`, PASS
- `state_query_seconds=0.214418`, target `0.5`, PASS
- `resume_seconds=0.551488`, target `3.0`, PASS

The first Windows / Python 3.11 attempt measured `state_query_seconds=0.686325` and failed only the fixed 0.5-second performance target. No code or threshold was changed. A rerun of only the failed job produced `0.214418` and the exact-SHA run became four-matrix GREEN. A prior same-environment GREEN run had measured `0.233531`; the first excursion is therefore treated as hosted-runner variance, not as a waived gate.

Permanent CI also reported the full unittest suite `OK`; the C279 crypto-dependent capture tests are intentionally covered by the dedicated crypto workflow below rather than silently assumed from the base matrix.

## Dedicated C279 crypto evidence

Workflow: `CBI v6.4 C279 diagnostic crypto CI`

- Run: `33960212038`
- Exact head SHA: `bab9f71fc13faba8fda972b49deec098c59a69f2`
- Run attempt: `1`
- Conclusion: `success`
- Pinned dependency: `cryptography==50.0.1`
- Verified wheel SHA256: `51afcfceb15597cf2635068e4ac9a56b2abde622edde17f37d85fd7b5306497a`
- C279 capture contract: `5/5 PASS`
- Privacy scan: PASS

Known non-blocking test warning: the dedicated capture test emitted a `ResourceWarning` associated with localhost test-socket cleanup. It did not fail the workflow and is recorded here rather than represented as a warning-free run.

## C279 security and data-boundary contract

The verified diagnostic implementation is designed for a narrowly bounded current-session proof path:

- one temporary internal C279 export path;
- static-admin bearer authorization only for that path, with no OAuth fallback;
- route disabled/fail-closed when required diagnostic configuration or bearer channel is absent or invalid;
- request-time expiry makes the diagnostic route unavailable after the configured window;
- snapshot exporter reads the already-bound session root and is designed as zero-write;
- no R2 export path is used for this diagnostic snapshot;
- capture client validates response schema, declared length, and SHA-256 before encryption;
- capture encryption uses X25519 key agreement, HKDF-SHA256, and ChaCha20-Poly1305;
- capture CLI obtains the bearer from environment, not from persisted configuration;
- the capture client persists ciphertext JSON only, not plaintext session data or bearer material;
- HTTP failures are sanitized before reporting.

These are code/test properties only. They do not substitute for a fresh current-cloud C279 proof after an explicitly approved diagnostic deployment.

## Production-to-diagnostic net diff scope

Fresh GitHub compare from `a311a2a57ee43a1f1a3b2819bf28946566b05692` to `bab9f71fc13faba8fda972b49deec098c59a69f2` reports exactly 13 net changed files:

1. `.github/workflows/cbi-release-ci.yml`
2. `.github/workflows/cbi-v64-c279-diagnostic-ci.yml`
3. `mcp/c279_single_session_export_v64.py`
4. `mcp/chatgpt_oauth_transport.py`
5. `mcp/remote_transport.py`
6. `mcp/server_v61_remote.py`
7. `requirements/cbi-v64-c279-capture.txt`
8. `scripts/capture_v64_c279_single_session.py`
9. `tests/test_v64_c279_capture.py`
10. `tests/test_v64_c279_export_entrypoint_contract.py`
11. `tests/test_v64_c279_export_transport.py`
12. `tests/test_v64_c279_single_session_export.py`
13. `tests/test_v64_c279_transport_main_forwarding.py`

Temporary apply/bootstrap workflows used during TDD are not present in the final net diff.

## Fresh production invariant snapshot

GitHub production branch:

- branch: `cbi-v6-cloud-runtime-20260901`
- SHA: `a311a2a57ee43a1f1a3b2819bf28946566b05692`
- `protected=false`
- required status-check enforcement: off

Repository rulesets:

- active rulesets returned: only `protect-main`
- no production-specific ruleset is present

Render production service:

- service: `cbi-v61-preview`
- service ID: `srv-dab38a3tqb8s73eljmtg`
- configured branch: `cbi-v6-cloud-runtime-20260901`
- auto-deploy trigger: `checksPass`
- current live deploy: `dep-dadbsl2jnfac73fa08sg`
- current live commit: `a311a2a57ee43a1f1a3b2819bf28946566b05692`

No diagnostic SHA appears as the live production deployment in this snapshot. No Render deploy, Render environment-variable update, R2 write, or production Git ref update was performed while creating this checkpoint.

## Remaining hard gates

`PRODUCTION_READY=FALSE` remains mandatory until all applicable release gates are separately proven. Current blockers include:

1. **Production branch governance** — the actual production branch remains unprotected and only `protect-main` exists. This connector can read rulesets but does not expose the required repository-administration write capability to create the missing production ruleset.
2. **Current-cloud C279 proof** — no diagnostic code has been deployed to the actual production service in this checkpoint, so a current-cloud single-session ciphertext capture and isolated verification have not yet been performed.
3. **Production diagnostic deployment approval** — explicit approval is still required before changing production service code/env/deployment state or otherwise exposing the temporary diagnostic route.
4. **Post-diagnostic cleanup and verification** — any approved temporary diagnostic enablement must be removed/expired and the production invariants reverified before release promotion can be considered.

## Next lifecycle transition

Current state:

`CODE_VERIFIED`
→ `PREPRODUCTION_REVIEW_CHECKPOINTED`
→ **STOP: PRODUCTION_DIAGNOSTIC_DEPLOYMENT_APPROVAL_REQUIRED**

Only after explicit approval should a separate execution window plan and execute the minimal, reversible diagnostic deployment, obtain current-cloud C279 evidence, verify ciphertext-only capture and no live mutation, then disable/expire the diagnostic path and re-audit production state.
