# M6 Production initial sync: Approval Point 3 evidence (2026-09-23)

This records the explicitly approved first Production jobs start and startup
catch-up after the [stage-1 cutover](PFT_M6_CUTOVER_STAGE1_2026-09-23.md).
It does **not** include restart, sleep/resume, or offline/recovery testing, or
the two normal daily cycles. Those remain behind Approval Point 3.

## Scope and backup-first startup

- Immediately before starting jobs, `pft_production_backfill` contained one
  user, exactly five active/unpaused Items, no other eligible Items, and zero
  sync runs. Item/account scope was unchanged: American Express 2 enabled
  accounts, Bank of America 1, Capital One 2, Chase 3, Robinhood 1 enabled
  and 4 disabled. The old `personal-finance-tracker-db-production-backfill-1`
  remained exited with restart `no`; `pft-runtime-db-1` was the sole running
  owner of `personal-finance-tracker_pgdata_production_backfill`. There was no
  existing jobs container or unexpected DB writer session.
- Started only `pft-runtime-jobs-1` using the approved runtime Compose files
  and existing private env files. The initial tick created the required daily
  backup **before** the sync run began. Archive
  `pft-daily-20260923T200743126960Z.dump` was created at
  `2026-09-23T20:07:43.126960Z`; the sync run started at
  `20:07:43.318650Z`. The archive is 465,304 bytes, SHA-256
  `5d1e5d0128e5c8976c9a0d7ca7ab311d00cbb413ce16f021735b84752727477d`.
  Its manifest size/checksum matched. The runtime recorded a successful
  backup at `20:07:43.095395Z` with no backup error, and the status API showed
  `backup.status=healthy`.

## Startup catch-up and publication

- The sole startup catch-up run was triggered by `jobs`, not by a manual
  request. Run `a2366920-bdf0-475a-8c96-e39216c14b06` finished at
  `20:07:49.766871Z` with `status=success`,
  `classification_status=success`, 2,564 classified rows, no error category,
  and a publication timestamp. All five `sync_item_runs` had
  `status=success`, `phase=published`, one page, and zero retries:

  | Institution | Added | Modified | Removed |
  | --- | ---: | ---: | ---: |
  | American Express | 32 | 0 | 2 |
  | Bank of America | 0 | 0 | 0 |
  | Capital One | 6 | 0 | 0 |
  | Chase | 41 | 0 | 3 |
  | Robinhood | 14 | 2 | 1 |

- Cursor digests compared with the isolated pre-sync checkpoint changed for
  the four Items with transaction changes; Bank of America's successful no-op
  retained its cursor. No cursor value was printed. The durable publication
  marker and proxied `/api/pft/sync/status` both identified this run; status
  showed jobs running, backup healthy, five active institutions, their latest
  outcomes, and no error category. A final audit still showed exactly one
  successful run, five published Item outcomes, the unchanged five-Item scope,
  and one running Production-volume owner.

## Preservation and analytics

- Snapshot-consistent post-sync fingerprinting showed the expected 93 added
  raw and normalized rows: both tables went from 2,517 to 2,610 rows. Six
  Plaid rows were marked removed. All 13 account rows, consumer-scope and
  legacy evidence rows, statement batch/rows, and every manual classification,
  category, label, and benefit override retained its pre-sync full-row hash.
  Item identity/account scope was unchanged. All checked ownership,
  normalized-account, statement-evidence, and Plaid/statement-link integrity
  counts remained zero.
- Read-only web-proxied analytics returned 200. June, July, and August 2026
  net spending stayed `12225.97`, `4867.08`, and `4282.40`; September updated
  from `140.09` to `4421.50`. Each month satisfied `net_spending = gross -
  refunds - reimbursements - card_benefits`. August and September institution
  breakdowns summed exactly to their respective monthly net totals. Their
  category breakdowns summed to net spending **plus** card benefits, as
  designed because benefits are shown separately. The trailing-12-month
  Membership net cost was `2016.60`; both its component equation and the sum
  of account net costs less unallocated reimbursements reconciled. September
  showed 11 unclassified transactions available for Review; the committed
  classification run itself succeeded.

## Post-sync recovery point and browser

- Created the separate post-sync `extra` checkpoint with the backup-only
  one-off command. Archive `pft-extra-20260923T200938146309Z.dump` is 486,775
  bytes, SHA-256
  `49a5e23ae5bd81746d6ed4c1e0e0afaf0027d7cbe596dedbda1fdc7cc87cc4a9`.
  Its manifest, archive listing, size/checksum, and restricted Windows ACLs
  passed. Restored that exact archive with `--exit-on-error --no-owner
  --no-privileges` into a **new isolated** PostgreSQL 16 database on port
  55440. After normalizing both read-only fingerprint sessions to UTC, all 15
  table counts and hashes, institution/source breakdowns, and integrity
  results matched the published Production snapshot exactly. The canonical
  preservation digest was
  `2cc2448c6f0a7e43adf8661de1e52071787f70d0ae97cbdd0e97912f0863ff2e`.
  The initial apparent mismatch in four timestamp-bearing tables was only
  server timezone rendering (Production UTC, isolated server America/New_York);
  the hash-only helper now sets UTC explicitly. No Production restore occurred.
- A temporary headless Windows Chrome session loaded the **real hydrated**
  Overview, Memberships, and Review pages against localhost. Each displayed
  jobs running and backup healthy with the five institutions. Overview showed
  the new September data; selecting August and Gross Spending loaded the
  expected category view. A browser focus event fetched status and analytics
  again while preserving that month/category choice. Memberships showed the
  reconciled total, advanced to page 2 of 115, and retained page 2 and period
  across focus refresh; its Charges filter worked. Review loaded the needs-
  review list, switched to Credits & Transfers, applied direction `all`,
  advanced to page 2 of 719, and retained page/filter across focus refresh;
  the effective-type filter worked. No edit or sync button was used. During a
  separate 47-second browser observation, a status request fired from the
  45-second poll and the health panel remained healthy. The temporary Chrome
  instance was closed afterward.

No stop condition was met. Jobs remain running for normal operation. **Stop
here for Approval Point 3** before any restart, sleep/resume, offline/recovery,
or second/third daily-cycle acceptance tests.
