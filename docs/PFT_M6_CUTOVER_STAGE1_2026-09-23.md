# M6 Production cutover: Approval Point 2 evidence (2026-09-23)

This records only the approved cutover through API/web read-only validation. The
jobs scheduler has **not** been started and no Production Plaid call was made.
Approval Point 2 is the boundary before any Production sync.

## Identity, writer freeze, and backup

- Rechecked the M0 Production identity before action: database
  `pft_production_backfill`, role `pftbackfill`, PostgreSQL 16.15, old container
  `personal-finance-tracker-db-production-backfill-1`, Compose project
  `personal-finance-tracker`, service `db-production-backfill`, host port 5434,
  and exact named volume `personal-finance-tracker_pgdata_production_backfill`
  mounted at `/var/lib/postgresql/data`. No native API/web/jobs process,
  port-8000/3000 listener, or unexpected DB writer session was present before
  the dump. The five active Items and all cursor-presence flags were unchanged:
  American Express (2 enabled accounts), Bank of America (1), Capital One (2),
  Chase (3), and Robinhood (1 enabled, 4 disabled). No pending/disabled Item.
- Captured a read-only repeatable-read fingerprint, then wrote the **fresh**
  pre-cutover custom dump to the protected Windows `Production` backup directory:
  `pft-m6-precutover-20260923T195244Z.dump`, 420,774 bytes, SHA-256
  `5bcaa7ad50420f009d7fb0ded267ce1f264fafcbb94ad403a3416d83d3a887fb`.
  `pg_restore -l` passed. Its Windows ACL grants only the user, Administrators,
  and SYSTEM. A second source fingerprint after the dump was identical.
- Restored that exact archive into a **new isolated** PostgreSQL 16 database on
  port 55440 with `--exit-on-error --no-owner --no-privileges`. All 12 table
  counts and full-row hashes, Item/account scope, raw source/date/removal
  breakdown, and integrity checks matched the frozen source. A canonical
  digest of those preservation fields was
  `7073aab39e91b7a9e864c23e0a787eb70107f23c559b1007875202fe5828211c`
  for both source and restore. The matching counts include 5 Items, 13
  accounts, 2,517 raw and 2,517 normalized transactions, 1 statement batch,
  171 statement rows, 60 classification, 166 category, 27 label, and 8 benefit
  overrides. There are no removed raw rows or checked integrity errors.

## Volume handoff and migration

- Set the old DB container restart policy to `no`, stopped **only** that DB,
  then ran `scripts/pft_volume_preflight.py`. It passed exactly: the M0 volume
  identity matched and no running container mounted it. Started only the new
  `pft-runtime` DB against the same external volume. The old container remains
  `exited` with restart `no`; `pft-runtime-db-1` is the sole running volume
  owner, healthy, with no published DB port.
- Ran the explicit `python -m api.migrate_once` once in a one-off API container;
  exit 0. Production now has 15 public tables, including `sync_runs`,
  `sync_item_runs`, and `sync_runtime_state`. The read-only post-migration
  legacy-column fingerprint matched all 12 frozen table counts/hashes,
  institution/source breakdowns, and integrity checks. The new sync tables
  have zero rows. No jobs container is running.

## API, UI, analytics, and checkpoint

- Started API and web only. Both and the DB are healthy. The web port is bound
  to `127.0.0.1:3000`; the API and DB have internal ports only. Through the
  actual localhost web proxy, `GET /api/pft/sync/status` returned 200 with the
  same five active institutions, `jobs.status=stopped`, no current/published
  run, and `backup.status=never`. The latter is expected until the scheduler
  performs its first recorded backup; the manual checkpoint below is stored
  separately. Overview, Review, and Memberships HTML routes returned 200,
  with the sync/backup health section in the rendered shell. Monthly,
  institution-breakdown, and membership analytics GETs returned 200. No
  mutation route was called. This is HTTP/read-only UI-route validation, not
  an interactive browser session.
- Production monthly net-spending totals through the web proxy matched the
  preflight restored-app baseline: June 2026 `12225.97`, July `4867.08`,
  August `4282.40`, and September `140.09`. Each matched `gross_spending -
  refunds - reimbursements - card_benefits`; August institution breakdown
  summed to `4282.40`. The earlier isolated old/new app comparison also
  matched monthly, institution, and membership hashes for its tested periods.
- Used a one-off `jobs` **command override** to run only
  `python -m api.backup create --kind extra`; it did not launch the scheduler.
  The migrated-state checkpoint is
  `pft-extra-20260923T200127978681Z.dump` with its JSON manifest in the
  protected Windows `Production` directory. The archive is 465,232 bytes,
  SHA-256 `40a6ae8897eb64ac24aef7abfdfe5030eade1ba1caea130be5ac06c207075fdc`;
  manifest schema SHA-256
  `1b519f776315625c5b0e2a3bdaf8cb4b44b6e0c22e3cc008e2a35d5847fe68b1`,
  app commit `2b413550433e83db151ef1f62ad98b26d70fbd9e`. Size/checksum,
  archive listing, and both Windows ACLs passed. Restored the **exact** archive
  into another new isolated port-55440 database; restore exited 0, all 15
  tables appeared, and its 12 legacy preservation fields produced the same
  canonical digest above. No Production restore was performed.

Preflight gates recorded in `PFT_M6_PREFLIGHT_2026-09-23.md`: backend 235
passed with no required skips, frontend 28 passed, TypeScript typecheck and
production builds passed, and `git diff --check` passed. The stage-1 commands
made authorized Production schema writes only. No Production sync/cursor
advancement or Plaid call occurred. Jobs, startup catch-up, the two daily
cycles, restart/sleep/offline recovery, and interactive UI validation remain
for M6 after separate authorization. **Stop here for Approval Point 2.**
