# CBI v6.1 on Render

This is the managed Git-connected deployment path for the accepted CBI v6.1
remote Runtime. It avoids coupling CBI availability to a Windows workstation or
a rotating VPN IP.

## Architecture

```text
GitHub branch / later main
        |
        | Render Blueprint + Docker build
        v
Render paid web service (Singapore)
        |
        +-- HTTPS /healthz
        +-- HTTPS /mcp (bearer protected)
        |
        v
/var/lib/cbi  <- Render persistent disk
        |
        +-- incoming/      temporary migration archive only
        +-- live/
             +-- export-manifest.json
             +-- sessions/
             +-- backups-v61/
```

The Blueprint is `render.yaml` at the repository root.

## Why the first deploy is bootstrap-only

A new empty Render disk must never silently become a second empty production
CBI Runtime. The Render Docker command starts `mcp/render_bootstrap.py`.

Before migration import:

```json
{"status":"bootstrap_required","durable_state_loaded":false,"mcp_enabled":false}
```

`POST /mcp` returns HTTP 503. No CBI durable writes are possible.

After a validated bundle is imported into `/var/lib/cbi/live`, restarting the
service causes the bootstrap gate to bind the accepted production Runtime to:

```text
CBI_SESSION_ROOT=/var/lib/cbi/live/sessions
CBI_BACKUP_ROOT=/var/lib/cbi/live/backups-v61
```

## Render service configuration

The committed Blueprint intentionally selects:

- Web service / Docker runtime
- Singapore region (Render currently has no Tokyo region)
- `1c-2g` paid compute
- 5 GB persistent disk mounted at `/var/lib/cbi`
- `/healthz` HTTP health check
- deploy-on-passing-checks policy
- bearer authentication

The bearer token is declared with `sync: false`. During initial Blueprint
creation, enter a strong secret of at least 32 characters. Never commit it.

## Create the Blueprint

1. Sign in to Render and connect the GitHub account that can access this repo.
2. Create a new Blueprint.
3. Select `Scorp96/customs-buyer-intelligence-ledger`.
4. While this change is still under acceptance, select branch
   `cbi-v6-cloud-runtime-20260901`.
5. Use the repository-root `render.yaml`.
6. When prompted for `CBI_REMOTE_BEARER_TOKEN`, paste a locally generated secret.
7. Create the Blueprint and wait for the deploy to become healthy.

Generate a token locally, for example:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Record the token in a password manager. Do not paste it into GitHub issues, PRs,
logs, or chat transcripts.

## Expected first-deploy health

The first deploy is successful when the Render health URL returns HTTP 200 with:

```json
{
  "status": "bootstrap_required",
  "service": "customs-buyer-intelligence",
  "durable_state_loaded": false,
  "mcp_enabled": false
}
```

This is not a production-ready state. It means the service and persistent disk
exist and are waiting for the validated migration bundle.

## Configure Render SSH

Use a dedicated SSH key for Render. Add the public key to the Render account.
The Docker image already gives the non-root `cbi` user a real shell and creates
`~/.ssh` with mode `0700`, as required by Render SSH for Docker services.

Render shows the exact SSH command under the service's **Connect > SSH** menu.
For Singapore it has this general shape:

```text
ssh <service-id>@ssh.singapore.render.com
```

Do not guess the service ID; copy the command from Render.

## Transfer the private migration bundle

The migration archive contains private durable buyer intelligence. Never upload
it to GitHub, a public file host, or a chat attachment.

1. In the running Render service shell:

```bash
mkdir -p /var/lib/cbi/incoming
```

2. From Windows, use the exact Render SCP destination shown for your service.
Render recommends SCP/SFTP for disk-backed services. The destination must be
under the mounted persistent disk, for example:

```powershell
scp -s "C:\path\to\CBI_Cloud_Runtime_Export_<UTC>.tar.gz" `
  <service-id>@ssh.singapore.render.com:/var/lib/cbi/incoming/
```

3. In the Render shell, hash the transferred archive:

```bash
sha256sum /var/lib/cbi/incoming/CBI_Cloud_Runtime_Export_<UTC>.tar.gz
```

It must exactly equal the SHA-256 printed by the Windows exporter. Stop if it
does not match.

## Fail-closed import

Run inside the real running Render service, not an ephemeral shell instance:

```bash
python scripts/import_cloud_runtime_bundle.py \
  /var/lib/cbi/incoming/CBI_Cloud_Runtime_Export_<UTC>.tar.gz \
  --target-root /var/lib/cbi/live \
  --expected-sha256 <EXACT_WINDOWS_EXPORTER_SHA256>
```

The importer has no health bypass. It rejects an untrusted archive hash,
path-traversal entries, duplicate members, links/devices, oversized archives,
payload inventory differences, payload hash mismatches, missing quiescence
proof, non-empty target roots, and non-activation-ready state.

After activation it binds the accepted production backup/recovery stack to the
imported root, checks Runtime health, creates `CLOUD_IMPORT_BASELINE`, and
validates that baseline snapshot.

Only a final `status: PASS` authorizes the next step.

After PASS, remove the temporary transfer copy:

```bash
rm -f /var/lib/cbi/incoming/CBI_Cloud_Runtime_Export_<UTC>.tar.gz
```

Do not remove `/var/lib/cbi/live` or its backups.

## Activate the cloud Runtime

Restart/redeploy the Render service after a successful import. The bootstrap
gate now sees the complete imported bundle and launches
`mcp/server_v61_remote.py`.

Expected `/healthz` shape:

```json
{
  "status": "ok",
  "service": "customs-buyer-intelligence",
  "transport": "streamable-http-stateless",
  "durable_root_bound": true,
  "backup_recovery_enabled": true
}
```

The MCP endpoint is:

```text
https://<render-service-subdomain>.onrender.com/mcp
```

It requires:

```text
Authorization: Bearer <CBI_REMOTE_BEARER_TOKEN>
```

## Cutover rule

After remote MCP validation succeeds:

1. Cloud becomes authoritative.
2. The old Windows production root stays rollback-only.
3. Do not resume normal durable writes on Windows.
4. Keep the old Candidate, rollback root, and activation backups.
5. If both Windows and cloud ever receive durable writes, treat it as a
   split-brain incident and reconcile event lineage. Never overwrite either
   side by directory copy.

## Render-specific operational boundaries

A persistent disk is attached to one service instance, so do not scale this
service horizontally. Disk-backed Render deploys have a short restart window
instead of zero-downtime replacement; this is acceptable for the current
single-user append-only Runtime and prevents two writers mounting the same disk.

Render automatically snapshots persistent disks daily, but CBI's own
`ProductionBackupRecoveryManager` remains the application-level backup and
lineage authority.

## ChatGPT product gate

Hosting CBI on Render removes the Windows-PC availability dependency. It does not
change ChatGPT plan/workspace eligibility. Configure the remote MCP app only in a
ChatGPT plan/workspace that currently supports the required custom MCP tool
surface and authentication mode.
