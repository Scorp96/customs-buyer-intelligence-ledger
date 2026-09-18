# Cloud-first customs history and monitoring

## Product intent

Git and the local CLI are development, release, diagnostics and recovery surfaces. They are **not** the normal end-user operating path for customs monitoring.

When the user asks to keep watching a Buyer, supplier, product, bill-of-lading pattern or customs stream, the normal product behavior is Host/cloud execution:

1. complete an initial historical customs backfill from the public/search/provider surfaces actually available to the Host;
2. normalize and deduplicate the known shipment history;
3. establish a monitoring baseline using immutable shipment identifiers when available;
4. schedule a cloud condition watch appropriate to the source update cadence;
5. search again on future runs without requiring the user's Windows machine to be online;
6. notify the user only when genuinely new records or materially changed shipment facts are found.

Do not ask the user to run PowerShell, CMD, Git, Python or a local MCP server merely to receive ongoing customs updates.

## Historical backfill

For a tracked Buyer, search both the Buyer identity and relevant supplier/shipper pages. Build the history from the strongest available identifiers:

- Master BOL;
- House BOL;
- container number;
- shipment/arrival date;
- buyer/consignee/notify identity;
- supplier/shipper identity;
- commodity description;
- weight and quantity;
- origin/foreign port and U.S. destination port;
- carrier/vessel/voyage when available.

A current importer summary count is useful for coverage, but it is not a substitute for individual shipment facts. Preserve source URLs and observed/crawled dates.

Deduplicate obvious duplicates before treating the history as a monitoring baseline. A duplicate copy of the same BOL is not a new shipment.

## New-record fingerprint

Prefer exact BOL/container identifiers. When those are unavailable, use a conservative composite fingerprint from:

`buyer + supplier + shipment/arrival date + commodity + weight + quantity + ports`

A changed run date, crawl date, formatting difference or duplicated manifest presentation is not itself a new shipment.

If a source later adds a missing field to an already-known shipment, report it only when the added field materially changes commercial interpretation or shipment identity.

## Cloud watch behavior

Use a condition-style recurring watch rather than requiring a local process. Customs/public manifest sources usually do not need sub-hour polling; daily checking is a reasonable default unless the user requests another cadence.

On each watch run:

1. search current Buyer and supplier-side sources;
2. compare against the stored/declared baseline;
3. identify unseen shipment fingerprints;
4. verify the Buyer/entity relationship before promotion;
5. notify only when at least one genuinely new shipment or material correction is found;
6. otherwise send no notification.

A notification should include, when available:

- shipment/arrival date;
- buyer role;
- supplier;
- commodity/product;
- weight/quantity;
- origin and destination ports;
- Master/House BOL;
- container;
- source links;
- whether the new record strengthens, weakens or does not change the commercial assessment.

## Interaction with CBI modes

`ANSWER_FIRST`: the Host may search current customs/public sources and answer immediately. No Runtime persistence is implied.

`FULL_AUDIT`: perform the historical backfill and all required entity/product/trade/evidence work. A valid historical backfill can become the baseline for later monitoring.

`WATCH_NEW_CUSTOMS`: monitoring is an ongoing Host/cloud task after a baseline exists. It is not a claim that the Runtime itself performs web search. The Host performs the searches using tools actually available on each scheduled run.

A watch does not require CRM writeback. New shipment findings may be presented to the user first; persistence/CRM sync remains a separate explicit action unless the user has explicitly authorized automatic persistence for that workflow.

## Local CLI boundary

`scripts/cbi.py`, `scripts/cbi_canonical_preflight.py`, local production roots and local MCP servers remain useful for engineering, explicit production bootstraps, diagnostics, migrations, recovery and acceptance testing.

They must not be presented as prerequisites for ordinary cloud customs monitoring or new-record notifications.
