# Release packet DRAFT — main @ ba763ab to local Production, 2026-10-09

**Draft only. Nothing in this document has been executed.** Every [STATE] step needs the owner's approval at execution time, one command at a time.

Owner review of 2026-10-09 is folded in (decisions 1–4 and the three procedure fixes).

## What would be released

The release is pinned to commit **`ba763ab`**. Do not follow `main` at execution time: later commits on main are out of scope for this packet.

| Area | Running in Production now | `ba763ab` adds |
| --- | --- | --- |
| api `6f6d9560` | code of `b646fb9` (2026-10-02 sync diff-writes) | custom labels API (`labels.py`, `label_schema.py`, `routes/review.py`, `routes/analytics.py`); R10 recovery of `running` runs and the reused-backend lock guard (`sync_all.py`, `sync_state.py`); S7 commit after owner checks; R13 bucketed classification; R17 lazy `api.db`; `trigger_auth.py` (M5, not mounted) |
| jobs `7120adde` | `b646fb9` + `api/jobs.py` from `544beb4` (backup errno logging) | the same `api/` changes as api |
| web `9d7e0e22` | `47183eb` (category donut) | custom labels UI |
| db | schema of `b646fb9` | **label schema migration** |

Not shipped: `experiments/`, most of `scripts/`, `deploy/backup_runner/` and docs. `Dockerfile.jobs` copies only `api/`, `statement_imports/*.py` and `scripts/pft_dining_migration.py`.

## Constraints that shape the procedure

- **New binaries refuse to start before the migration.** `verify_runtime_schema()` requires the label tables, the 4 guards and the validated FK `fk_manual_transaction_label` ([custom labels](CUSTOM_TRANSACTION_LABELS.md)).
- **The migration has no down path.** Rollback after the migration is roll-forward, or a restore to an isolated target with old images, under separate approval ([merge review, rollback limits](CUSTOM_LABELS_MERGE_REVIEW.md)).
- **Kept old image tags do not make rollback safe.** The old api, jobs and web have **not** been verified against the new schema.

## Owner decisions (2026-10-09)

1. **main ships alone; lifecycle gets its own window.**
   - The two releases carry different migrations: a label migration here, an `items` table rewrite in lifecycle. Separate windows keep diagnosis and recovery decisions simple.
   - After main is accepted, lifecycle's D15 rehearsal is **re-run on a backup taken after the label migration**. The old-schema result does not carry over.
2. **Rebuild api, jobs and web from `ba763ab`.**
   - Reason: code, dependencies and the schema contract stay consistent across all three. (Not "too many files for an overlay".)
   - Build and image verification happen **before** the maintenance window. Inside the window, only backup, migration, switchover and acceptance.
   - The Dockerfiles use floating base tags (`python:3.12-slim`, `postgres:16`, `node:22-alpine`), and `api/requirements.txt` pins only 6 direct packages, with no transitive lock. So a rebuild does not guarantee identical versions. Each image is checked individually against the running image (step P3).
3. **Window: an attended daytime slot, e.g. 14:00–16:00 UTC (10:00–12:00 EDT).**
   - Recent sync times (about 00:38 and 03:05 UTC, plus or minus 2 h) give an avoid-zone of 22:38–05:05 UTC. The daily backup runs near 20:32 UTC.
   - These are **not** fixed cron times. Due time is the last success + 24 h, and a retry deadline can override it. Step W0 re-derives all of this on the day.
4. **Keep the old versions.**
   - Pins and rollback tags stay until the **latest** of three points: acceptance; one full daily sync cycle plus one new-version backup/restore check passing; and 7 days.
   - Pin files are small; archive them indefinitely. Images and the pre-migration backup are cleaned up separately, by explicit decision.
   - The pre-migration backup taken in the window is kept.

## Procedure

### Before the window (no Production writes)

| Step | Kind | Action |
| --- | --- | --- |
| P0 | LOCAL | Check out exactly `ba763ab` in a clean worktree. CI must be green on `ba763ab` |
| P1 | STATE (image tags only) | Tag the running images `rollback-<date>-{api,jobs,web}` (stop if a tag exists). Copy the current pin file into a new release directory (mode 0700) |
| P2 | STATE (new images only; containers untouched; `:latest` not moved) | Build api, jobs and web from the `ba763ab` worktree without pins. Record the image IDs in `new-images.yml` |
| P3 | READ-ONLY (throwaway containers, `--network none`) | For each new image against its running counterpart: base image digest; Python version and full `pip freeze` diff (api, jobs); `pg_dump`/`pg_restore` versions (jobs); Node version (web). **Sources:** for api and jobs, check the packaged `/app` files byte-for-byte against `ba763ab`. The web final image holds only `.next`, `node_modules` and the package files, with no TSX. So for web, check the build inputs at `ba763ab` (the `Dockerfile.web` COPY set and `package-lock.json`), `npm ls` from the image against the lockfile, and record a build-output manifest (hashes of `.next/BUILD_ID` and the server and static file list). Import check as uid 1000 (api, jobs). **Every difference must be listed and accepted by the owner before the window** |
| P4 | STATE (isolated DB only) | Restore a recent backup into an isolated `pft_restore_*` database, then run the migration there with the new api image, and record the duration. Then READ-ONLY checks: FK, guards, audit rows, and a legacy-column fingerprint comparison (as in W6) |

### In the window

| Step | Kind | Action |
| --- | --- | --- |
| W0 | READ-ONLY | **Scheduling recheck:** no `running` run; no pending manual request (`requested_sequence > handled_sequence`); no Item due within the window plus recovery time, counting `next_sync_retry_at`; daily backup not due within the window. Otherwise stop and pick another slot |
| W1 | STATE | **Freeze all writers.** Stop jobs and api (all 21 API write routes, including statement imports, are behind api). Confirm that no operator script (`pft_dining_migration`) or other client is connected: in `pg_stat_activity`, no client backends other than the read-only check itself, and none `idle in transaction`. web may stay up; it cannot write without api |
| W2 | READ-ONLY | **Final baseline after the freeze:** container IDs and images, `sync_runtime_state` (including `last_backup_at`), analytics fingerprints (`scripts/pft_m6_fingerprint.py`), label audit row counts, DB identity |
| W3 | STATE | Manual backup `api.backup create --kind extra`. Restore it into an isolated `pft_restore_*` DB (**a write**, isolated target) and compare its fingerprints with W2, ignoring the database name, which differs by design. The backup is kept |
| W4 | STATE (schema, irreversible) | Run `python -m api.migrate_once` from the **new** api image with the schema-owner configuration. Post-checks (read-only): validated FK, enabled guards, audit rows unchanged |
| W5 | STATE | Recreate api from the new pin (`--no-deps --no-build --pull never`) for **internal health checks only**: healthy within 120 s; logs show `verify_runtime_schema` passing and no migration. Do not route user traffic to it: **web stays stopped** (or in maintenance) and no client may call write routes. Recreate jobs **without starting it** |
| W6 | READ-ONLY | Writers are still frozen: web stopped, jobs stopped, api internal only. **Legacy data:** `scripts/pft_m6_fingerprint.py --columns-from <W2 output>` compares the old tables and columns with W2; they must be identical. **New schema, accepted separately:** the label definitions table exists with exactly the seeded system labels (CHINA, MEMBERSHIP) and no custom ones; FK `fk_manual_transaction_label` is validated; the 4 guards and 3 functions are present and enabled; existing override and audit rows are unchanged. Any unexplained difference stops the release |
| W7 | STATE (owner) | Recreate web from the new pin and start it; this ends the write freeze for the smoke tests only. Smoke tests through the UI on a **scoped** set chosen in advance: overview, review, single/bulk/archive labels. Label operations can leave permanent audit rows, so restoring the UI does not mean the database is unchanged. Record every row each action wrote (tables, ids, audit entries) |
| W8 | STATE | Start jobs. Then check only the run-state fields that may change: heartbeat advancing, no `Jobs tick failed`. Backup expectation from W2's `last_backup_at`: if it is ≥ 24 h old, the first tick runs the daily backup, which must succeed (the extra backup in W3 does **not** update `last_backup_at`). Sync expectation from W0's due list |
| W9 | LOCAL | Write the new full `running-images.yml`; move the `:latest` tags; update memory and the pin location |

## Rollback

- **Before W4:** recreate api, jobs and web from the current pins (`~/.local/share/pft/releases/2026-10-08-jobs-backup-log/running-images.yml`), then start jobs. The database is unchanged.
- **After W4:** prefer fixing forward. The old binaries are not verified against the new schema. A restore of the W3 backup needs an isolated target, old images, a separate approval, and an explicit decision about any writes after W3 (smoke-test rows from W7, syncs after W8).

## Stop conditions

Stop if any of these happens:
- any P3 difference not accepted by the owner, including any missing web build-input or manifest evidence;
- the P4 rehearsal fails;
- W0 finds anything due or running;
- a writer is still connected after W1;
- the W3 restore or its fingerprints differ;
- the migration errors, or its post-checks fail;
- api is not healthy within 120 s;
- any container other than the one targeted changes;
- any unexplained W6 difference.
