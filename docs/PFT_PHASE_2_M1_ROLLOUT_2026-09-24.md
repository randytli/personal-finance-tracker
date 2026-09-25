# Phase 2 M1 private iPhone access — rollout and execution record (2026-09-24)

**Owner acceptance and checkpoint, 2026-09-25:** Phase 2 M1 is owner-accepted and complete. This checkpoint contains the reviewed exact Host/Origin boundary, guarded private-env helper, focused tests, and dated deployment/Serve/iPhone/restart evidence. Checkpoint verification passed **21 focused HTTP/env/runtime tests, zero skips**, using synthetic sandbox settings and a nonconnecting database URL. The earlier broader backend/frontend and live proxy results remain recorded below; this checkpoint did not rerun Production actions.

**Phase 1 remains open for two observations:** (1) the second subsequent naturally elapsed normal daily cycle, including backup-before-sync, five-Item outcomes, publication and financial reconciliation; (2) a real overdue startup catch-up after naturally elapsed downtime. Neither observation is certified by M1 acceptance or the short reboot. No clocks, cursors, or schedules were manipulated. Stop after this checkpoint and wait for owner direction before M2.

The dated stage packets preserve the approval boundaries and observations at the time of each action. Their earlier stop points are historical; this acceptance statement and the final restart receipt describe the completed M1 state.

**Current state, 2026-09-25:** The restrictive tailnet policy, renamed Windows node, HTTPS certificate prerequisite, and Production API Origin are active. Owner-approved private Serve is running for `https://pft-host.tailc4d964.ts.net/`, with the single HTTPS `443` handler forwarding to Windows `127.0.0.1:3000`; Funnel is off. Real iPhone Safari read-only acceptance passed on Wi-Fi and cellular. The VPN-off negative check showed expected inaccessibility; the owner clarified an ambiguous “Reconnect failed” reply after a cautious one-endpoint rollback, and the same Serve endpoint was restored with localhost and preservation checks passing. The owner then confirmed a fresh cellular Safari request loaded both the API status URL and app home with VPN reconnected, completing the negative/reconnect check. The [Serve execution record](PFT_PHASE_2_M1_SERVE_ACTION_PACKET_2026-09-25.md#execution-record-2026-09-25) contains that evidence. The subsequent [single Windows restart/sign-in recovery test](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md) passed without manual recovery: Docker Production, Tailscale, private Serve, localhost, iPhone Wi-Fi/cellular, and financial preservation recovered. Stop after M1; do not begin M2.

**Earlier blocker, now resolved:** The first M1 Serve attempt reported that Serve was not enabled on the tailnet. Tailscale documents [tailnet HTTPS certificates as required for Serve](https://tailscale.com/docs/features/tailscale-serve). That attempt was cancelled without enabling HTTPS, Serve, or Funnel. The owner separately approved and enabled HTTPS certificates before the later Serve action.

**Final M1 recovery boundary:** The owner approved the [Windows restart and sign-in action packet](PFT_PHASE_2_M1_WINDOWS_RESTART_ACTION_2026-09-25.md); its [execution receipt](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md) records a pass. The remaining Phase 1 second natural daily cycle and real overdue catch-up observations remain open. No clocks, cursors, or schedules were changed to accelerate them.

The executed API stage, Serve blocker, image IDs, gates, impact, and rollback are in the [M1 Production action packet](PFT_PHASE_2_M1_PRODUCTION_ACTION_PACKET_2026-09-24.md). The [2026-09-25 Origin replacement action](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md) supersedes the preparatory Action B examples below for future Production work.

**2026-09-25 update:** The Windows Tailscale device is now `pft-host.tailc4d964.ts.net` with the same node ID/IP. See the [rename receipt and stop point](PFT_PHASE_2_M1_DEVICE_RENAME_2026-09-25.md). The old `randy-pc` entries in the 2026-09-24 evidence below describe the actual earlier deployment and device identity; they are not the future HTTPS target. The separate [Production API Origin replacement](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md) subsequently passed. Future phone URL: `https://pft-host.tailc4d964.ts.net/`.

## Evidence and target boundary

- Windows-native `curl.exe http://127.0.0.1:3000/` returned 200. Existing Production web publishes only `127.0.0.1:3000`; API and Production DB have no host port. Preserve those bindings and the existing Docker project/volume.
- In an isolated built Next.js → FastAPI chain, a request with either local or simulated phone Host arrived at FastAPI with the rewrite target Host `127.0.0.1:18080`. FastAPI received the original browser Origin: allowed local and HTTPS Origins passed the middleware to a nonexistent route (404); missing/hostile Origins returned 403. A spoofed `X-Forwarded-Host` did not change the decision. The Production Next.js → FastAPI path later passed the same allowed/denied Origin probes with exact Host allowlist `api:8000`.
- Verification: 246 backend tests passed with all seven synthetic PostgreSQL opt-ins and zero skips against a fresh isolated database; after adding the duplicate-Host case, 13 focused HTTP/env tests passed. Frontend 28 tests, TypeScript typecheck, Python compilation, `git diff --check`, and the isolated Next.js production build passed. The temporary proxy servers and synthetic PostgreSQL cluster were stopped. These checks do not substitute for real Tailscale or iPhone acceptance.
- Deployed Production FastAPI configuration, with only the two M1 allowlist lines added to the private env file:

  ```dotenv
  PFT_STRICT_LOCAL_HTTP=true
  PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000
  PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000
  PFT_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,https://randy-pc.tailc4d964.ts.net
  ```

  `PFT_ALLOWED_ORIGIN` remains for compatibility; the new list adds localhost and the **actual** HTTPS browser Origin. The Tailscale name is an Origin, not an API Host, because Next.js rewrites to `api:8000`. The exact API Host list also admits its local health probe. Invalid/missing strict configuration fails startup; writes without an allowed Origin fail closed. No forwarded Host/identity header is trusted. Browser fetches already use relative `/api/pft/...` paths, so no CORS or new public port is needed.
- Current [Tailscale Personal pricing](https://tailscale.com/pricing) is $0 for non-commercial use with unlimited user devices and up to six users. The owner confirmed that Billing shows **Personal** on 2026-09-24. [Serve](https://tailscale.com/docs/features/tailscale-serve) is private to the tailnet and uses a tailnet HTTPS certificate; [Funnel](https://tailscale.com/docs/features/tailscale-funnel) is public and is excluded.

## Action A — installed and discovered identity (owner approved; 2026-09-24)

**Installation and identity:** The official [Windows installer](https://tailscale.com/docs/install/windows) from `https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe` was downloaded to the owner's Windows Downloads folder. SHA-256: `dc874bb9db4a93e1e412f44ed629ec4b432ae24c7322f9d51d445b15a852a9e5`; Windows Authenticode status `Valid`, signer `Tailscale Inc.` (certificate thumbprint `108F172FDE945B21A5C0696731D6220D67D1C39E`). Installed Windows CLI version `1.102.4`; Tailscale service and backend are running. The owner installed and joined the official [iOS app](https://tailscale.com/docs/install/ios). Read-only `tailscale status --json` showed:

| Device | Device name | Tailnet DNS name | Tailscale IPv4 | Tailscale IPv6 | State |
| --- | --- | --- | --- | --- | --- |
| Windows Production host | `Randy_PC` | `randy-pc.tailc4d964.ts.net` | `100.109.100.36` | `fd7a:115c:a1e0::ea01:64cd` | Running |
| Owner iPhone | `iphone-15-pro` | `iphone-15-pro.tailc4d964.ts.net` | `100.99.41.95` | `fd7a:115c:a1e0::d839:2960` | Online |

Both devices report Tailscale user ID `6835685919123983`. Windows `tailscale serve status --json` and `tailscale funnel status --json` each returned `{}`. Windows-native `curl.exe http://127.0.0.1:3000/` still returned HTTP 200. The four existing `pft-runtime` containers remained running; the web port remained bound to Windows loopback only, with no API/DB host ports. No Production service was restarted. The owner supplied the current default policy and confirmed Billing shows Personal. No Serve/Funnel, policy, subnet, or Production configuration change was made.

From an Administrator PowerShell window on Windows, inspect the installed CLI and identity before any Serve command:

```powershell
tailscale version
$ts = tailscale status --json | ConvertFrom-Json
$ts.Self.DNSName.TrimEnd('.')
$ts.Self.TailscaleIPs
tailscale serve status --json
tailscale funnel status --json
```

**Observed effect:** The Windows PC and iPhone are the two devices shown in the Windows CLI's tailnet view. The owner confirmed the Personal plan. The installed CLI's read-only `serve --help` confirms `--bg` and `--https` flags, `http://127.0.0.1:3000` as a supported target form, and `serve status --json`.

**Reviewed policy replacement:** The owner supplied the complete default policy. Its active network grant was `{"src":["*"],"dst":["*"],"ip":["*"]}`; its other active rule was the default Tailscale SSH `check` rule from `autogroup:member` to `autogroup:self`. The other blocks in the supplied text were comments. Grants are additive, so adding a narrow rule without removing the wildcard grant would not restrict access. The approved **full replacement** for this new two-device tailnet was:

```json
{
  "hosts": {
    "pft-iphone": "100.99.41.95",
    "pft-windows": "100.109.100.36"
  },
  "grants": [
    {"src": ["pft-iphone"], "dst": ["pft-windows"], "ip": ["tcp:443"]}
  ],
  "tests": [
    {"src": "pft-iphone", "proto": "tcp", "accept": ["pft-windows:443"], "deny": ["pft-windows:22", "pft-windows:3000"]},
    {"src": "pft-windows", "proto": "tcp", "deny": ["pft-iphone:443"]}
  ]
}
```

This replaced the broad grant, removed the default Tailscale SSH rule, and added only iPhone → Windows TCP 443 plus policy tests. The owner confirmed no reliance on Tailscale SSH or other device-to-device tailnet access. Device IP changes require a reviewed policy update. The owner confirmed Personal; both devices report the same Tailscale user ID. [Tailscale grants](https://tailscale.com/docs/reference/syntax/grants) and [policy tests](https://tailscale.com/docs/reference/syntax/policy-file#tests) support these selectors, port scopes, and assertions.

### Restrictive policy replacement (owner approved and saved)

**Scope and backup:** The owner approved this policy replacement only. The owner copied the full current console policy from the JSON editor; it matched the previously supplied default text, including the sole allow-all grant and default SSH rule. Its exact clipboard text was preserved before any save at `C:\Users\tianr\Downloads\pft-m1-tailnet-policy-before-20260924.hujson` (SHA-256 `8031034e164a25610ceb4fbf518b186e0161e6b062cab0ed700f64220135141b`). The reviewed proposed JSON above was copied to `C:\Users\tianr\Downloads\pft-m1-tailnet-policy-proposed-20260924.json` (SHA-256 `42f24eb75b0c70303cb0f295a4bf2953cc2bd351bbf6031eefbfb8075c1e3c26`) and the Windows clipboard. The owner pasted and saved it in the authenticated admin-console JSON editor. No Serve, Funnel, device setting, subnet routing, Docker, or Production change was performed.

**Expected effect:** The iPhone at `100.99.41.95` can reach the Windows device at `100.109.100.36` on TCP 443 only. Other tailnet TCP ports and Windows → iPhone access are denied by the network grants. The existing default Tailscale SSH rule is removed. Windows localhost `127.0.0.1:3000` and Docker networking stay as they are. Since Serve is disabled, saving the policy alone does not make the app available by HTTPS yet.

**Verification after save (2026-09-24 19:32 EDT):** Immediately before the owner's console save, read-only Windows checks confirmed the same two device identities, empty Serve/Funnel statuses, and Windows localhost HTTP 200. The owner reported a successful save. The owner reopened and copied the saved JSON; its exact text was preserved at `C:\Users\tianr\Downloads\pft-m1-tailnet-policy-after-20260924.json` (SHA-256 `a13a5dfa372facd261255ea2e26e4270ed4ad0202604e9c602a54450081b0428`). Parsing both saved and reviewed JSON showed them semantically identical: exactly two host aliases, one iPhone → Windows TCP 443 grant, two tests, and no broad grants, ACLs, or SSH section. Tailscale [rejects an update if any policy test fails](https://tailscale.com/docs/reference/syntax/policy-file#tests), so the successful save with both tests present is evidence that both passed. After saving, Windows `tailscale status --json` again showed the same Windows and online iPhone DNS names and IPs; `serve status --json` and `funnel status --json` both remained `{}`; Windows `http://127.0.0.1:3000/` returned HTTP 200. Actual HTTPS/Safari behavior cannot be tested until Serve is separately approved and enabled.

**Rollback:** If the policy is rejected or unexpectedly affects required tailnet traffic, restore the exact saved original policy in the admin console and verify the original rule is active. This deliberately restores the original broad grant; Serve remains disabled. If a restrictive safe state is preferred instead, pause for a separately reviewed revision. Localhost app and Docker remain untouched.

## Action B — reviewed API boundary (completed)

The following preparatory examples have been revised for the new name but are superseded by the [specific Origin replacement action](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md). Use that packet's exact commands and gates for any approved Production change.

The revised browser origin is `https://pft-host.tailc4d964.ts.net`. Confirm that this is the exact URL to be opened in Safari and that the full tailnet policy is restrictive. Recheck the M0-style read-only fingerprint, publication marker, five-Item scope, and backup health immediately before any subsequent API deployment. If recovery status is stale or unhealthy, stop and review before changing API. Do not run a Production sync or migration.

From the repository in WSL, the exact env edit after approval is:

```bash
python3 scripts/pft_m1_http_env.py --origin 'https://pft-host.tailc4d964.ts.net' --previous-origin 'https://randy-pc.tailc4d964.ts.net'
```

The helper requires the existing strict/local lines and a private mode-0600 file, atomically adds only the two M1 allowlist lines, and prints no secret values. At execution, the source code matched the reviewed M1 hashes recorded in the action packet. Verify only the HTTP setting keys/values and file mode, without printing the rest of the private env file. Then set the existing Compose interpolation values and build/recreate **only** API:

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
docker image inspect pft-runtime-api --format '{{.Id}}'
docker image tag pft-runtime-api pft-runtime-api:m1-pre-20260924
docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime build api
docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime up -d --no-deps api
```

The `PFT_APP_COMMIT` value above is the existing jobs image value and is used only to satisfy Compose interpolation; jobs is not rebuilt or recreated. API should become healthy with read-only startup identity/schema checks. Web, jobs, DB, the Production volume, and their configuration stay running. Verify Windows localhost Overview/status/monthly reads and exact allowed/denied Origin behavior through `/api/pft`. Record API image ID before/after, then repeat the fingerprint with a new output name. Compare financial tables and explain any naturally scheduled changes. If API fails, the prepared rollback is:

```bash
python3 scripts/pft_m1_http_env.py --origin 'https://randy-pc.tailc4d964.ts.net' --previous-origin 'https://pft-host.tailc4d964.ts.net'
docker image tag pft-runtime-api:m1-pre-20260924 pft-runtime-api:latest
docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime up -d --no-deps --force-recreate api
```

Verify old API health and localhost again. If the helper refuses because the env file changed, inspect it privately rather than forcing rollback.

## Action C — private Serve (blocked at HTTPS certificate prerequisite)

The command below was attempted after the API gate passed. It reported that Serve is not enabled on the tailnet and supplied an admin-console activation link. The waiting command was cancelled; the status commands then confirmed empty Serve and Funnel configurations. Do not rerun the Serve command or enable tailnet HTTPS as part of this documentation review. Tailscale's [HTTPS setup guide](https://tailscale.com/docs/how-to/set-up-https-certificates) describes the separate consent and public Certificate Transparency record for an issued device DNS name.

Only after the API boundary and restrictive policy pass, run in **Windows Administrator PowerShell**, using the installed CLI:

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:3000
tailscale serve status --json
tailscale funnel status --json
```

**Expected effect:** `https://pft-host.tailc4d964.ts.net/` is served privately through the Windows host's loopback web port. The Serve status must show HTTPS port 443 proxying to `http://127.0.0.1:3000`; Funnel status must show no public endpoint. There is no router forwarding, subnet route, or new Docker API/DB/web binding. The [current CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve) documents this target form, status, exact `off` rollback, and `--bg` persistence across Tailscale/device restarts. Installed CLI syntax was checked with `serve --help`; actual Serve behavior awaits separate approval.

**Rollback:** In the same Administrator terminal, run `tailscale serve --https=443 off` and confirm Serve status has no M1 endpoint. Keep the separately approved restrictive IP-based tailnet policy and the device rename in place. This removes only the M1 Serve endpoint; do not use `serve reset` if other Serve entries exist. Keep localhost access and the existing DB/jobs running. If the new API Origin gate fails, use the [exact Origin replacement rollback](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md) separately.

## Acceptance sequence after those approvals

1. Read-only desktop regression: Windows `http://127.0.0.1:3000/`, Overview, Membership, both Review modes, transaction details, status, and representative financial totals/publication ID. Verify API/DB have no published host ports and the Production volume still has one running DB owner.
2. Real iPhone Safari with Tailscale enabled: open the exact HTTPS URL on Wi-Fi, then on cellular with Wi-Fi off. On each network, visit Overview, Membership, Credits & Transfers and Needs Review, and transaction details; compare values and publication ID with desktop. Check browser reload/focus refresh. Disconnect Tailscale and confirm the URL is unavailable outside the permitted tailnet. Check the TLS certificate/hostname and Serve/Funnel statuses.
3. Write acceptance is separate: first select and record the exact existing override state and a reversible edit/reversal, then obtain the owner's scoped approval for those two Production writes. Read-only phone access does not make the app server-enforced read-only.
4. After a separate restart/sign-in approval, capture fingerprint/status/backup baseline, perform the agreed Windows restart and sign-in, then verify Docker, Tailscale, Serve, localhost, iPhone Wi-Fi/cellular, and unchanged financial data/marker except naturally scheduled activity. PC sleep/off remains expected unavailability. On failure, disable only Serve and use the API/config rollback above.

**Historical stop point before Serve (2026-09-25):** Action A, the restrictive IP-based tailnet policy, the Windows device rename, the [new Production API Origin gate](PFT_PHASE_2_M1_ORIGIN_REPLACEMENT_ACTION_2026-09-25.md), and the [HTTPS certificate prerequisite](PFT_PHASE_2_M1_HTTPS_PREREQUISITE_ACTION_2026-09-25.md) were complete. A stale former-name Serve handler appeared after HTTPS was enabled and was cleared; Serve/Funnel statuses were `{}` at that stop point. The owner confirmed Personal billing. See the linked execution receipts for Production image and preservation evidence.

**Owner disposition and Serve packet:** The owner accepted HTTPS and the unresolved former-name CT status as a non-blocking privacy uncertainty, then approved the [current-name Serve and iPhone action packet](PFT_PHASE_2_M1_SERVE_ACTION_PACKET_2026-09-25.md). Its completed execution and successful VPN reconnect are recorded there. It supersedes the earlier Action C acceptance/rollback examples. The separately approved [restart/sign-in recovery](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md) subsequently passed; the owner accepted M1 as complete.
