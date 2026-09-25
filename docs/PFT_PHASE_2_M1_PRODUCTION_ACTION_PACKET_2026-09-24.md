# Phase 2 M1 Production API + private Serve action packet — 2026-09-24

**Historical stage record:** The stop points below describe this action at its execution time. Phase 2 M1 is now owner-accepted and complete; see the [final rollout status](PFT_PHASE_2_M1_ROLLOUT_2026-09-24.md) and [successful restart/sign-in recovery](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md). The two remaining Phase 1 observations remain open.

**Status: owner-approved API stage completed; Serve activation blocked and halted.** The owner accepted the restrictive tailnet policy as recorded in [the M1 rollout report](PFT_PHASE_2_M1_ROLLOUT_2026-09-24.md), then separately approved this staged action. The API stage passed its health, desktop, proxy-Origin, and preservation gates. The exact Serve command reported that Serve is not enabled on this tailnet and supplied an admin-console activation link. [Tailscale documents tailnet HTTPS certificates as a prerequisite for Serve](https://tailscale.com/docs/features/tailscale-serve). Enabling HTTPS requires separate owner approval; the command was cancelled, and Serve and Funnel remain disabled. No Windows restart or manual financial write occurred. The sequence below records the completed 2026-09-24 API stage and the uncompleted Serve stage. **For continuation:** Windows Tailscale was [renamed to `pft-host`](PFT_PHASE_2_M1_DEVICE_RENAME_2026-09-25.md) on 2026-09-25, and the [exact Origin replacement](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md) subsequently passed. The historical `randy-pc` API commands and evidence below must not be rerun as continuation steps.

## Execution receipt and current stop point

- Preflight: branch/source hashes, mode-0600 private env, Compose configuration, API rollback tag vacancy, four container identities, sole running DB-volume owner, Windows localhost HTTP 200, approved device identities, and empty Serve/Funnel all passed. Jobs were running, backup healthy, five Items present, latest run successful, and publication remained `3795ad32-ca11-4695-bc06-9cbfcdd0f51d`.
- The read-only repeatable-read [before fingerprint](PFT_PHASE_2_M1_BEFORE_FINGERPRINT_2026-09-24.json) had all 15 tables, five institutions, and zero integrity mismatches (SHA-256 `1b9a4615f802ac8934a4040c148e3f2b928cb76689a0d88edc9a529906999863`). The old API image was retained as `pft-runtime-api:m1-pre-20260924` pointing to `sha256:9ef45ea6154ae6465823fe9711621f2cf430c317775dbb42134c7b8699073f4d`.
- The helper added exactly the two approved Host/Origin lines to `.env.runtime.production.local`, preserving mode `0600`. Compose config passed. Only API was built and recreated, becoming healthy at `2026-09-24T23:45:03Z` with image `sha256:cec3537e5a6fb670aeb823bdde7c213f92c237a29cde48b58306be4d545b57a2`. Its `/app/api/main.py` hash matches reviewed source. Web, jobs, and DB retained their original image IDs and start times; web still publishes only Windows loopback, and DB remains the sole running Production-volume owner.
- Windows localhost home and proxied status both returned HTTP 200. Synthetic POST to a nonexistent review route returned `404` with the assigned HTTPS Origin, `403` with a hostile Origin, and `403` with no Origin. Jobs remained running, backup healthy, five Items present, and publication unchanged. September Overview gross/refunds/reimbursements/benefits/net remained `6183.89 / 1607.97 / 37.50 / 200.26 / 4338.16`; trailing-12-month Membership through August remained 113 transactions and `2636.67 / 10.65 / 438.02 / 2188.00` gross/refunds/benefits/net. Both Review modes returned successfully (Needs Review 2; Credits & Transfers 504).
- The read-only [after-API fingerprint](PFT_PHASE_2_M1_AFTER_API_FINGERPRINT_2026-09-24.json) has the same database, five-institution scope, source breakdown, and zero integrity mismatches (SHA-256 `d6d60b136d98e61313ed7032841334173d4e61b428451e22e211462d477c416b`). Fourteen table counts/full-row hashes match exactly. Only `sync_runtime_state` hash changed; its row count stayed one, while the running jobs heartbeat advanced. Status showed unchanged publication and backup timestamps, consistent with heartbeat-only operation.
- The documented Windows CLI command `tailscale serve --bg --https=443 http://127.0.0.1:3000` returned **“Serve is not enabled on your tailnet”** and an admin-console activation URL. It did not complete; the waiting command was cancelled. No activation URL was opened, HTTPS certificate setting enabled, or certificate requested. Immediately afterward, `serve status --json` and `funnel status --json` both returned `{}`, Windows localhost returned 200, and jobs/backup/five-Item status and publication were unchanged. Tailscale's [HTTPS setup guide](https://tailscale.com/docs/how-to/set-up-https-certificates) says enabling certificates involves admin-console consent and that issued device DNS names appear in the public Certificate Transparency ledger. That disclosure and the exact console setting need owner review before continuing. **Stop here:** private iPhone Safari access, Wi-Fi/cellular acceptance, and restart/sign-in recovery have not occurred.

**Local verification (2026-09-25):** The M1 HTTP boundary, private-env helper, and existing runtime tests passed together: 20 tests, zero skips, using a synthetic nonconnecting database URL and sandbox Plaid settings. Python compilation and `git diff --check` passed. The two sanitized fingerprint JSON files parse and differ only in `sync_runtime_state` as documented above. The earlier isolated M1 run passed 246 backend tests with all seven synthetic PostgreSQL opt-ins and zero skips, plus 28 frontend tests, typecheck, and build; no code changed after those results. This review performed no new Production or networking action.

## Baseline before the API stage

- At execution, checkout was `main` at `79bc3a8add6ff5a2aa0def0c70f383cf503c9184`, with the M1 API/env helper/tests/report still uncommitted. The deployed reviewed source was pinned by `api/main.py` SHA-256 `66b82f125627018ae55079e0abadf1bbd61290d870e3e437ccb834e17ca9f63b` and `scripts/pft_m1_http_env.py` SHA-256 `1f6ed321aed055fbca50057bad4167808790ebdff46cca53f54b53e44fb26910`.
- Production Compose project `pft-runtime` has healthy `api`, `web`, and `db`, with `jobs` running. Current image IDs: API `sha256:9ef45ea6154ae6465823fe9711621f2cf430c317775dbb42134c7b8699073f4d`; web `sha256:428dec07c99fe04d8bca63a0c05d48793afd2d1612631ca577ecb43e2ea8fd1a`; jobs `sha256:f3e3536c901ad23a4d3f1e2f007f11a4933dbc9cfa1c8b635565a8a2fbed60d2`; DB `sha256:c1b3783309b6499c795eed7c20135a1a4d25cae1b575c3d52c6f536129a1b109`. Only web publishes `127.0.0.1:3000`; API and Production DB have no host ports. The external Production volume remains `personal-finance-tracker_pgdata_production_backfill`.
- Current private `.env.runtime.production.local` is mode `0600` and has `PFT_STRICT_LOCAL_HTTP=true` and `PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000`, with no `PFT_ALLOWED_HOSTS` or `PFT_ALLOWED_ORIGINS`. Add exactly:

  ```dotenv
  PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000
  PFT_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,https://randy-pc.tailc4d964.ts.net
  ```

  The existing two lines remain. No wildcard, forwarded Host trust, CORS expansion, schema change, financial rule change, or Plaid configuration change is proposed. The DNS name is an allowed browser **Origin**; Next.js sends requests to FastAPI at Host `api:8000`.
- The approved policy grants only iPhone `100.99.41.95` → Windows `100.109.100.36` TCP 443. Windows `randy-pc.tailc4d964.ts.net` and iPhone `iphone-15-pro.tailc4d964.ts.net` remain online. Serve and Funnel statuses are `{}`. Owner confirmed Personal billing. The current status read shows jobs `running`, backup `healthy` (last success `2026-09-24T20:08:24.809645+00:00`), five Items, publication `3795ad32-ca11-4695-bc06-9cbfcdd0f51d`.

## Approved execution sequence (API complete; Serve halted)

Steps 1–3 below were executed and passed. Do not rerun them as part of this documentation review. Step 4 reached the separate tailnet HTTPS certificate prerequisite and stopped without enabling Serve. Step 5 has not begun.

1. **Read-only stop/go:** Recheck branch/source hashes, private env mode and exact existing HTTP keys, current image IDs, sole running Production-volume owner, loopback-only web binding, two Tailscale identities, saved restrictive policy, Serve/Funnel empty, and Windows localhost HTTP 200. Check status for jobs running, backup healthy, five active Items, publication marker, and no active sync. The accepted M0 isolated restore covers the post-sync baseline; if backup/recovery is stale or unhealthy, stop for review. Capture a new repeatable-read prechange fingerprint with `scripts/pft_m6_fingerprint.py`; do not trigger sync or Plaid. Existing Phase 1 natural-cycle observations remain open and are not accelerated.
2. **Save the old image; change only the private HTTP env; build/recreate only API.** From the repository in WSL:

   ```bash
   export PFT_RUNTIME_ENV_FILE=.env.runtime.production.local
   export PFT_DB_ENV_FILE=.env.runtime.db.production.local
   export PFT_BACKUP_ENV_FILE=.env.runtime.backup.production.local
   export PFT_BACKUP_HOST_DIR=/mnt/c/Users/tianr/PFTBackups/Production
   export PFT_APP_COMMIT=2b413550433e83db151ef1f62ad98b26d70fbd9e
   export PFT_WEB_PORT=3000
   docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime config --quiet
   docker exec -i pft-runtime-api-1 python - --output /tmp/pft-m1-before.json < scripts/pft_m6_fingerprint.py
   docker cp pft-runtime-api-1:/tmp/pft-m1-before.json /tmp/pft-m1-before.json
   docker image tag pft-runtime-api:latest pft-runtime-api:m1-pre-20260924
   python3 scripts/pft_m1_http_env.py --origin 'https://randy-pc.tailc4d964.ts.net'
   docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime config --quiet
   docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime build api
   docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime up -d --no-deps --no-build --wait --wait-timeout 120 api
   ```

   Confirm the backup image tag does not already exist before tagging. `PFT_APP_COMMIT` is only the current Compose interpolation value for jobs; jobs is not rebuilt or restarted. The only recreated container is `pft-runtime-api-1`. Web, jobs, DB, and their images and volumes remain running. Capture their image IDs and start times before and after.
3. **API gate before Serve:** Require API healthy. On Windows, `curl.exe http://127.0.0.1:3000/` and `curl.exe http://127.0.0.1:3000/api/pft/sync/status` must return 200. The status must still show five Items, jobs running, healthy backup, and a plausible publication marker. In Windows PowerShell, run the read-only boundary probes:

   ```powershell
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://randy-pc.tailc4d964.ts.net' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://evil.test' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   ```

   Expected status codes are `404`, `403`, `403` in that order. The first reaches FastAPI routing through the real Next.js proxy; the unknown route has no financial handler. A Host mismatch would return `400`. Recheck representative Overview/Membership/Review reads and financial totals. Then from WSL capture the postchange repeatable-read fingerprint:

   ```bash
   docker exec -i pft-runtime-api-1 python - --output /tmp/pft-m1-after-api.json < scripts/pft_m6_fingerprint.py
   docker cp pft-runtime-api-1:/tmp/pft-m1-after-api.json /tmp/pft-m1-after-api.json
   ```

   Compare all 15 table counts/hashes, integrity checks, and institution scope against the prechange fingerprint; explain any naturally scheduled jobs or user edits before proceeding. Stop and roll back API if there is an unexplained delta or desktop regression.
4. **Enable private Serve only after the API gate passes.** Confirm the tailnet has MagicDNS and HTTPS certificates enabled; if the CLI presents an admin URL or requires a new tailnet setting, stop and review that change separately. In Windows Administrator PowerShell, run exactly:

   ```powershell
   & 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --https=443 http://127.0.0.1:3000
   & 'C:\Program Files\Tailscale\tailscale.exe' serve status --json
   & 'C:\Program Files\Tailscale\tailscale.exe' funnel status --json
   ```

   Require HTTPS 443 proxying to `http://127.0.0.1:3000` at `https://pft-host.tailc4d964.ts.net/` and no Funnel endpoint. Do not run `tailscale funnel`, advertise routes, change Docker port bindings, or open router/API/DB ports. The installed Windows CLI `1.102.4` supports the target and flags; actual Serve behavior has not been exercised. First require the separate new-Origin API gate and HTTPS prerequisite to pass.
5. **Acceptance reads:** In iPhone Safari with Tailscale connected, test the exact HTTPS URL on Wi-Fi and then cellular with Wi-Fi off. Check TLS hostname, Overview, Membership, Credits & Transfers, Needs Review, transaction details, publication ID, representative totals, reload, and focus refresh; compare with desktop localhost. Disconnect Tailscale and confirm the URL is unavailable. Recheck localhost, four container identities, sole DB-volume owner, Serve status, and Funnel empty. No application write test is part of this action. A Windows restart/sign-in recovery test remains a separate approval boundary.

## Expected impact and rollback

- The API container will be rebuilt and recreated once, causing a short interruption to `/api/pft/...` requests. The web container remains up; its page may load while API requests briefly fail. Jobs and DB continue, so a naturally scheduled sync may write data and call Plaid, changing financial fingerprints; this must be explained from run evidence. Windows localhost access remains the desktop path. After Serve starts, the owner iPhone can reach the same app only through the restricted tailnet HTTPS endpoint while the PC is awake and online. No recurring paid service, manual Production SQL write, manual Plaid call, or Windows reboot is proposed.
- If Serve is configured but phone/TLS checks fail, first remove only this endpoint in Windows Administrator PowerShell:

  ```powershell
  & 'C:\Program Files\Tailscale\tailscale.exe' serve --https=443 off
  & 'C:\Program Files\Tailscale\tailscale.exe' serve status --json
  & 'C:\Program Files\Tailscale\tailscale.exe' funnel status --json
  ```

- If the API or desktop gate fails, after disabling Serve if present, restore only the M1 HTTP lines and old API image (using the same Compose exports above):

  ```bash
  python3 scripts/pft_m1_http_env.py --origin 'https://randy-pc.tailc4d964.ts.net' --rollback
  docker image tag pft-runtime-api:m1-pre-20260924 pft-runtime-api:latest
  docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 api
  ```

  Verify old API image ID `sha256:9ef45ea6154ae6465823fe9711621f2cf430c317775dbb42134c7b8699073f4d`, API health, Windows localhost 200, status, and preservation fingerprint. If the env helper detects unexpected edits, stop and inspect privately rather than overwriting them. Keep the approved restrictive tailnet policy; it has no app endpoint after Serve is off. Do not restore the previous allow-all policy as part of an API/Serve rollback.

**Approval boundary:** The API stage is complete. The next action needs separate approval for the tailnet HTTPS certificate prerequisite. This documentation review authorizes no HTTPS enablement, Serve/Funnel activation, Windows restart/sign-in recovery, financial write, manual Production Plaid call, M2, or unrelated networking change.

**2026-09-25 continuation:** The Windows device rename passed with its IP/node identity preserved. The [new-Origin API action](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md) was separately approved, executed, and passed its full gate. The [HTTPS prerequisite action](PFT_PHASE_2_M1_HTTPS_PREREQUISITE_ACTION_2026-09-25.md) was also approved and enabled. A stale former-name Serve handler appeared after HTTPS propagated; the targeted `off` failed and the sole Serve configuration was cleared with `serve reset`. Final Serve/Funnel statuses are `{}`. Stop for owner review of that exception before beginning a new Serve activation; Windows restart/sign-in remains a later boundary.

**Current Serve continuation:** The owner accepted the HTTPS prerequisite and the former-name CT uncertainty as non-blocking. Use the [new current-name Serve action packet](PFT_PHASE_2_M1_SERVE_ACTION_PACKET_2026-09-25.md) for all future prechecks, commands, phone acceptance, Funnel interpretation, and rollback. The earlier step 4/5 and rollback examples above are historical preparation; in particular, `funnel status --json` may mirror a private Serve configuration, so it need not be `{}` after Serve starts. The new packet remains unapproved and unexecuted.
