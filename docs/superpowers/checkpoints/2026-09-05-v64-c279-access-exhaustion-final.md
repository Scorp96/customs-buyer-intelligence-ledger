# CBI v6.4 C279 Current-Cloud Access Exhaustion — Final Read-Only Addendum

Date: 2026-09-05

## Purpose

This addendum records the final non-mutating access checks performed after the earlier C279 current-cloud checkpoint. It intentionally contains no production credential values, no raw C279 investigation identifier, and no runtime archive contents.

## Fresh production invariant proof

A fresh read-only production MCP probe ran after the final access-path checks:

- workflow run: `33942814266`
- job: `101243365731`
- production SHA remained `a311a2a57ee43a1f1a3b2819bf28946566b05692`
- C279 commitment matched exactly one production investigation
- outreach readiness remained `IDENTITY_ONLY`
- blocker remained `VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED`
- canonical route count remained `0`
- valid company-route observation count remained `0`
- valid information-route count remained `0`
- object-store generation remained `669`
- recovery fingerprint remained stable
- mutating tool called: `false`
- private raw values printed: `false`
- secret value printed: `false`

This proves the diagnostic work did not change the authoritative production state.

## Exact production object-store secret-name probe

Source inspection of the production object-store manager confirmed the real runtime environment-variable names are exactly:

- `CBI_OBJECT_STORE_MODE`
- `CBI_OBJECT_STORE_ENDPOINT`
- `CBI_OBJECT_STORE_BUCKET`
- `CBI_OBJECT_STORE_ACCESS_KEY_ID`
- `CBI_OBJECT_STORE_SECRET_ACCESS_KEY`
- `CBI_OBJECT_STORE_REGION`
- `CBI_OBJECT_STORE_PREFIX`
- `CBI_OBJECT_STORE_RETENTION`

A presence-only GitHub Actions probe tested those exact names:

- commit: `91534913069e6e1c1bede778723ef4c4814fb981`
- workflow run: `33942814272`
- job: `101243365692`
- result: all eight exact names were `ABSENT`
- network calls performed: `false`
- secret values printed: `false`

Therefore the C279 blocker is not caused by previously probing only guessed production aliases.

## GitHub Actions / environment-scope findings

- Existing production/release workflows do not declare a GitHub Actions `environment:` binding.
- The existing R2 acceptance workflow maps only the isolated `CBI_V63_R2_*` secret set.
- Those acceptance credentials were already tested with a GET-only request against the production pointer and returned HTTP `403`.
- No second committed workflow mapping to a production object-store credential was found.

## Production MCP raw-state reconstruction path closed

The production v6 MCP tool surface exposes semantic projections such as health, claims, account state, investigation state, portfolio state, information history and journal state.

It does not expose a raw append-event stream, session JSONL download, runtime-root export, object-store archive download, snapshot download or backup-byte interface. Consequently the authoritative session cannot be reconstructed byte-for-byte from production MCP projections.

The HTTP transport also confirms that `/mcp` GET is disabled and that the remote transport does not implement an independent MCP resource-download surface such as `resources/list` or `resources/read`.

## Render control-plane path closed under current connection

Fresh Render service metadata confirms:

- service remains bound to `cbi-v6-cloud-runtime-20260901`
- runtime remains Docker in Singapore
- SSH address exists, but the connected Render tool surface exposes no shell/SSH execution action
- PR previews are disabled
- preview generation is off
- no reusable environment-group inheritance surface is exposed by the current connector
- environment-variable actions available to this conversation are mutation actions, not secret-value reads

No Render deploy, restart hook or environment mutation was triggered.

## GitHub Actions artifact bytes audited

The current-cloud C279 preflight artifact was downloaded and inspected directly:

- artifact id: `9960768288`
- ZIP SHA256: `44fe4e8fa1c72cb7bb3814cf4c1b2edd75e7b18a5871fddd34c2a4e5ac8e2042`
- ZIP entries: exactly one file, `CBI_V64_C279_CURRENT_CLOUD_PREFLIGHT.json`
- uncompressed JSON size: `1337` bytes
- contents are sanitized production SHA/generation/fingerprint/semantic-preflight metadata; no runtime root, session JSONL or archive payload exists in the artifact

Historical source-SHA exact-checkout live acceptance was also inspected:

- run `33760447567`
- artifact `9895310327`
- ZIP contains exactly four JSON acceptance/correlation/recovery-receipt files; no runtime archive or session JSONL

All four historical `cbi-v63-render-r2-pvc-acceptance` workflow-dispatch runs were enumerated. Their artifacts were either tiny failure-status files or isolated acceptance receipts. The two successful artifacts were inspected directly and used the isolated prefix `cbi-v63-acceptance-20260903-r01`, not production `cbi-v61`:

- run `33756309554`, artifact `9893653145`: generation `8`, isolated acceptance prefix, `production_ready=false`
- run `33753317687`, artifact `9892512260`: generation `0 -> 8`, isolated acceptance prefix, `production_ready=false`
- failed runs `33743183878` / `33735379824`: artifact sizes only `394` / `498` bytes

Therefore historical GitHub Actions artifacts do not contain an authoritative production generation-669 runtime archive.

## Library recovery path closed

Searches did not find:

- a saved generation-669 runtime archive
- a saved C279 session JSONL
- a saved `CBI_v64_runtime_readonly_minimal_*.zip`
- an SSH private-key file (`id_ed25519`, `id_rsa`, `.pem`) associated with the Render service
- a saved valid production R2 Access Key / Secret file

The historical Windows migration archive is documented only at the old local path `CBI_Cloud_Runtime_Export_20260901T011247Z.tar.gz`; it is the generation-0 migration baseline and cannot substitute for current-cloud generation 669.

Historical security records also state that an earlier exposed R2 token was revoked and replaced, and the current valid bucket-scoped token was stored only in Render Environment. The revoked token must not be recovered or reused.

## Plugin path closed

Plugin discovery returned no Cloudflare connector capable of reading the production R2 bucket under the current conversation's authorized connections.

## Minimum isolated C279 runtime input

The current generic C279 full-runtime test requires an authoritative source root containing at least:

- `sessions/<target-investigation>.jsonl`
- the corresponding runtime governance state under the explicit session root's `.runtime` hierarchy (including canonical/pending state as applicable)

A single semantic MCP state response or a copied final event is not sufficient to establish the required full-runtime proof.

## Final non-mutating conclusion

All currently available non-production-mutation access paths have been exhausted.

Status remains:

`BLOCKED_EXTERNAL / AUTHORITATIVE_SOURCE_RUNTIME_ROOT_UNAVAILABLE`

Accepted unlock paths remain exactly one of:

1. provision authenticated **read-only** access to the production R2 pointer/archive for `cbi-v61-production` / `cbi-v61/*`;
2. provision authorized **read-only** Render filesystem/SSH access sufficient to copy the authoritative current runtime state;
3. explicitly approve a narrowly scoped temporary production export/diagnostic channel. This is a production mutation and is not authorized by generic lifecycle-continuation instructions.

After either read-only path is supplied, immediately restore/copy the exact generation-669 state to an isolated temporary root, bind the private bridge durable tail to source JSONL, run the current integrated v6.4 full-runtime regression, call `prepare_outreach` only on the isolated copy, and prove `sends_message=false`.

## Production governance remains independent

The separate `protect-cbi-production` ruleset blocker remains unchanged. Do not treat C279 access resolution as a substitute for repository production governance.
