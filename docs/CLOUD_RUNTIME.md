# CBI v6.1 Always-On Cloud Runtime

## Goal

Move the accepted CBI v6.1 durable Runtime off the Windows workstation so the
workstation may be powered off while the MCP backend remains available.

This migration changes **transport and hosting only**. It does not change the
accepted buyer-intelligence semantics, Commercial Value logic, Evidence rules,
Peer lifecycle, append-only history, or backup/recovery guards.

## Architecture

```text
ChatGPT / supported MCP client
        |
        |  remote MCP
        v
Secure MCP Tunnel (preferred)
        |
        |  loopback HTTP
        v
mcp/server_v61_remote.py
        |
        |  same production handler stack
        v
mcp/server_v61_backup_recovery.py
        |
        v
CBI_SESSION_ROOT=/var/lib/cbi/sessions
        |
        +-- append-only investigations
        +-- .runtime/canonical
        +-- .runtime/pending
        +-- .runtime/host-pending-v6

CBI_BACKUP_ROOT=/var/lib/cbi/backups-v61
```

The remote endpoint is stateless at the MCP transport layer. Durable CBI state
remains on disk in the mounted data volume. This is deliberate: transport
sessions are not business state.

## Protocol compatibility

`mcp/server_v61_remote.py` serves one `/mcp` endpoint and supports:

- MCP `2026-07-28` stateless requests and `server/discover`;
- legacy initialize-capable clients (`2025-11-25` / `2025-06-18` style);
- direct JSON responses for normal tool/resource calls;
- no long-lived MCP session ID;
- no unsolicited server-to-client messages.

The CBI tool surface is request/response and does not require sampling, roots,
or unsolicited notifications.

## Security posture

The cloud process refuses to start unless `CBI_SESSION_ROOT` is an explicit,
absolute, writable path.

Remote transport defaults to fail-closed bearer authentication:

```text
CBI_REMOTE_AUTH_MODE=bearer
CBI_REMOTE_BEARER_TOKEN=<at least 32 random characters>
```

For a public internet deployment, do **not** switch auth to `none` unless a
trusted upstream authentication layer is enforcing access. Prefer Secure MCP
Tunnel because it avoids exposing the MCP endpoint publicly.

The Docker service:

- runs as non-root uid/gid `10001`;
- drops Linux capabilities;
- uses `no-new-privileges`;
- runs with a read-only container filesystem;
- mounts only `/var/lib/cbi` writable;
- binds its host port to `127.0.0.1` by default.

## Recommended cloud host

A small always-on Linux VM is sufficient for the current single-user workload.
For AWS, Ubuntu 24.04 LTS with an encrypted EBS volume is a straightforward
choice. Keep the CBI data volume private and backed up.

If Secure MCP Tunnel is used, the VM does not need inbound 80/443. Restrict SSH
to the administrator's source IP and allow required outbound HTTPS.

If the optional Caddy public-HTTPS profile is used, point a controlled DNS name
at the VM and allow inbound 80/443. Authentication remains mandatory.

## Phase 1 — prepare the cloud VM

Install Git and Docker Engine / Docker Compose using the distribution-supported
or Docker-supported procedure, then clone this repository and checkout the cloud
branch or the later merged main branch.

Create the durable host directory:

```bash
sudo mkdir -p /srv/cbi-data
sudo chown 10001:10001 /srv/cbi-data
```

Create a deployment environment file from the committed template:

```bash
cp deploy/cloud/.env.example deploy/cloud/.env
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Put the generated value into `CBI_REMOTE_BEARER_TOKEN`. Never commit
`deploy/cloud/.env`.

## Phase 2 — one-time validated export from Windows

The old workstation must be powered on for this **one migration step only**.
Run from the accepted repository checkout:

```powershell
python scripts\export_cloud_runtime_bundle.py
```

The exporter does not tar the live mutable tree directly. It:

1. binds the real production session root explicitly;
2. creates a normal `ProductionBackupRecoveryManager` snapshot;
3. validates that snapshot;
4. restores it into an isolated activation-ready session root without replaying
   later live writes;
5. hashes every exported payload file;
6. creates `CBI_Cloud_Runtime_Export_<UTC>.tar.gz`.

The archive contains private durable buyer intelligence. **Never upload it to
GitHub, chat, email, or a public file host.** Transfer it directly to the
controlled cloud VM (for example with SCP/SFTP over an authenticated SSH
connection).

Record the SHA-256 printed by the exporter and compare it after transfer.

## Phase 3 — fail-closed import on the cloud VM

From the repository checkout on the VM:

```bash
python3 scripts/import_cloud_runtime_bundle.py \
  /path/to/CBI_Cloud_Runtime_Export_<UTC>.tar.gz \
  --target-root /srv/cbi-data
```

The importer rejects:

- path traversal;
- symbolic/hard links;
- devices/FIFOs;
- non-empty destination roots;
- missing or extra payload files;
- any file hash mismatch;
- a bundle not marked hash-chain-valid and activation-ready.

After activation it imports the real production backup/recovery stack against
`/srv/cbi-data/sessions` to verify the Runtime binds the imported root and that
Runtime health can be read.

Then normalize ownership:

```bash
sudo chown -R 10001:10001 /srv/cbi-data
```

## Phase 4 — start the always-on service

```bash
docker compose \
  --env-file deploy/cloud/.env \
  -f deploy/cloud/docker-compose.yml \
  up -d --build cbi
```

Check:

```bash
docker compose \
  --env-file deploy/cloud/.env \
  -f deploy/cloud/docker-compose.yml \
  ps

curl -sS http://127.0.0.1:8787/healthz
```

Expected health shape:

```json
{
  "status": "ok",
  "service": "customs-buyer-intelligence",
  "transport": "streamable-http-stateless",
  "durable_root_bound": true,
  "backup_recovery_enabled": true
}
```

## Phase 5A — preferred ChatGPT connection: Secure MCP Tunnel

Use the Secure MCP Tunnel workflow exposed by the supported OpenAI product and
run the tunnel on the **always-on cloud VM**, not on the Windows workstation.
Point the tunnel at:

```text
http://127.0.0.1:8787/mcp
```

This is the preferred design because the CBI server stays loopback/private and
the workstation is no longer part of the availability chain.

Do not invent tunnel CLI commands from this repository; use the current OpenAI
product instructions shown when the tunnel is provisioned because the tunnel
product and enrollment syntax may change independently of CBI.

## Phase 5B — optional public HTTPS endpoint

Only use this when the client/authentication arrangement requires a normal HTTPS
URL and you control a DNS name.

Set `CBI_MCP_DOMAIN` in `deploy/cloud/.env`, point DNS at the VM, and run:

```bash
docker compose \
  --env-file deploy/cloud/.env \
  -f deploy/cloud/docker-compose.yml \
  --profile public-https \
  up -d --build
```

The endpoint becomes:

```text
https://<CBI_MCP_DOMAIN>/mcp
```

Caddy handles TLS. The CBI server still requires its configured authentication.
Do not expose an unauthenticated write-capable MCP endpoint to the public
internet.

## MCP protocol probe

For an operator-side bearer-auth test:

```bash
TOKEN='<same token as deploy/cloud/.env>'
curl -sS http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  -H "Authorization: Bearer ${TOKEN}" \
  --data '{"jsonrpc":"2.0","id":"discover-1","method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

The response must advertise tools/resources and `supportedVersions` containing
`2026-07-28`.

## Cutover rule

Do not let Windows and cloud both accept durable write traffic after cutover.
Once cloud import and remote MCP validation pass:

1. mark cloud as authoritative;
2. leave the Windows production root read-only/rollback-only;
3. keep the previous Candidate, rollback root, and external activation backups;
4. do not merge new Windows writes into cloud by directory copy.

If a write accidentally occurs on both sides, treat it as a split-brain event and
use lineage/reconciliation logic rather than overwriting either event chain.

## Rollback rule

Cloud migration does not delete or rewrite the old Windows Runtime. If the cloud
cutover fails before new cloud writes occur, reconnect the old known-good path.
If the cloud Runtime has accepted new durable writes, rollback requires explicit
reconciliation; never overwrite those writes with an older directory snapshot.

## What this change does not do

- It does not make ChatGPT product-plan features available where the product does
  not currently expose them.
- It does not make mobile clients support custom MCP apps if the current ChatGPT
  client does not support them.
- It does not move private state through GitHub.
- It does not change CBI scoring, Evidence, Peer, Closure, CRM, or outreach rules.
