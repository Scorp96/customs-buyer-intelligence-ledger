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

It now supports customs-input orchestration in addition to the existing Runtime
operator commands.

## Security and persistence boundary

The new commands are intentionally fail-closed:

- `lookup` is read-only and never creates Runtime state.
- `audit-file` / `audit` is read-only unless `--commit` is supplied.
- `batch-audit` is read-only unless `--commit` is supplied.
- a committed audit does not call `UnifiedRuntime` directly for mutations;
  mutations go through `mcp/server_v61_backup_recovery.py --stdio`, so v6.1
  mutation WAL/idempotency and automatic backup guards remain in force.
- a committed audit initially persists only the user-provided customs record as
  `D1_USER_SUPPLIED_UNVERIFIED` Evidence.
- the initial customs row never proves Ultimate Buyer, repeat demand, annual
  volume, product specifications, warehouse/channel capability, decision
  authority or final Commercial Value.
- no CRM writeback or outreach send is performed by these commands.

On Windows, the CLI uses the same production V6 sessions root as the MCP when
`CBI_SESSION_ROOT` is not explicitly set:

```text
%LOCALAPPDATA%\XingHuai\CustomsBuyerIntelligenceV6\sessions
```

On hosts where this root cannot be discovered, a mutating audit requires
`--session-root` or `CBI_SESSION_ROOT` explicitly. Read-only preview/lookup does
not require a Runtime root.

## Why the CLI does not perform the whole Internet investigation

The v6.1 Runtime is a governance/evidence engine. It intentionally performs no
web search and has no authority to invent browser/registry/maps/provider
results. Public research is executed by a Host with real web/search/browser,
registry, maps or separately authorized provider tools.

Therefore a committed CLI audit performs the durable bootstrap:

```text
customs JSON
  -> canonical account resolution
  -> start/reuse EXHAUSTIVE Investigation
  -> compile D1 user customs Evidence
  -> calculate initial state
  -> emit EIV-ranked next objectives
  -> emit Host resume instruction
```

The Host then resumes the returned Investigation and executes those objectives
using real public sources until Decision Saturation or a truthful
`PAUSED_RESOURCE_LIMIT`.

## Input format

One record is a JSON object. English and common Chinese customs labels are
accepted, including nested sections such as `基本信息`, `产品信息`, `货运信息` and
`其它信息`.

Minimal example (synthetic):

```json
{
  "date": "2026-08-17",
  "master_bill": "SYNTH-MBL-001",
  "house_bill": "SYNTH-HBL-001",
  "supplier": "Synthetic Export Supplier Ltd",
  "buyer": "Synthetic Import Buyer LLC",
  "buyer_address": "100 Synthetic Buyer Avenue",
  "buyer_country": "United States",
  "product": "Synthetic PVC Foam Sheet",
  "quantity": "16 PKG",
  "weight_kg": 23820,
  "teu": 2,
  "destination": "United States"
}
```

The CLI requires a Buyer name and a Buyer country. If Buyer country is absent,
`United States` may be inferred only when the supplied destination explicitly
matches a supported United States spelling.

Do not store real customer/customs input files in this public repository. Keep
production inputs outside the repository or in a local ignored/private path.

## `lookup`: ANSWER_FIRST Host handoff

```powershell
python scripts/cbi.py lookup C:\PrivateInputs\buyer.json
```

This command:

- validates and normalizes the customs record;
- computes a stable input SHA-256;
- emits a `cbi.cli-host-handoff.v1` JSON request;
- tells the Host to run `$investigate-customs-buyers` in `ANSWER_FIRST` mode;
- performs no Runtime mutation.

The Host should verify company/entity, Ultimate Buyer, product/trade context,
contacts and routes with concrete public sources and produce the standard email
and instant-chat drafts. It must not silently convert the lookup into Runtime,
CRM, Closure or send state.

## `audit-file`: FULL_AUDIT preview

Preview is the default:

```powershell
python scripts/cbi.py audit-file C:\PrivateInputs\buyer.json
```

or:

```powershell
python scripts/cbi.py audit C:\PrivateInputs\buyer.json
```

The preview validates/normalizes the record and shows the initial claims that
would be compiled. It writes nothing.

## `audit-file --commit`: durable FULL_AUDIT bootstrap

Only an explicit `--commit` may persist state:

```powershell
python scripts/cbi.py audit-file C:\PrivateInputs\buyer.json --priority-grade A --commit
```

`--priority-grade` is a research-budget priority, not a buyer Commercial Value
grade. A new audit defaults to `A` research priority. The Runtime independently
calculates Commercial Value from verified Evidence.

Optional controls:

```text
--objective-limit N
--priority-grade A+|A|A-|B+|B|B-|C|D|NQ
--budget-units FLOAT
--session-root PATH
```

A successful bootstrap returns at least:

```text
account_id
investigation_id
account_resolution
investigation_start
customs_input_sha256
customs_evidence_compilation
initial_commercial_value
initial_research_confidence
decision_saturation
investigation_health
next_research_objectives
host_instruction
```

The Host instruction is the next execution boundary. It tells an authorized
Host to resume the exact Investigation in `FULL_AUDIT`, execute the EIV-ranked
research objectives with real public sources, compile Evidence, run all six
network branches for every Anchor, preserve conflicts and continue until
Decision Saturation or a truthful resource pause.

## Initial customs Evidence semantics

The bootstrap may initially create these observations when applicable:

```text
trade.import_activity
relationship.supply_chain
```

Both are sourced as:

```text
reference_type = USER_INPUT
authority_level = D1_USER_SUPPLIED_UNVERIFIED
```

The product description remains part of the customs record, but the bootstrap
does not mark `product.fit` as proven. Likewise it does not mark
`identity.ultimate_buyer` or `identity.legal_entity` as proven merely because a
name appeared in a customs row.

This is deliberate. Verification belongs to later public-source objectives.

## Idempotency

Stable request material is derived from the normalized candidate and original
input hash. Re-running the same committed input should therefore reconcile or
replay the same canonical account/start/bundle through the production WAL rather
than duplicating Evidence or spawning parallel Investigations.

A materially different customs input receives a different input hash and can be
appended to the same canonical account under normal Runtime identity/reuse
rules.

## `batch-audit`

Input is a non-empty JSON array of customs records.

Read-only preview:

```powershell
python scripts/cbi.py batch-audit C:\PrivateInputs\buyers.json
```

Explicit durable bootstrap:

```powershell
python scripts/cbi.py batch-audit C:\PrivateInputs\buyers.json --priority-grade A --commit
```

Batch mode bootstraps each record using the same safe single-record contract. It
does not perform CRM writeback and does not mean research is complete.

## Existing operator commands

The existing commands remain available:

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

CI should validate the orchestration with synthetic data only. GitHub Actions
can test normalization, preview behavior, WAL-backed bootstrap, idempotency and
privacy boundaries. It is not the production public-web research agent unless a
separate, explicitly authorized online research infrastructure is designed and
reviewed.

## Recommended real-customer procedure

1. keep the customs JSON in a private local path outside the public repo;
2. sync the reviewed CLI code locally;
3. run `audit-file` without `--commit` first;
4. inspect the normalized candidate/boundary;
5. explicitly run `audit-file ... --commit`;
6. retain the returned `investigation_id`;
7. give the returned Host instruction to a Host with `$investigate-customs-buyers`
   and real public web tools;
8. do not claim exhaustive completion until Runtime Decision Saturation passes.
