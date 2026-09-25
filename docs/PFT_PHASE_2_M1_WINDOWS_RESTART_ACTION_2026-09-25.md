# Phase 2 M1 — Windows restart and sign-in recovery action (prepared 2026-09-25)

**Status: owner-approved action executed and accepted; see the [dated recovery result](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md).** This was the final M1 recovery test for the accepted private iPhone Serve path. The only planned interruption was one normal Windows restart followed by sign-in to the existing owner account. No Docker image rebuild, container recreation, environment/policy edit, new endpoint, manual Plaid request, financial write, clock/cursor/schedule change, or M2 work was performed. A normally due jobs run or backup could have occurred on its own; none was artificially triggered.

## Known starting point and reason for the test

- At preparation time (2026-09-25 18:09 UTC), branch `main` was at `79bc3a8add6ff5a2aa0def0c70f383cf503c9184` with existing uncommitted M1 code/evidence. This packet changes documentation only. Windows Tailscale 1.102.4 reported its service **Running / Automatic**, backend Running, MagicDNS enabled, `pft-host.tailc4d964.ts.net` at `100.109.100.36` with node ID `3351434150137017`, and online `iphone-15-pro.tailc4d964.ts.net` at `100.99.41.95`. The only certificate domain was `pft-host.tailc4d964.ts.net`; the owner previously saw a valid certificate. The saved restrictive policy has one `pft-iphone` → `pft-windows` `tcp:443` grant, two tests, and no ACL/SSH/broad grant; its preserved JSON SHA-256 is `a13a5dfa372facd261255ea2e26e4270ed4ad0202604e9c602a54450081b0428`. Reconfirm the **console** policy before the restart; a local copy alone cannot establish current policy.
- Docker Desktop reported `running`; its saved `AutoStart` setting was `true`, and Windows `StartupApproved\Run` showed Docker Desktop enabled (`000000000000000000000000`). This matters because the first Phase 1 sign-in recovery failed when Docker autostart was disabled; a repeat sign-in then passed after the owner enabled both settings. All four `pft-runtime` containers currently have `unless-stopped`: DB `3b97f7733793` / image `sha256:c1b37833...`, API `f4799bf8162b` / `sha256:cec3537e...`, web `643d75993526` / `sha256:428dec07...`, jobs `4bc21502f34b` / `sha256:f3e3536c...`. DB/API/web are healthy and jobs is running. The old `personal-finance-tracker-db-production-backfill-1` is exited with restart `no`. `pft-runtime-db-1` is the sole running owner of `personal-finance-tracker_pgdata_production_backfill`; only web publishes `127.0.0.1:3000`, with no Production API/DB host port.
- Current localhost status showed five active institutions, jobs running, backup healthy with last success `2026-09-24T20:08:24.809645Z`, no running sync, and publication `3795ad32-ca11-4695-bc06-9cbfcdd0f51d` at `2026-09-24T20:08:30.619006Z`. The latest accepted [post-Serve fingerprint](PFT_PHASE_2_M1_AFTER_SERVE_RECONNECT_FINGERPRINT_2026-09-25.json) has SHA-256 `6124cac697fcb57bccdbdf1ecc21a4b8a0e6e6472fc4ab789c5edd79d682102d`: 15 tables, five institutions, zero integrity errors. These are preparation observations, **not** substitutes for the immediate pre-restart readings.
- Tailscale [documents `--bg` Serve persistence across reboot](https://tailscale.com/docs/reference/tailscale-cli/serve); Docker [documents its sign-in autostart setting](https://docs.docker.com/desktop/settings-and-maintenance/settings/). This action measures those behaviors on this host. A configured Serve handler alone does not prove the app is reachable; Safari and localhost must both work after sign-in.

## Gate A — immediately before the approved restart (read-only)

1. Record UTC time, current Windows boot time (`Get-CimInstance Win32_OperatingSystem | Select-Object LastBootUpTime`), branch/SHA/`git status`, and the four container IDs/images/start times. Do not reset or commit unrelated work. Confirm Docker Desktop Settings → General still has **Start Docker Desktop when you sign in** enabled, Windows Settings → Apps → Startup still allows Docker Desktop, its saved `AutoStart` remains `true`, and Windows-native `docker.exe desktop status` says `running`. Require `Get-Service Tailscale` to show Running/Automatic. Stop if either startup mechanism is disabled or has changed unexpectedly. The read-only Windows setting checks are:

   ```powershell
   (Get-Content -Raw "$env:APPDATA\Docker\settings-store.json" | ConvertFrom-Json).AutoStart
   & 'C:\Windows\System32\reg.exe' query 'HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' /v 'Docker Desktop'
   Get-CimInstance Win32_OperatingSystem | Select-Object LastBootUpTime
   ```
2. In Windows PowerShell, run the following read-only checks. Require the same Windows/iPhone node IDs, DNS names and IPs, MagicDNS and exact current certificate domain; `Resolve-DnsName` must return `100.109.100.36`. Require Serve JSON to contain **only** HTTPS `443` and `pft-host.tailc4d964.ts.net:443` path `/` → `http://127.0.0.1:3000`. `funnel status` must say **tailnet only**, with no `AllowFunnel: true`, extra handler, or old hostname. The `funnel status --json` command may mirror private Serve config; a nonempty object alone is not Funnel exposure.

   ```powershell
   Get-Service -Name Tailscale | Select-Object Name, Status, StartType
   & 'C:\Program Files\Tailscale\tailscale.exe' status --json
   Resolve-DnsName -Name 'pft-host.tailc4d964.ts.net' -Type A
   & 'C:\Program Files\Tailscale\tailscale.exe' serve status --json
   & 'C:\Program Files\Tailscale\tailscale.exe' funnel status --json
   & 'C:\Program Files\Tailscale\tailscale.exe' funnel status
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' desktop status
   ```

3. In Admin Console, **read only**: confirm HTTPS Certificates/MagicDNS still enabled, current-name machine certificate valid, and exactly the saved two-device policy with its one `tcp:443` grant/two tests and no other grants/ACL/SSH. Check the local rollback copy's SHA-256, but do not save a policy change. Confirm the private API HTTP settings remain exactly `PFT_STRICT_LOCAL_HTTP=true`, `PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000`, `PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000`, and `PFT_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,https://pft-host.tailc4d964.ts.net`; do not print other private env values.
4. From WSL, require `docker ps`/`docker inspect` to show the same four `pft-runtime` service identities/images, `unless-stopped`, DB/API/web healthy and jobs running; the old Production DB must be exited with restart `no`. `docker ps --filter volume=personal-finance-tracker_pgdata_production_backfill --format '{{.Names}}'` must return only `pft-runtime-db-1`. Require web bound only to `127.0.0.1:3000` and no API/Production DB host port. On **Windows**, not WSL localhost, require HTTP `200` for `/` and `/api/pft/sync/status`. Repeat the live proxy's harmless nonexistent-review-route Origin probe: current HTTPS Origin `404`; old hostname and missing Origin `403`. Stop if this boundary or any runtime identity differs. Run the same HTTP probes again after sign-in:

   ```powershell
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' 'http://127.0.0.1:3000/'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' 'http://127.0.0.1:3000/api/pft/sync/status'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://pft-host.tailc4d964.ts.net' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://randy-pc.tailc4d964.ts.net' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   ```
5. Record status JSON: five active Items, no active sync, jobs running with a fresh heartbeat, backup healthy and its last success/age, latest publication ID/time, and last run outcome. Require an intact recent recovery point: the [accepted M0 isolated restore](PFT_PHASE_2_M0_BASELINE_2026-09-24.md) covers the post-September-24 published baseline; verify the protected archive is still available and current backup is healthy. If a later natural run/user edit means the accepted restore point no longer covers the current state, or backup is overdue/failed, **stop and review a fresh backup/recovery preflight before restarting**. Do not use a stale or unverified backup as a pass.
6. Capture a new read-only repeatable-read fingerprint immediately before restart. Use the existing API container and `scripts/pft_m6_fingerprint.py`; save the JSON outside the container with a dated name and SHA-256. Record all 15 counts/hashes, database/five-institution identity, source breakdown, and four integrity checks. Compare with the last accepted Serve fingerprint and explain any legitimate naturally elapsed cycle or user edit before the reboot. Record current desktop Overview, Membership, both Review modes, one detail, and publication ID for post-restart iPhone comparison. If a sync begins, let it finish naturally and re-baseline; do not alter its cursor or schedule.

   ```bash
   docker exec -i pft-runtime-api-1 python - --output /tmp/pft-m1-restart-before.json < scripts/pft_m6_fingerprint.py
   docker cp pft-runtime-api-1:/tmp/pft-m1-restart-before.json /tmp/pft-m1-restart-before.json
   sha256sum /tmp/pft-m1-restart-before.json
   ```

## Gate B — one Windows restart and owner sign-in, only after approval and Gate A

In Windows PowerShell, issue exactly one normal restart **without `/f`**:

```powershell
& 'C:\Windows\System32\shutdown.exe' /r /t 0
```

The owner signs into the **same Windows account** after reboot and leaves the PC awake and network-connected. Do not manually launch Docker Desktop, start containers, run `tailscale up`, or reapply Serve/policy before the first recovery observations. The app and private URL will be unavailable while Windows/Docker are down; the existing database volume and containers should resume, with new start times and the same container/image identities. A normal scheduled jobs/backup action may become due during real elapsed downtime; do not manipulate time, cursor, due state, or schedules to create a catch-up result. Microsoft [documents `/r` and `/t` for a normal restart](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown).

## Gate C — automatic recovery, preservation, and iPhone acceptance

1. Record new Windows boot time and sign-in time. **Before any manual recovery**, observe Tailscale service/backend Running and `docker.exe desktop status` running; allow up to five minutes after sign-in for Docker Desktop startup, recording observations at roughly one, three, and five minutes. If it does not start automatically, mark this gate **failed** before using any recovery command. Do not infer Docker health from a running GUI alone.
2. Require the same Tailscale node ID, DNS/IP, MagicDNS/current certificate domain, valid certificate, and unchanged console policy. Require Serve's exact singleton HTTPS `443` handler and `funnel status` **tailnet only** with no `AllowFunnel`. Verify no new public route, subnet route, Docker API/DB host port, or old-name handler. Record any Tailscale reconnect delay before the final result.
3. Require all four `pft-runtime` containers to auto-resume with the same container IDs and image IDs, `unless-stopped`; DB/API/web healthy, jobs running. Require the old Production DB still exited/restart `no`, the new DB the **sole** running volume owner, and web still loopback-only. From Windows, home and sync status must each return `200`; current Origin must reach harmless routing (`404`) while old/missing Origin remains `403`. Check publication, five active Items, backup health, and no lingering active sync. Allow the documented seven-minute heartbeat grace after jobs starts, then require a fresh heartbeat and `jobs=running`; record a failure if it does not recover. A naturally due run may be active; wait for its normal completion and evaluate its backup-before-sync and five Item outcomes separately rather than calling the reboot a fabricated overdue test. Use the same Serve, Tailscale, Docker, volume, and HTTP commands from Gate A, capturing their output before any recovery command.
4. Capture the post-restart repeatable-read fingerprint with the same script and API container, and save its SHA-256. Compare all 15 table counts/hashes, institution scope, raw source breakdown, and four zero-integrity checks to the immediate pre-restart fingerprint. If no natural job/user write occurred, require the 14 non-heartbeat tables to match exactly; only `sync_runtime_state` heartbeat may advance. If a natural cycle or owner edit did occur, require matching run/audit evidence, backup timing, item outcomes, publication and financial reconciliation before accepting any data delta. Unknown differences or integrity errors fail the gate. No restore or SQL fix is automatic.

   ```bash
   docker exec -i pft-runtime-api-1 python - --output /tmp/pft-m1-restart-after.json < scripts/pft_m6_fingerprint.py
   docker cp pft-runtime-api-1:/tmp/pft-m1-restart-after.json /tmp/pft-m1-restart-after.json
   sha256sum /tmp/pft-m1-restart-after.json
   ```

5. On Windows desktop localhost, compare Overview, Membership, both Review modes, one transaction detail, and publication ID to the recorded pre-restart values, accounting only for an evidenced natural run/user edit. On real iPhone Safari with Tailscale connected, open `https://pft-host.tailc4d964.ts.net/` first over Wi-Fi, then with Wi-Fi off over cellular. Require no certificate warning, working API, the same publication/totals and representative views/detail as desktop, and reload/focus recovery. With cellular active, a fresh URL must fail while the iPhone VPN is off and load again once reconnected. This is read-only acceptance; do not make a phone edit. If the PC sleeps or is off, temporary unavailability is expected and is outside this recovery gate.

**Pass:** Automatic Docker and Tailscale startup, persistent private Serve, Funnel disabled, localhost and real-iPhone Wi-Fi/cellular paths, one Production-volume owner, healthy jobs/backup, and explained preserved financial state all pass **without manual reconfiguration**. Record actual boot/sign-in/recovery timestamps and a dated execution receipt. A failed automatic start remains a failure even if manual recovery later restores service.

## Failure containment and recovery (record failure before acting)

- If Docker Desktop is absent after the five-minute observation, collect its status/events, then the **manual recovery** command is `& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' desktop start --timeout 180`. This restores service but does **not** pass the automatic-recovery gate. If Desktop runs but containers remain stopped, first verify the old DB is exited and no other container owns the Production volume; only then run the following in WSL, waiting for DB health before API and API health before web/jobs. Do not run `compose up`, recreate images/containers, start the legacy DB, or attach another DB to the volume as a blind fix.

  ```bash
  docker start pft-runtime-db-1
  docker inspect --format '{{.State.Health.Status}}' pft-runtime-db-1
  docker start pft-runtime-api-1
  docker inspect --format '{{.State.Health.Status}}' pft-runtime-api-1
  docker start pft-runtime-web-1 pft-runtime-jobs-1
  ```
- If Tailscale is stopped, capture status and use `Start-Service -Name Tailscale` as a manual recovery step; if sign-in or device identity changed, stop for owner review. If Tailscale runs but the Serve handler is absent, first confirm the exact current DNS/IP, restrictive policy, no unrelated handler, and Funnel off. Only then restore the single known endpoint with `& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --https=443 http://127.0.0.1:3000`; this is manual recovery and fails automatic persistence. Do not enable Funnel, `tailscale cert`, or a new tailnet setting.
- If an unexpected Serve/Funnel handler or public exposure appears, do not use `serve reset` or alter the policy indiscriminately. If the only handler is the M1 HTTPS `443` endpoint, remove just that endpoint with `& 'C:\Program Files\Tailscale\tailscale.exe' serve --https=443 off`, verify statuses, and keep desktop localhost available while investigating. If another handler exists, stop and review its owner before changing it.
- If DB ownership, health, backup, publication, Origin boundary, or financial fingerprint is unexplained, stop acceptance, preserve logs/snapshots/backup artifacts, and request a scoped recovery decision. Do not restore a backup over Production, run migrations, manually sync/Plaid, rewrite cursors, or change scheduler due times as a rollback. The Windows restart itself cannot be undone; the safe fallback for a private-path failure is the existing healthy localhost app plus a narrowly inspected Serve rollback.

## Phase 1 evidence and approval boundary

The [accepted M0 report](PFT_PHASE_2_M0_BASELINE_2026-09-24.md) observed the first subsequent naturally elapsed daily cycle. Its **second normal daily cycle** and a **real overdue startup catch-up after naturally elapsed downtime** remained open at this packet's preparation time. Recheck their actual status at execution. This short restart is a recovery test, not proof of overdue catch-up unless a real due time actually passes and the resulting scheduled behavior is independently observed. Do not change clocks, cursors, or schedules to force that evidence.

**Execution disposition:** The owner approved this one Windows restart/sign-in action. All three gates passed without manual recovery; the evidence and open Phase 1 observations are in the [execution receipt](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md). Stop after this M1 result; do not begin M2.
