# Phase 2 M1 — Production API Origin replacement (2026-09-25)

**Historical stage record:** The stop points below describe this action at its execution time. Phase 2 M1 is now owner-accepted and complete; see the [final rollout status](PFT_PHASE_2_M1_ROLLOUT_2026-09-24.md) and [successful restart/sign-in recovery](PFT_PHASE_2_M1_RESTART_RECOVERY_2026-09-25.md). The two remaining Phase 1 observations remain open.

**Status: owner-approved action executed and verified on 2026-09-25.** The Windows Tailscale device [has](PFT_PHASE_2_M1_DEVICE_RENAME_2026-09-25.md) MagicDNS name `pft-host.tailc4d964.ts.net` at the same `100.109.100.36` IP. This action replaced only the old HTTPS Origin in the private Production environment and recreated only the API container to load it. HTTPS, Serve, and Funnel were not enabled.

## Execution receipt

- Preflight: Windows Tailscale node ID `3351434150137017`, `pft-host.tailc4d964.ts.net` → `100.109.100.36`, iPhone `100.99.41.95`, MagicDNS enabled, `CertDomains: null`, Serve/Funnel `{}`. The previously saved restrictive policy JSON still has only iPhone → Windows `tcp:443` and its two tests (saved copy SHA-256 `a13a5dfa372facd261255ea2e26e4270ed4ad0202604e9c602a54450081b0428`); no policy save or edit was made. The private env was mode `0600` with the exact old HTTPS Origin. Windows localhost home and API status were `200`; jobs `running`, backup `healthy`, five active Items, no active sync, publication `3795ad32-ca11-4695-bc06-9cbfcdd0f51d`. Web alone published `127.0.0.1:3000`, and `pft-runtime-db-1` was the sole running owner of the Production volume. Compose config passed. The live proxy gave new-Origin `403` and old-Origin `404` before replacement.
- The read-only repeatable-read [before fingerprint](PFT_PHASE_2_M1_BEFORE_ORIGIN_FINGERPRINT_2026-09-25.json) covered 15 tables, five institutions, unchanged institution/source scope, and zero integrity errors. Its SHA-256 is `d045ce8eec06b0de6ce84950a2f69e1d8748cd64f08b0c845ace4ebb152b8d33`. Relative to the September 24 post-API fingerprint, only `sync_runtime_state` had changed, consistent with the running jobs heartbeat.
- Ran the exact guarded `--previous-origin` helper command below. It replaced one allowlist line and preserved private file mode `0600`. Only API was recreated, with `--no-deps --no-build --force-recreate --wait`; it became healthy. The API image stayed `sha256:cec3537e5a6fb670aeb823bdde7c213f92c237a29cde48b58306be4d545b57a2`. API container ID changed from `1e9264cb2938...` to `f4799bf8162b...`; web, jobs, and DB retained their IDs, image IDs, and start times. Inside the new API container, the four HTTP environment values matched the block below exactly.
- Postchange Windows localhost home, Membership page, Review page, and API status returned `200`. Through the live Windows localhost → Next.js → FastAPI chain, the nonexistent POST route returned **`404` for the new HTTPS Origin, `403` for the old HTTPS Origin, `403` for `https://evil.test`, and `403` with no Origin**. The `404` means the new Origin passed the boundary and reached routing; no financial handler ran. Serve/Funnel stayed `{}`. The DB still had one running volume owner and no API/DB host ports.
- September Overview gross/refunds/reimbursements/benefits/net were `6183.89 / 1607.97 / 37.50 / 200.26 / 4338.16` before and after. Trailing-12-month Membership through August remained 113 transactions and `2636.67 / 10.65 / 438.02 / 2188.00` gross/refunds/benefits/net. Needs Review remained 2; Credits & Transfers remained 504. Jobs/backup/five-Item status and publication ID were unchanged.
- The read-only repeatable-read [after fingerprint](PFT_PHASE_2_M1_AFTER_ORIGIN_FINGERPRINT_2026-09-25.json) has SHA-256 `fb1e5ec66e7e8aba56e63dea99b5a2c1793e3e34d37d41c6f6d25e08cbc56b44`. All 15 table counts match; 14 table full-row hashes match. Only the `sync_runtime_state` hash advanced, with its row count still one, consistent with the observed jobs heartbeat. Five-institution scope, raw source breakdown, and all four zero-integrity checks match exactly. **The gate passed; rollback was not needed.** No manual financial write or Plaid call was made.

## Approved change and gate (completed; do not rerun)

The resulting HTTP settings must be exactly:

```dotenv
PFT_STRICT_LOCAL_HTTP=true
PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000
PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000
PFT_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,https://pft-host.tailc4d964.ts.net
```

The former HTTPS Origin must be absent. The exact Host list stays `api:8000,127.0.0.1:8000` because Next.js reaches FastAPI as `api:8000`. The IP-based tailnet policy, web, jobs, DB, volume, all other environment values, and API image stay the same.

1. Before applying, read-only confirm current `pft-host` DNS/IP/node ID, the two-device restrictive policy, Serve/Funnel `{}`, Windows localhost home and status `200`, four `pft-runtime` identities, single running owner of `personal-finance-tracker_pgdata_production_backfill`, API health, jobs/backup health, five Items, publication ID, and no active sync. Capture a repeatable-read fingerprint using the same [M1 fingerprint procedure](PFT_PHASE_2_M1_PRODUCTION_ACTION_PACKET_2026-09-24.md#approved-execution-sequence-api-complete-serve-halted). Stop if this baseline or recovery state differs unexpectedly.
2. With the existing Production Compose interpolation exports from the [previous action packet](PFT_PHASE_2_M1_PRODUCTION_ACTION_PACKET_2026-09-24.md#approved-execution-sequence-api-complete-serve-halted), the following commands were run from WSL after approval:

   ```bash
   python3 scripts/pft_m1_http_env.py --origin 'https://pft-host.tailc4d964.ts.net' --previous-origin 'https://randy-pc.tailc4d964.ts.net'
   docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime config --quiet
   docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 api
   ```

   The helper requires the old exact allowlists and private file mode, changes one line atomically, and refuses a mismatch. Inspect only these four HTTP keys and the file mode afterward; do not print secrets. The API image is reused, not rebuilt. Expect a short API interruption while that one container restarts; web, jobs, and DB continue.
3. Require API healthy and both Windows localhost URLs (`/` and `/api/pft/sync/status`) to return `200`. Through the real Windows localhost → Next.js → FastAPI proxy chain, use the nonexistent review route for non-writing Origin probes:

   ```powershell
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://pft-host.tailc4d964.ts.net' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://randy-pc.tailc4d964.ts.net' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   & 'C:\Windows\System32\curl.exe' -sS -o NUL -w '%{http_code}' -X POST -H 'Origin: https://evil.test' 'http://127.0.0.1:3000/api/pft/review/__m1_boundary_probe__'
   ```

   Require `404 / 403 / 403`. Recheck local desktop Overview, Membership, both Review modes, representative totals/publication ID, backup/jobs/five-Item status, container image IDs and ports. Take a post-recreation repeatable-read fingerprint. All financial table counts/hashes and integrity checks must match unless a naturally scheduled job or user edit has separately evidenced a legitimate change; explain any such change before proceeding. Only routine `sync_runtime_state` heartbeat drift is expected.

If the API health, boundary, desktop, or preservation gate fails, reverse only the exact Origin change and recreate only API with the same Compose exports:

```bash
python3 scripts/pft_m1_http_env.py --origin 'https://randy-pc.tailc4d964.ts.net' --previous-origin 'https://pft-host.tailc4d964.ts.net'
docker compose -f compose.runtime.yml -f docker-compose.production.yml -p pft-runtime up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 api
```

Verify old API health and localhost `200`; keep Serve/Funnel `{}`. Stop if the helper refuses because the private file differs. The Tailscale rename remains in place during this API rollback.

**Next approval boundary:** This API stage is complete. The [revised HTTPS prerequisite](PFT_PHASE_2_M1_HTTPS_PREREQUISITE_ACTION_2026-09-25.md) remains unapproved and unexecuted. No Windows restart/sign-in or M2 work is included.
