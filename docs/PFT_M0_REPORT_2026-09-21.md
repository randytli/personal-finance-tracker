# M0 local facts and baseline — 2026-09-21

**Gate status: M0 technical verification complete and explicitly accepted by the user on 2026-09-22.** Database identity, backup/restore, analytics, independent key recovery, protected Windows-host storage, and encrypted USB copy checks passed. This acceptance is not authorization for Production writes or Plaid calls; the user explicitly directed that M1 not begin in this session.

## Identity and boundary

- Code: `main` at `dd4622b85e03054de838a1c764608d14ad6008c6`; `git status --short --branch` showed no uncommitted changes before this report.
- Docker context: `default`. Running PostgreSQL containers were `personal-finance-tracker-db-production-backfill-1` (127.0.0.1:5434), `personal-finance-tracker-db-production-pilot-1` (127.0.0.1:5433), and `personal-finance-tracker-db-1` (5432). The backfill container has Docker Desktop's WSL `Ubuntu` label.
- Source database: `pft_production_backfill` in `personal-finance-tracker-db-production-backfill-1`, Compose project `personal-finance-tracker`, service `db-production-backfill`, configuration `docker-compose.yml`, environment file `.env.backend.production-backfill.local`. Its named volume is `personal-finance-tracker_pgdata_production_backfill`, mounted at `/var/lib/postgresql/data` (Docker source path `/var/lib/docker/volumes/personal-finance-tracker_pgdata_production_backfill/_data`). The pilot and default databases use distinct containers and volumes.
- The backfill env file contains `DATABASE_URL`, `EXPECTED_DATABASE_NAME`, `PFT_BACKFILL_DB_NAME`, and `PLAID_TOKEN_ENCRYPTION_KEY`; values were not printed. Repository instructions show `docker compose --env-file .env.backend.production-backfill.local --profile production-backfill up -d db-production-backfill`. Sanitized shell history shows the API launch sequence `set -a`, `source .env.backend.production-backfill.local`, `set +a`, then `.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000` (history lines 1455–1458 and 1459–1462). Running-process environment and command match that sequence, although shell history alone has no process timestamp.
- No Production write, Plaid call, runtime restart, migration, or Compose reconfiguration was performed. Source access was `pg_dump` and aggregate `SELECT` only.
- The running API command is `uvicorn api.main:app --host 127.0.0.1 --port 8000`. Its sanitized environment targets `127.0.0.1:5434/pft_production_backfill` with `PLAID_ENV=production`; `DATABASE_URL`, expected database name, user ID, and encryption key exactly match `.env.backend.production-backfill.local`. Values were not printed.

## Backup and isolated restore

- Source dump: `/tmp/pft-m0-20260921.dump`, PostgreSQL 16 custom format, 420,627 bytes, created 2026-09-21 21:28 local time. SHA-256: `74429c03352b517e209b2d89e862b6c6fd61c68e48195518bd17d2aed6627be0`. File mode was set to `0600`; `pg_restore -l` parsed the archive. Application commit was `dd4622b85e03054de838a1c764608d14ad6008c6`. No global schema-version table was found; the archive's schema-only SHA-256 is `efd9faa933ee6c452386c1043cc0293dc8c2366c09ef54ca640e114fe7c4ce22` as a baseline schema identity.
- Restore target: new `pft_m0_restore_20260921` database in the separate `personal-finance-tracker-db-1` development container and its separate `personal-finance-tracker_pgdata` volume. `pg_restore --exit-on-error --no-owner --no-privileges` completed successfully. No source roles or Production objects were changed. Ownership and grants were deliberately not restored; a recovery runbook must recreate required roles.
- A second restore into a new `/tmp` PostgreSQL cluster and `pft_m0_restore_local_20260921` database succeeded. Its database default was set read-only before application checks. Collation-stable raw, normalized, cursor, statement-row, and override fingerprints matched exactly between both isolated restores.
- A host copy at `C:\Users\tianr\PFTBackups\pft-m0-20260921.dump` is outside the PostgreSQL volume and Docker/WSL virtual disk. Its size, SHA-256, and archive listing match the original. Windows ACLs on directory and file grant full access only to the user, Administrators, and SYSTEM. NTFS `C:` had 90,070,949,888 bytes free when first checked. On 2026-09-22, the user ran `manage-bde -status C:` with sufficient Windows privilege and reported `Conversion Status: Fully Encrypted`, `Percentage Encrypted: 100.0%`, and `Protection Status: Protection On`. Codex's own read-only `manage-bde` attempt remained access-denied without Windows administrator rights, so the encryption-state evidence is user-verified rather than tool-observed.
- The user created `C:\Users\tianr\PFTBackups\pft-m0-20260921-encrypted.rar`, reported password encryption with its password independently stored in iCloud Passwords, then closed/reopened the recovery path and used the independently retrieved password to extract the dump into `C:\Users\tianr\PFTBackups\M0-Restore-Test`. Codex did not receive the password. The extracted dump's SHA-256 was tool-verified as the original dump hash above. The host archive is 382,686 bytes, with SHA-256 `91c34917b0c01695cd5e9b35133e257e13e454479777aee12470da5fe01113cd`; its Windows ACL grants access only to the user, Administrators, and SYSTEM. The user copied only this encrypted archive to removable FAT32 USB drive E:. Codex independently verified `E:\PFT Backups\pft-m0-20260921-encrypted.rar` is the same size and has the same SHA-256. Password encryption and independent password retrieval are user-reported; the file and hashes are tool-observed.
- Snapshot/restore contained five active Items, all with cursors; accounts enabled/disabled by Item: Chase 3/0, Robinhood 1/4, American Express 2/0, Capital One 2/0, Bank of America 1/0. No pending or disabled Items appeared in this snapshot. Explicit stored ownership checks are recorded below.
- Raw and normalized rows: 2,517 each. Raw by Item: American Express 1,478; Bank of America 71; Capital One 35; Chase 662; Robinhood 271. Raw source/removal: Plaid 2,346 active rows dated 2024-09-03 to 2026-09-12; statement 171 active rows dated 2026-02-04 to 2026-07-21; no removed rows in the restore.
- Statement evidence: one applied `robinhood-gold-card` import batch and 171 statement rows. Manual override row counts: classification 59, category 164, label 27, benefit 8. Current source aggregate `SELECT` returned the same Item, raw, normalized, statement-row, and classification-override counts after the dump; this is a later live check, not a backup-consistent fingerprint.
- Raw signed amount totals in the restore for recent months: 2026-09 −664.13; 2026-08 110643.02; 2026-07 −1414.52; 2026-06 −5605.63. These are **not** the application's principal analytics totals.
- Detailed restored provenance check: all 171 statement rows have `new` disposition and nonempty canonical and source-evidence JSON. No raw/account Item ownership mismatches, normalized/raw account mismatches, statement batch/account Item mismatches, orphaned statement rows, or Plaid rows with statement IDs were found. Stored ambiguity/ownership checks passed; Plaid authorization status was not queried.
- A later live-source fingerprint check matched the backup for raw rows, normalized rows, cursors, and statement rows. Its override fingerprint differs despite unchanged override counts. The restored archive is the consistent baseline; the later live override state must not be represented as the snapshot.

## Runtime and recovery evidence

- Local loopback ports are 3000 (Next.js 15.5.24 using `next dev --hostname 127.0.0.1`), 8000 (uvicorn), 5433 (pilot), and 5434 (backfill). Compose currently runs databases, not web/API containers. `next.config.js` defaults its proxy to `http://127.0.0.1:8000`. Existing API `/ping` and web `/api/pft/analytics/monthly?month=2026-08` each returned HTTP 200. `api/main.py` calls `init_db()` at startup, so no app was started against Production for M0.
- Docker Desktop 29.7.2 runs through WSL Ubuntu. The backfill container uses restart policy `unless-stopped`. Windows HKCU Run contains Docker Desktop, while Docker's `settings-store.json` reports `AutoStart: false`; these indicators disagree. No Docker-specific scheduled task was found. Windows booted 2026-09-21 10:49, with a service-start event at 10:49:25. Nothing establishes whole-app login startup.
- Windows Kernel-Power 42/107 event pairs show historical sleep/resume on September 15, 16, 18, and 19. They do not prove application recovery after sleep. Disruptive restart and sleep/resume testing belongs to later runtime acceptance.
- The host encrypted archive and the verified encrypted USB copy provide an external recovery path for this baseline. The host dump and extracted restore-test dump remain in `C:\Users\tianr\PFTBackups`; their contents are plaintext files, protected at rest by the now fully encrypted C: volume and restricted directory/file ACLs. The removable copy contains only the password-encrypted archive. `/tmp` had about 949 GiB free, but its dump alone would not meet the off-WSL requirement.
- No classification recomputation ran against Production. Pure `build_classifications` on 2,517 eligible restored rows took 0.1547, 0.1555, and 0.1545 seconds in three runs, yielding 2,517 outcomes and 36 refund matches. This excludes future database/locking cost.

## Restored analytics and key check

Baseline analytics functions ran directly against the second isolated restore after asserting its exact database name and `default_transaction_read_only=on`. Jobs were absent, no API startup was used, and no Plaid network call occurred. The configured local key decrypted all five restored encrypted access tokens; the script printed only `5 of 5` success, not keys or plaintext tokens.

The user then retrieved the independent recovery copy from iCloud Passwords and ran `/tmp/pft_m0_verify_independent_key.py` themselves. Its command explicitly removed `PLAID_TOKEN_ENCRYPTION_KEY` and `DATABASE_URL` from the child environment, did not source either Production env file, and prompted through `getpass` with hidden terminal input. It hard-coded the isolated `pft_m0_restore_local_20260921` database over a user-only Unix socket and checked `default_transaction_read_only=on` and five encrypted Items before accepting input. The user reported `PASS`, meaning all five restored tokens decrypted with the independently retrieved key. Codex did not receive or observe the key or plaintext tokens; the result is recorded as user-reported rather than tool-observed.

| Month | Gross | Refunds | Reimbursements | Benefits | Net spending | Income | Unclassified |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-06 | 17,563.46 | 114.03 | 5,000.00 | 223.46 | 12,225.97 | 4,439.34 | 0 |
| 2026-07 | 5,470.42 | 474.78 | 0.00 | 128.56 | 4,867.08 | 5,423.56 | 0 |
| 2026-08 | 5,658.16 | 784.72 | 333.00 | 232.26 | 4,308.18 | 5,517.78 | 1 |
| 2026-09 | 152.09 | 12.00 | 0.00 | 0.00 | 140.09 | 0.00 | 0 |

Each net total reconciles as `gross − refunds − reimbursements − benefits`. The August institution breakdown returned seven groups. Trailing-12-month Membership through August returned five accounts, 113 transactions, gross charges 2,636.67, refunds 10.65, benefits 438.02, and net cost 2,188.00. These are restored-snapshot analytics totals; raw signed amount sums above are not equivalent.

## Final M0 criterion assessment

| Required M0 fact | Assessment | Evidence or limit |
| --- | --- | --- |
| Code identity and uncommitted state | Pass | Branch/commit and worktree state recorded above; only this M0 report was added. |
| Docker engine and running containers | Pass | Docker Desktop/WSL, context, version, three distinct database containers and ports recorded. |
| Exact Production database/volume | Pass | Backfill DB, Compose project/service, port, mount path, and distinct pilot/development identities recorded. |
| Environment loading | Pass | Env-file paths, documented Compose command, sanitized shell-history API launch sequence, running command and effective DB/config match; no secret values printed. |
| Item/account scope | Pass | Five active Items, per-Item enabled/disabled accounts, common user ownership, no pending/disabled Items. |
| Data baseline | Pass | Snapshot raw/normalized counts and Item/source date ranges, removal state, override counts and restore fingerprints, principal monthly totals recorded. |
| Cursor state | Pass | All five cursors present; no values exposed or unexplained missing cursor. |
| Statement provenance/blockers | Pass within M0 boundary | Applied batch, 171 evidenced rows, no stored ownership/overlap anomaly; live Plaid authorization was deliberately not queried. |
| Independent key recovery | Pass, user-reported | Independently retrieved iCloud Passwords key produced verifier `PASS` against five restored tokens with env key unset; no key/plaintext exposed. |
| Backup feasibility and protection | Pass, C: encryption user-verified | Consistent dump, host/USB checksums, free space, restricted ACL, verified encrypted external copy, and user-reported `manage-bde` result showing C: fully encrypted with protection on. |
| Isolated restore/reconciliation | Pass | Two separate restore targets, identical stable fingerprints, restored counts/provenance/cursors and analytics; Production source was untouched by M0. |
| Restored baseline application | Pass | Baseline analytics functions read exact isolated read-only DB; jobs were absent and no Plaid call path was invoked. API startup with `init_db()` was avoided. |
| Existing runtime facts | Pass | Current ports/proxy, login-start indicators, and historical sleep/resume evidence recorded. Disruptive recovery tests are later milestones. |
| Classification cost | Pass | Three pure calculation timings on isolated restored rows; no Production recomputation. |

**Remaining mandatory M0 blockers: none.** The former host-storage blocker was resolved by completing Windows Device Encryption on C: with protection on, as verified and reported by the user. The ACL, space, archive integrity, external encrypted copy, and isolated recovery evidence remain recorded above. The two host dump files need no deletion for M0 because they now reside on the encrypted C: volume under restricted ACLs.

The verified USB copy supplies the encrypted external medium for this M0 baseline. The proposed ongoing external-copy procedure is weekly password-encrypted archives, with independent password recovery and host/USB SHA-256 comparison; implementation and retention automation belong to M3. Cluster-role creation, full runtime startup, and disruptive restart/sleep tests also belong to later milestones.

## Human acceptance

On **2026-09-22**, the user stated: “I have reviewed the completed M0 report and its supporting evidence. I explicitly accept M0.” This records the explicit human acceptance required by the Phase 1 architecture plan. The user also directed that M1 not begin in this session. No M1 work began, and any later Production writes or Plaid calls still require their explicitly authorized scope.
