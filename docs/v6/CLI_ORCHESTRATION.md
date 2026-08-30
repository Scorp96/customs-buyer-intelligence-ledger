# CBI v6.1 Git-controlled CLI orchestration

## Purpose

`Git`/GitHub controls the reviewed CBI source version. Python and the CBI v6.1
MCP/Runtime execute the code. A Git checkout is therefore a reproducible entry
point into the Buyer Intelligence engine, but Git itself is not a research
provider and GitHub Actions is not the public-web research host.

The operator CLI is:

```text
scripts/cbi.py
```

It supports customs-input orchestration in addition to the existing Runtime
operator commands.

## Security and persistence boundary

The customs commands are intentionally fail-closed:

- `lookup` is read-only and never creates Runtime state.
- `audit-file` / `audit` is read-only unless `--commit` is supplied.
- `batch-audit` is read-only unless `--commit` is supplied.
- committed mutations go through `mcp/server_v61_backup_recovery.py --stdio`,
  so v6.1 mutation WAL/idempotency and automatic backup guards remain in force.
- an optional `--requested-account-id` on a single audit becomes an exact
  Canonical identity constraint during commit; it is never a fuzzy suggestion.
- committed customs input starts only as `D1_USER_SUPPLIED_UNVERIFIED` Evidence.
- the complete raw input is retained alongside a canonical normalized view.
- unknown/unclassified raw fields are not discarded.
- a customs row never proves Ultimate Buyer, legal entity, repeat demand,
  annual volume, product specifications, channel capability, decision authority
  or final Commercial Value by itself.
- no CRM writeback or outreach send is performed by these commands.

On Windows, the CLI uses the production V6 sessions root when
`CBI_SESSION_ROOT` is not explicitly set:

```text
%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligenceV6\sessions
```

On hosts where that root cannot be discovered, a mutating audit requires
`--session-root` or `CBI_SESSION_ROOT`. Read-only preview/lookup does not require
a Runtime root.

## Host boundary

The v6.1 Runtime is a governance/evidence engine. It intentionally performs no
public-web research and has no authority to invent browser/registry/maps/provider
results. Public research is executed by a Host with real web/search/browser,
registry, maps or separately authorized provider tools.

A committed CLI audit therefore performs only the durable bootstrap:

```text
customs JSON
  -> preserve exact raw JSON
  -> normalize known fields
  -> resolve buyer-country routing signal conservatively
  -> apply optional exact requested Account ID constraint
  -> canonical account resolution
  -> start/reuse EXHAUSTIVE Investigation
  -> compile D1 user customs Evidence
  -> calculate initial state
  -> emit EIV-ranked next objectives
  -> emit Host resume instruction
```

The Host resumes the returned Investigation and executes those objectives using
real public sources until Decision Saturation or a truthful
`PAUSED_RESOURCE_LIMIT`.

## Input format

One record is one JSON object. English and common Chinese customs labels are
accepted, including nested sections such as `基本信息`, `产品信息`, `货运信息` and
`其它信息`.

Synthetic example:

```json
{
  "数据源": "美国(进口)",
  "日期": "2026-08-17",
  "主单号": "SYNTH-MBL-001",
  "分单号": "SYNTH-HBL-001",
  "供应商": "Synthetic Export Supplier Ltd",
  "采购商": "Synthetic Import Buyer LLC",
  "采购商地址": "1111 Example Dr San Bruno, CA 94066",
  "数量": "16 PKG",
  "重量（kg）": 23820,
  "TEU": 2,
  "产品": "Synthetic PVC Foam Sheet",
  "Bill Type": "House Bill",
  "opaque_source_field": "Synthetic Marker"
}
```

Do not store real customer/customs input files in this public repository. Keep
production inputs outside the repository or in a local ignored/private path.

## Buyer-country resolution

Canonical identity needs a country routing value, but many raw customs exports
do not contain a dedicated `buyer_country` field. Country resolution is therefore
explicit and inspectable instead of silently guessed.

Resolution order:

1. explicit `buyer_country` / `country` / `采购商国家`;
2. explicit United States destination (`destination` / `目的地`);
3. conservative US-import inference only when **both** conditions hold:
   - the normalized data source is a recognized US-import source such as
     `美国(进口)` / `美国进口数据` / `US import`;
   - `buyer_address` contains a 5-digit postal signal (optionally ZIP+4).

The third path returns:

```json
{
  "country": "United States",
  "basis": "US_IMPORT_SOURCE_PLUS_POSTAL_SIGNAL",
  "inferred": true
}
```

If neither explicit country/destination nor the paired US-import + postal signal
is available, normalization fails closed. A US-import label alone is not enough.

The preview/lookup/bootstrap output includes `buyer_country_resolution` so an
operator can see whether country was explicit or inferred. An inferred country
is an identity-routing hint only; it is not independent legal-entity proof and
must be verified by later public research.

This rule is designed for real US customs rows that include an import-data label
and US buyer address but omit a dedicated country column, without weakening the
canonical identity boundary.

## Raw-input retention and canonical normalization

Information retention comes before classification. The CLI maintains two views:

```text
raw_customs_record
normalized_customs_record
```

The raw view preserves the complete decoded JSON object, including fields the
current normalizer does not understand. The normalized view maps known labels to
stable keys used for identity resolution, Evidence claims and automation.

Examples of normalized metadata include:

```text
data_source
update_date
run_date
vessel_country
hidden
bill_type
manifest_number
record_status
conveyance
place_of_receipt
notify_address
```

Unknown fields remain in `raw_customs_record`. The input SHA-256 is computed from
the complete raw object, not the normalized subset.

For committed audits, raw + normalized views and `buyer_country_resolution` are
preserved in the Investigation start input and the durable
`trade.import_activity.value.customs_record`.

The Evidence source accepts the full proof at compile time, but the v6.1
Evidence Compiler deliberately canonicalizes source proof into bounded fields:

```text
content_sha256
raw_excerpt
raw_content_retained=false
```

It does not duplicate full `source.raw_content` indefinitely. Full raw customs
content remains durable in the Evidence value and Investigation start input.

Raw preservation and country derivation do **not** increase Evidence authority.

## `lookup`: ANSWER_FIRST Host handoff

```powershell
python scripts/cbi.py lookup C:\PrivateInputs\buyer.json
```

This command:

- validates and normalizes the customs record;
- preserves the exact raw JSON object;
- resolves/discloses the buyer-country routing basis;
- computes the stable raw-input SHA-256;
- emits a `cbi.cli-host-handoff.v1` request;
- tells the Host to run `$investigate-customs-buyers` in `ANSWER_FIRST` mode;
- performs no Runtime mutation.

The Host must independently verify company/entity, Ultimate Buyer, country,
product/trade context, current contacts and routes with concrete public sources.

## `audit-file`: FULL_AUDIT preview

Preview is the default:

```powershell
python scripts/cbi.py audit-file C:\PrivateInputs\buyer.json
```

or:

```powershell
python scripts/cbi.py audit C:\PrivateInputs\buyer.json
```

When an already-reviewed Canonical C-number is known, it can be carried through
preview without mutation:

```powershell
python scripts/cbi.py audit-file `
  C:\PrivateInputs\buyer.json `
  --requested-account-id C157
```

Preview shows at least:

```text
candidate
requested_account_id
buyer_country_resolution
customs_input_sha256
raw_input_preserved
raw_flattened_field_count
normalized_field_count
raw_customs_record
normalized_customs_record
proposed_initial_claims
runtime_mutation_performed=false
```

In preview, `requested_account_id` is display-only. The command does not resolve,
allocate or bind that ID. Use `scripts/cbi_canonical_preflight.py` for the
byte-read-only Runtime identity check.

No canonical account, Investigation, Evidence, Pivot, Peer, CRM or outreach
state is written.

## `audit-file --commit`: durable FULL_AUDIT bootstrap

Only explicit `--commit` may persist state:

```powershell
python scripts/cbi.py audit-file C:\PrivateInputs\buyer.json --priority-grade A --commit
```

For an existing reviewed customer, bind the exact intended Canonical ID:

```powershell
python scripts/cbi.py audit-file `
  C:\PrivateInputs\buyer.json `
  --requested-account-id C157 `
  --priority-grade A `
  --commit
```

`--requested-account-id` is a **hard identity constraint** on single-record
`audit-file` / `audit` only. During commit:

- the ID is validated before the production MCP client is started;
- it is included in the `resolve_or_create_account` request;
- it is included in resolver idempotency material, so a later change of requested
  identity cannot silently replay an earlier automatic resolution;
- if the requested ID collides with another existing Canonical identity, the
  resolver returns ambiguity and the CLI blocks before `start_investigation`;
- if a resolver ever returns a different Account ID than the requested one, the
  CLI performs a second fail-closed check and blocks;
- the requested ID is retained in the Investigation start input for provenance;
- successful output exposes both `requested_account_id` and resolved `account_id`.

A requested ID does not override country/tax/strong-identity conflicts. It is an
identity constraint, not permission to force a merge.

`--priority-grade` is a research-budget priority, not the buyer's Commercial
Value grade. Commercial Value remains Evidence-derived.

Optional controls:

```text
--objective-limit N
--priority-grade A+|A|A-|B+|B|B-|C|D|NQ
--budget-units FLOAT
--requested-account-id ACCOUNT_ID   # single audit only
--session-root PATH
```

A successful bootstrap returns at least:

```text
requested_account_id
account_id
investigation_id
account_resolution
investigation_start
buyer_country_resolution
customs_input_sha256
raw_input_preserved
customs_evidence_compilation
initial_commercial_value
initial_research_confidence
decision_saturation
investigation_health
next_research_objectives
host_instruction
```

If `buyer_country_resolution.inferred=true`, the Host instruction explicitly
requires independent verification before treating legal country as confirmed.

## Initial customs Evidence semantics

The bootstrap may initially create only these observations when applicable:

```text
trade.import_activity
relationship.supply_chain
```

Both use:

```text
reference_type = USER_INPUT
authority_level = D1_USER_SUPPLIED_UNVERIFIED
```

The product description remains inside the customs record, but the bootstrap
does not mark `product.fit` as proven. It also does not mark
`identity.ultimate_buyer` or `identity.legal_entity` as proven merely because a
name/address appeared in a customs row.

Verification belongs to later public-source objectives.

## Idempotency

Resolver idempotency material is derived from both:

```text
canonical candidate
requested_account_id (or empty when automatic)
```

Investigation/bundle idempotency remains bound to the resolved Account and raw
customs input hash. Re-running the same committed input with the same identity
constraint should reconcile/replay the same account/start/bundle through
production WAL rather than duplicate Evidence or spawn parallel Investigations.

Changing a requested Account ID changes resolver idempotency material instead of
replaying the previous resolution under a different identity intent.

A materially different raw input receives a different input hash and can be
appended under normal Runtime identity/reuse rules.

## `batch-audit`

Input is a non-empty JSON array.

Read-only preview:

```powershell
python scripts/cbi.py batch-audit C:\PrivateInputs\buyers.json
```

Explicit durable bootstrap:

```powershell
python scripts/cbi.py batch-audit C:\PrivateInputs\buyers.json --priority-grade A --commit
```

Each record independently applies the same country-resolution and raw-retention
contract. Batch mode intentionally does **not** expose one shared
`--requested-account-id`; applying one C-number to an array would create a
cross-record misbinding risk. Known existing IDs must be handled per record or by
a future explicitly mapped batch identity manifest.

Batch mode does not perform CRM writeback and does not mean research is complete.

## Existing operator commands

```text
status <investigation_id>
resume <investigation_id>
claims <investigation_id>
pivots <investigation_id>
peers <investigation_id>
health [--investigation-id ID]
pending [--limit N]
verify [--investigation-id ID]
backup [--reason TEXT|--daily]
backups
migrate ...
restore ...
```

## GitHub Actions boundary

Do not paste private customs/customer records into public workflow inputs or
commit them as repository fixtures.

CI validates orchestration with synthetic data only. It can test normalization,
country-resolution boundaries, raw retention, preview behavior, exact requested
Account binding, identity-collision blocking, WAL-backed bootstrap, idempotency
and privacy. GitHub Actions is not the production public-web research agent.

## Recommended real-customer procedure

1. keep customs JSON in a private local path outside the public repo;
2. sync the reviewed CLI code locally;
3. run `audit-file` without `--commit`, carrying a known C-number with
   `--requested-account-id` when applicable;
4. inspect the exact raw object, normalized view, candidate,
   `buyer_country_resolution` and requested ID;
5. run `scripts/cbi_canonical_preflight.py`, supplying the same known C-number;
6. reconcile any Runtime/CRM identity mismatch before commit; Runtime `NOT_FOUND`
   does not prove an external CRM has no customer;
7. if country is inferred, confirm the routing inference is reasonable;
8. explicitly run `audit-file ... --requested-account-id ... --commit` only after
   identity/preview review;
9. confirm returned `account_id` equals the intended requested ID;
10. retain the returned `investigation_id`;
11. give the Host instruction to a Host with `$investigate-customs-buyers` and
    real public web tools;
12. do not claim exhaustive completion until Runtime Decision Saturation passes.
