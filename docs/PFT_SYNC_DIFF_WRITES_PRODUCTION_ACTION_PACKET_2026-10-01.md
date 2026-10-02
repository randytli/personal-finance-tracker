# Sync diff-writes — local Production action packet — 2026-10-01

**Status: COMPLETE.** Phase 1 finished 2026-10-02 00:27 UTC and Phase 2 at 00:35 UTC. Both passed; see the [Phase 1](#phase-1-execution-record-2026-10-02) and [Phase 2](#phase-2-execution-record-2026-10-02) execution records. Every step marked as changing state requires the owner's explicit approval at execution time. Each phase's controlled sync makes a real Production Plaid call and Production financial writes; each needs its own approval.

Scope: deploy the [sync round-trip amplification fix](PFT_M5_SYNC_ROUND_TRIP_FIX_2026-10-01.md) (`a5f2dfd`, `b646fb9`) to the local Production runtime, Compose project `pft-runtime`, in **two phases**. Phase 1 recreates only `jobs`; Phase 2 recreates only `api` and `jobs`. `db` and `web` are not touched. There is no schema change and no migration.

- **Phase 1 — align jobs (owner-selected option 1, 2026-10-02).** Align the running images with `a047b0f4b32c2db23203fbab9b25cd5fe7678400`, the `main` commit before A/B. Step 0 found the API image already byte-identical to it, and the jobs image differing only in `api/labels.py`. So `api` is neither rebuilt nor recreated. `jobs` gets a **single-file overlay** on its running image (`FROM` the image ID, `COPY` that commit's `api/labels.py`), the same method as the card-fee release. Base image, Python and dependency versions stay unchanged.
- **Phase 2 — fix.** Only after Phase 1 verifies: merge A/B into `main` and deploy them with the same procedure. How Phase 2 builds its images is decided separately before Phase 2 starts. Recommended: the same single-file overlay of `api/services/derivation.py` on the then-running api and jobs images. A full `compose build` would pull an uncached `python:3.12-slim` base and could change unpinned transitive dependencies.

Authority: AGENTS.md, pft-safe-development, and existing Production practice in the [M1 action packet](PFT_PHASE_2_M1_PRODUCTION_ACTION_PACKET_2026-09-24.md), [M2 runtime](PFT_PHASE_2_M2_RUNTIME_2026-09-29.md), [M3 runtime/recovery](PFT_M3_RUNTIME.md), [M6 cutover](PFT_M6_CUTOVER_STAGE1_2026-09-23.md) and [card-fee release](PFT_CARD_FEE_MEMBERSHIP_DEPLOYMENT_2026-09-30.md).

Labels: **[READ-ONLY]** no state change. **[LOCAL]** changes only local Git or local files outside Production. **[STATE]** changes Production containers, images, backups or data, with the effect named. **[M]** measured; **[E]** estimate.

## Read-only baseline, 2026-10-01 (Appendix A1/A2)

Database `pft_production_backfill`, read-only session.

| Item | Value |
| --- | --- |
| Rows read by normalization per sync (active, consumer-enabled, not removed) | **2,615** [M]: 2,444 Plaid + 171 statement |
| Plaid payload, average | **1,565 B as text** / 1,556 B stored [M]. Statement payload: 182 B text [M] |
| Payload total read per sync | **3.86 MB as text** / 3.84 MB stored [M] |
| Sync runs in the last 30 days | 8, all `jobs` / `success`, one per day from 2026-09-23 to 2026-10-01, none on 2026-09-25 [M] |
| Sync duration | average **5.69 s**, maximum 6.61 s; classification average 1.31 s [M] |
| Last run / next due | 2026-10-01 19:35 UTC for all five active Items, no retries pending [M]. The next scheduled sync is due about 2026-10-02 19:35 UTC [E] |

The real Plaid payload is about 7.4× the 212 B synthetic payload used in the M5 cloud runs. Per-sync database transfer at today's size is therefore roughly 5 MB, not the 1.7 MB measured on the synthetic 2,610 fixture [E]. Schedule each phase well away from the daily run time.

Conclusion: with real payloads, current egress is about **150 MB per month** at one sync per day, and about **2 GB per month** at 35,600 retained rows [E]. Option C (incremental normalization) is therefore a quantified long-term optimization. It is not implemented now.

## Known issues

- **api and jobs may run different derivation logic — checked 2026-10-02, divergence limited to an unused path.** The running API image was produced by the card-fee release, which layered one file on an older image, and the jobs image came from the M3 dining release. Phase 1 step 0 compared all 34 `.py` files in each container with `a047b0f` [M]:
  - api is identical;
  - jobs differs only in `api/labels.py`, the pre-card-fee Membership description list (`1c2bcd9`). In jobs, that file is used only for `LABEL_CHECK`, which is identical in both versions. Membership label evaluation runs only in the API's analytics and review routes.
  - Derivation and classification code is therefore identical in both containers.
  - Installed packages (24) are identical in both containers and match `api/requirements.txt`.
  - Runtime versions: api Python 3.12.14; jobs Python 3.13.5 with `pg_dump` 16.15, matching the DB server.
- **`:latest` tags are stale; containers run pinned images.** Each Production container was created with release-packet override files that pin image IDs: the card-fee `current-images.yml`/`api-new.yml` for api, and the M3 dining `forward-images.yml` for jobs, plus the M4 `web-new.yml` for web. `pft-runtime-jobs:latest` (2026-09-23) and `pft-runtime-api:latest` (2026-09-29) are **not** the running images. Every `compose` command here therefore includes a pin file (`current-images.yml`) reproducing the running image IDs. A changed service gets an additional `*-new.yml`, and each change has a matching `*-rollback.yml`. `pull_policy: never` is set throughout.
- **Interrupted syncs.** Stopping jobs during a sync leaves a `running` run row until the next sync owner reconciles it (see the [M5 latency record](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md)). Stop jobs only when no sync or backup is running.

## Why jobs is stopped in each phase

In each phase, jobs is stopped **before** the pre-deploy fingerprints are taken. It is started again only **after** the post-deploy comparison is complete. This:

1. keeps scheduled syncs, the scheduler heartbeat and automatic backups from changing the database between the two fingerprints, so every difference can be attributed to the controlled sync;
2. prevents the scheduler from competing with the one-shot controlled sync for the `pft-sync` advisory lock. A losing one-shot would return `busy` and the phase could not be measured.

While jobs is stopped, `/sync/status` reports jobs as `stopped` and no automatic sync or backup runs. That is expected for the window.

## Fixed values and private evidence directory

Run from the repository root in WSL. Use the established Production Compose interpolation. Never print, copy or commit the env files.

```bash
export PFT_RUNTIME_ENV_FILE=.env.runtime.production.local
export PFT_DB_ENV_FILE=.env.runtime.db.production.local
export PFT_BACKUP_ENV_FILE=.env.runtime.backup.production.local
export PFT_BACKUP_HOST_DIR=/mnt/c/Users/tianr/PFTBackups/Production
export PFT_WEB_PORT=3000
export ALIGN_SHA=a047b0f4b32c2db23203fbab9b25cd5fe7678400
export STAMP=$(date -u +%Y%m%dT%H%M%SZ)
export P=/tmp/pft-sync-diff-writes-release-$STAMP       # private evidence; never commit
(umask 077; mkdir "$P" "$P/phase1" "$P/phase2")
export PFT_APP_COMMIT=pinned-by-override   # interpolation only; each jobs pin file sets the real value
# PH is the phase directory ($P/phase1 or $P/phase2). Its current-images.yml pins every service to the
# image ID that is running when the phase starts (generated from docker inspect, then reviewed).
compose() { env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime \
  -f compose.runtime.yml -f docker-compose.production.yml -f "$PH/current-images.yml" "$@"; }
```

Before any [STATE] step, confirm read-only that `compose config --images` resolves exactly the four running image IDs. Like the card-fee release, `env -u` keeps stale shell values for the HTTP allowlists from overriding the private env file.

Everything in `$P` (fingerprints, row hashes, transaction IDs, source diffs) is private. Keep it at mode 0600/0700, never commit it, and delete it after the retention decision.

## Stop conditions (both phases)

- Any failing test, any `compose config --quiet` failure, or tracked or untracked changes under the image paths (`api/`, `statement_imports/`, `scripts/pft_dining_migration.py`, the Dockerfiles, `api/requirements.txt`, `compose*.yml`).
- Phase 1 source differences not yet reviewed and approved by the owner. In Phase 2, any running-image difference other than `api/services/derivation.py`.
- At the start of either phase: a sync or backup is running, or the next scheduled sync is due in less than 2 hours (Appendix A2: earliest `last_sync_success_at` + 24 h, or any `next_sync_retry_at`).
- A sync is running or a backup is in progress when jobs would be stopped or api recreated.
- Backup verification fails, or a restored fingerprint differs from the source.
- Unexplained differences in a post-deploy comparison, especially in `raw_transactions`, manual override tables, statement tables or `accounts`.
- Any Review/Membership edit during the window. Ask for an edit freeze.

## Per-phase procedure

Both phases use the same steps. `<PH>` is `phase1` or `phase2`. `<SHA>` is `$ALIGN_SHA` in Phase 1 and `$MERGE_SHA` in Phase 2. `<TAG>` is `sdw-p1-pre-$STAMP` or `sdw-p2-pre-$STAMP`.

### Step 0 — Preflight [READ-ONLY, except where marked]

1. Git and source.
   - **Phase 1:** `git switch main` [LOCAL] and require `git rev-parse HEAD` = `$ALIGN_SHA`.
   - **Phase 2:** record `PRE_MERGE_SHA=$(git rev-parse HEAD)`, then run `git merge --ff-only m5-derivation-diff-writes` [LOCAL] and record `MERGE_SHA=$(git rev-parse HEAD)`. No push. If `--ff-only` refuses, stop. Require that `git diff --stat $ALIGN_SHA $MERGE_SHA` lists only `api/services/derivation.py` among the image paths.
   - Both phases: `git status --short -- api statement_imports scripts/pft_dining_migration.py Dockerfile.api Dockerfile.jobs api/requirements.txt compose.runtime.yml docker-compose.production.yml` must be empty, which rules out untracked `.py` files that `COPY api` would include. `.dockerignore` already excludes caches, env files, tests and docs.
   - Record the SHAs in `$P/<PH>/git.txt`. `export PFT_APP_COMMIT=<SHA>`.
2. Local tests: the full backend suite with all seven synthetic PostgreSQL opt-ins, on a disposable loopback cluster only.
3. `compose config --quiet`. Record containers:
   `docker inspect -f '{{.Name}} {{.Image}} {{.State.StartedAt}} {{.RestartCount}}' pft-runtime-api-1 pft-runtime-jobs-1 pft-runtime-web-1 pft-runtime-db-1 > $P/<PH>/containers-before.txt`
4. **Running containers versus `<SHA>`, per file (Appendix C).** Compare every `.py` file under `api/`, `statement_imports/` and `scripts/` in both running containers with the commit. Group differences by function. Also compare installed package versions with `api/requirements.txt`.
   - **Phase 1:** stop here and give the owner the grouped list. Continue only after approval.
   - **Phase 2:** the running containers are now the Phase 1 images. The only expected difference is `api/services/derivation.py`; anything else is a stop condition.
5. Status: `curl -s http://127.0.0.1:3000/api/pft/sync/status > $P/<PH>/status-before.json`. Require jobs `running`, backup `healthy`, `current_run.status` not `running`, five active institutions, and no backup in the jobs log since the last heartbeat.

### Step 1 — Stop jobs [STATE: scheduler stopped; no automatic sync or backup until step 8]

```bash
compose stop jobs
```

Re-check `/sync/status`: jobs `stopped`, no `running` run.

### Step 2 — Backup and restorability

1. **[STATE: writes one new backup file and manifest to the protected Windows Production backup directory]**
   Jobs is stopped, so use a one-off container with a command override. This is the M6 cutover pattern, and it does not start the scheduler. Because `compose()` includes `current-images.yml`, the one-off container uses the pinned running jobs image, not the stale `:latest`.
   `compose run --rm --no-deps -T jobs python -m api.backup create --kind extra | tee $P/<PH>/backup.json`
   The command validates the archive listing and publishes a SHA-256 manifest with schema fingerprint and application commit. `extra` has its own retention group (effectively unlimited) and does not prune daily/weekly/monthly checkpoints.
2. **[READ-ONLY]** Verify the manifest SHA-256 against the dump, and `/usr/lib/postgresql/16/bin/pg_restore -l <dump> > /dev/null`.
3. **Restorability [LOCAL: disposable cluster only; required in Phase 1, recommended in Phase 2].** Follow the [M0 baseline](PFT_PHASE_2_M0_BASELINE_2026-09-24.md) pattern:
   - initialize a new PostgreSQL 16 cluster in a private directory on `127.0.0.1:55439`;
   - restore with `pg_restore --exit-on-error --no-owner --no-privileges -d pft_restore_<STAMP> <dump>`;
   - run `scripts/pft_m6_fingerprint.py` against it under `env -i`, with only `DATABASE_URL`/`EXPECTED_DATABASE_NAME` pointing at the restore.

   **Pass:** every table count and hash equals the step 3.1 Production fingerprint. Jobs is stopped, so no table, including `sync_runtime_state`, should differ. Delete the cluster after comparison.

   Do not use `api.backup restore` for this check, because it creates the new database on the Production server.

### Step 3 — Pre-deploy fingerprints [READ-ONLY]

1. Full table fingerprints:

   ```bash
   docker exec -i pft-runtime-api-1 python - --output /tmp/pft-sdw-full-before.json < scripts/pft_m6_fingerprint.py
   docker cp pft-runtime-api-1:/tmp/pft-sdw-full-before.json $P/<PH>/full-before.json
   ```

2. Timestamp-free fingerprints. Build a reference that excludes `created_at`/`updated_at` from every table, then use `--columns-from`. *(`docker cp` writes one file into the API container's `/tmp`; no database change.)*

   ```bash
   python3 -c "import json,sys; f=json.load(open(sys.argv[1])); json.dump({'tables': {t: {'columns': [c for c in v['columns'] if c not in ('created_at','updated_at')]} for t, v in f['tables'].items()}}, open(sys.argv[2], 'w'))" $P/<PH>/full-before.json $P/<PH>/reference.json
   docker cp $P/<PH>/reference.json pft-runtime-api-1:/tmp/pft-sdw-reference.json
   docker exec -i pft-runtime-api-1 python - --columns-from /tmp/pft-sdw-reference.json --output /tmp/pft-sdw-before.json < scripts/pft_m6_fingerprint.py
   docker cp pft-runtime-api-1:/tmp/pft-sdw-before.json $P/<PH>/before.json
   ```

3. Classification digest (Appendix B1) → `$P/<PH>/classification-before.txt`.
4. Per-row hashes without timestamps (Appendix A3) → `$P/<PH>/rows-before.csv`.

### Step 4 — Preserve and build

**Phase 1 (jobs-only overlay):**

1. **[STATE: new image tag only]** `docker image tag "$(docker inspect -f '{{.Image}}' pft-runtime-jobs-1)" pft-runtime-jobs:sdw-p1-pre-$STAMP`. Stop if the tag exists. Api is untouched in Phase 1, so it needs no tag.
2. **[STATE: builds one new image; containers untouched]** The build context `$PH/overlay/` contains only `Dockerfile` (`FROM pft-runtime-jobs:sdw-p1-pre-$STAMP` / `COPY labels.py /app/api/labels.py`) and `labels.py` taken from `git show $ALIGN_SHA:api/labels.py`. Two rules learned in execution:
   - **`FROM` must name the local tag from item 1, never `sha256:<ID>`.** BuildKit treats an ID as a registry repository and tries docker.io.
   - **Both overlay files must be mode 0644 before the build.** `COPY` keeps the source mode, and the private directory's umask 077 produced a 0600 `labels.py` that the uid-1000 jobs process could not read.
   `docker build --pull=false -t pft-runtime-jobs:sdw-p1-align-$STAMP $PH/overlay`
   Write the new image ID into `$PH/jobs-new.yml`, from the template, with `PFT_APP_COMMIT: sdw-p1-a047b0f-labels-over-<old image ID>`. `$PH/jobs-rollback.yml` pins the old image and its original `PFT_APP_COMMIT`.
3. **[READ-ONLY]** For the new image:
   - all 34 `.py` files equal `$ALIGN_SHA` (Appendix C via `docker run --rm --entrypoint sh <image> -c '...'`);
   - `pip freeze`, Python and `pg_dump` versions are identical to the running jobs image;
   - `/app/api/labels.py` is `root:root 0644`, like the original;
   - its layers are the old image's layers plus exactly one;
   - as uid 1000 with `--network none` and a dummy `DATABASE_URL`, `python -c "import api.jobs, api.labels, api.models, api.services.sync_all, api.services.derivation, api.backup"` succeeds.

**Phase 2 (method decided before Phase 2; if full build):**

1. **[STATE: new image tags only]** Tag the exact running images. These are the containers' image IDs, not `:latest`; the API currently runs the card-fee release image. Stop if the tag already exists.

   ```bash
   docker image inspect pft-runtime-api:<TAG> pft-runtime-jobs:<TAG> >/dev/null 2>&1 && echo "tag exists; stop"
   docker image tag "$(docker inspect -f '{{.Image}}' pft-runtime-api-1)"  pft-runtime-api:<TAG>
   docker image tag "$(docker inspect -f '{{.Image}}' pft-runtime-jobs-1)" pft-runtime-jobs:<TAG>
   ```

   The jobs container is stopped but still exists, so its image ID is still available.
2. **[STATE: builds new `pft-runtime-api:latest` and `pft-runtime-jobs:latest` images; containers untouched]** Build **without** the pin file, because a pinned `image: sha256:…` cannot be a build tag: `env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime -f compose.runtime.yml -f docker-compose.production.yml build api jobs`. Record the new image IDs in `$PH/api-new.yml` and `$PH/jobs-new.yml`, and the running ones in the matching `*-rollback.yml`.
3. **[READ-ONLY]** Verify that both new images' `/app` sources equal `<SHA>` byte for byte. Use Appendix C with `docker run --rm --entrypoint sh <image> -c '...'`.

### Step 5 — Recreate api; recreate jobs without starting it

**Phase 1 [STATE: replaces `pft-runtime-jobs-1` with a new, stopped container from the overlay image; api untouched]:**

```bash
compose -f "$PH/jobs-new.yml" up --no-deps --no-build --pull never --force-recreate --no-start jobs
```

**Phase 2 [STATE: recreates `pft-runtime-api-1` (short API interruption); replaces `pft-runtime-jobs-1` with a new, stopped container]**. The new images are pinned with `$PH/api-new.yml` and `$PH/jobs-new.yml`:

```bash
compose -f "$PH/api-new.yml" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 api
compose -f "$PH/api-new.yml" -f "$PH/jobs-new.yml" up --no-deps --no-build --pull never --force-recreate --no-start jobs
```

Do **not** use the card-fee packet's `deploy-api.sh`; its rollback target predates both phases.

**[READ-ONLY]** The new jobs container is `created` with the expected image ID. API healthy (in Phase 1, the API container ID and start time must be unchanged). `curl http://127.0.0.1:3000/` and `/api/pft/sync/status` return 200, with jobs `stopped`. The API startup log shows read-only schema verification and no migration. Web and DB keep their container IDs, images, start times and restart counts; compare with `containers-before.txt`.

### Step 6 — Controlled sync

**[STATE: real Production Plaid `/transactions/sync` for all active Items; Production financial writes and cursor advance; separate explicit approval required]**

Run the one-shot entry point inside the new API container with a statement counter (Appendix B2). Jobs is stopped, so nothing competes for the `pft-sync` lock.

```bash
docker exec -i pft-runtime-api-1 python - < B2.py | tee $P/<PH>/sync-result.json
```

Record:
- total statements and statements by verb;
- wall time, plus `duration_ms` and `classification_duration_ms` for the returned `run_id`;
- per-Item added/modified/removed counts (Appendix A2, final queries).

Expected [E]:
- **Phase 1**, old write path: about 2 × 2,615 + constant ≈ 5,400 statements, plus about 2 per changed row.
- **Phase 2**: about 141 + about 2 per added/modified row + 1 per removed row. The constant depends on Item and account counts.

Production derived rows have been rewritten on every earlier sync, so Phase 2 should need no one-time convergence write. Phase 1, however, may legitimately rewrite derived values if the running jobs code differed from `$ALIGN_SHA` (see Known issues).

### Step 7 — Post-deploy comparison [READ-ONLY]

Copy `reference.json` into the new API container, repeat step 3 with `after` names, and compare:

| Object | Expected |
| --- | --- |
| `sync_runs`, `sync_item_runs`, `sync_runtime_state` | Changed (one new run, publication marker; heartbeat static while jobs is stopped) |
| `items` | Only `transactions_cursor` (if Plaid returned a new cursor) and `last_sync_*` / retry columns changed |
| `raw_transactions` (timestamp-free) | Identical except rows in this run's Plaid delta; every differing ID must be in the run's added/modified/removed set |
| `transactions` (timestamp-free) | Phase 2: identical except delta rows. Phase 1: the same, plus any derived-value changes explained by the reviewed code differences from step 0.4 |
| Classification digest | Phase 2: identical when the delta is empty. Otherwise, and in Phase 1, list every reclassified row (A3 fourth column, before/after) and attribute it to the delta or to a reviewed code difference |
| `accounts` | Identical, unless Plaid reported an unknown account (metadata refresh); explain it |
| Manual override, label, benefit, category, statement and legacy tables | Identical |
| Fingerprint integrity checks | All zero, as before |

In Phase 2, the full fingerprint should also show `transactions.updated_at` changing only on delta rows.

Write `$P/<PH>/comparison.md` with the result and the list of differing rows. An unexplained difference is a stop condition: keep jobs stopped, report, and decide on rollback (step 9).

### Step 8 — Start jobs [STATE: scheduler resumes; automatic syncs and backups resume]

Only after step 7 is complete and accepted:

```bash
compose start jobs
```

**[READ-ONLY]** Within about 60 s the heartbeat is fresh, `/sync/status` shows jobs `running`, and the jobs log shows no failed tick. Because the controlled sync updated `last_sync_success_at`, the next scheduled sync is about 24 h after it.

### Step 9 — Rollback for the phase

1. **Services [STATE: recreates api, and jobs if needed, from that phase's preserved tags]**

   Phase 1 (jobs only):

   ```bash
   compose -f "$PH/jobs-rollback.yml" up --no-deps --no-build --pull never --force-recreate --no-start jobs
   ```

   Phase 2 (api and jobs, back to the Phase 1 images):

   ```bash
   compose -f "$PH/api-rollback.yml" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 api
   compose -f "$PH/api-rollback.yml" -f "$PH/jobs-rollback.yml" up --no-deps --no-build --pull never --force-recreate --no-start jobs
   ```

   The rollback files pin the image IDs preserved by that phase's `sdw-p<N>-pre-$STAMP` tags; `:latest` is never used.

   Start jobs (step 8) only after verification. Phase 2 rolls back to the Phase 1 images (`sdw-p2-pre-*`). Phase 1 rolls back to the original images (`sdw-p1-pre-*`). Rolling back both phases means Phase 2's rollback first, then Phase 1's.
2. **Code [LOCAL; Phase 2 only]** Require `git status --short` to show no modified tracked files. Then `git switch main && git reset --hard $PRE_MERGE_SHA`. Nothing was pushed, and the branch keeps the commits. A non-destructive alternative is `git revert --no-edit $PRE_MERGE_SHA..$MERGE_SHA`. Phase 1 changes no Git state.
3. **Data.**
   - Both phases change only code that derives normalized and classification values. On the next sync, the rolled-back code re-derives every value, so derived columns re-converge without a restore.
   - Raw rows, cursors and manual decisions are written by code that the fix does not change.
   - Restore from that phase's backup **only** if the comparison shows unexplained damage to raw, override, statement or account data. Restore into a new `pft_restore_<STAMP>` database, verify fingerprints, and switch the runtime database only through a separately approved cutover following the M6 pattern. Never restore over the live database, and never use `docker compose down -v`.

## Phase 1 execution record, 2026-10-02

Owner-approved, in the order of the per-phase procedure. Private evidence: `/tmp/pft-sync-diff-writes-release-20261002T001220Z/phase1/`. All values [M].

| Step | Result |
| --- | --- |
| Preconditions (00:12 UTC) | No sync or backup running; last sync/backup 2026-10-01 19:35 UTC; next sync about 19 h away |
| 0 — source review | api: 34/34 `.py` identical to `a047b0f`. jobs: only `api/labels.py` differed (pre-card-fee, `1c2bcd9`), outside the jobs execution path. Packages identical. Owner chose option 1 (jobs-only overlay) |
| S1 — stop jobs (00:19:34) | No running run, no advisory locks |
| S2 — backup | `pft-extra-20261002T001945547083Z.dump`, 496,593 B, SHA-256 matches manifest, `pg_restore -l` lists 15 tables; manifest commit shows the pinned jobs image |
| Restorability | Restored into a disposable loopback cluster: all 15 table counts/hashes, institutions and integrity identical to Production; cluster deleted |
| 3 — pre-deploy fingerprints | 15 tables, integrity zero; 2,636 raw / 2,636 normalized row hashes; classification digest `4a570eb1…` |
| S3 — rollback tag | `pft-runtime-jobs:sdw-p1-pre-20261002T001220Z` → `sha256:b1ae3322…` |
| S4 — overlay | Two failed attempts, neither used by any container: (1) `FROM sha256:` rejected by BuildKit, nothing pulled or built; (2) image with a 0600 `labels.py`, caught by verification and replaced. Final `sha256:1d17e2b59fa4be74af41f60125f41084698049424e0b4d77376db1fe41cc74c7`: old layers + 1; 34/34 files equal `a047b0f`; packages, Python 3.13.5 and `pg_dump` 16.15 unchanged; uid-1000 imports pass |
| S5 — recreate jobs | Created, not started; user, command, restart policy and backup mount unchanged; api/web/db containers unchanged |
| S6 — controlled sync (00:24 UTC) | One-shot run `c029543d`, success for all 5 Items, Plaid delta 0/0/0. **5,374 SQL statements** (INSERT 2,622, UPDATE 2,639, SELECT 103, SAVEPOINT/RELEASE 5/5), wall 5.92 s, `duration_ms` 5,331, classification 1,375 ms, 2,615 rows normalized. This is the old-write-path Production baseline: 2 × 2,615 + 144 |
| 7 — comparison | All business tables identical without timestamps. Row level: 0 added / 0 removed / 0 changed / 0 reclassified; classification digest identical; integrity zero. `transactions` full hash differed only by `updated_at` (old path). Expected only: `sync_runs` +1, `sync_item_runs` +5; `items` `last_sync_attempt_at`, `last_sync_success_at`, `updated_at` (cursor unchanged); `sync_runtime_state` `last_published_run_id`, `published_at`. **PASS** |
| S7 — start jobs (00:27:29 UTC) | Heartbeat fresh within 1 s; status `running`; backup healthy; no log errors; restarts 0 |

Current pins for later phases: api `sha256:d5e5e8a3…` (unchanged), jobs `sha256:1d17e2b5…`, web `sha256:6ad6b7bc…`. Phase 2's `current-images.yml` must be generated from these running IDs. The next scheduled sync is due about 2026-10-03 00:24 UTC [E]. The next daily backup is about 2026-10-02 19:35 UTC [E], because the one-off extra backup does not update the scheduler's backup marker.

## Phase 2 execution record, 2026-10-02

Owner-selected build method: single-file overlay of `api/services/derivation.py` (same method as Phase 1) on the running api and jobs images. Owner-approved S0–S7, including the Plaid call. Private evidence: `/tmp/pft-sync-diff-writes-release-20261002T001220Z/phase2/`. All values [M].

| Step | Result |
| --- | --- |
| 0 — preflight (00:30 UTC) | Target `6ac9612`: among image paths, only `api/services/derivation.py` differs from `a047b0f` (content = `b646fb9`). Local suite 304 passed, 0 skipped. Both running containers differed from the target only in `derivation.py`; packages unchanged. Next sync about 24 h away |
| S0 — merge | Local `main` fast-forwarded `a047b0f` → `6ac9612`; not pushed |
| S1 — stop jobs (00:33:15) | No running run, no advisory locks |
| S2 — backup | `pft-extra-20261002T003316753226Z.dump`, 496,641 B, SHA-256 matches manifest, 15 tables; restore into a disposable cluster identical to Production in all 15 tables |
| 3 — pre-deploy fingerprints | 15 tables, integrity zero, classification digest `4a570eb1…` (unchanged since Phase 1) |
| S3 — rollback tags | `pft-runtime-api:sdw-p2-pre-20261002T001220Z` → `sha256:d5e5e8a3…`; `pft-runtime-jobs:sdw-p2-pre-20261002T001220Z` → `sha256:1d17e2b5…` |
| S4 — overlays | api `sha256:6f6d9560e50e91117307d01386af0f1073aa87f5e7788e77075b5f707b1acd7a`, jobs `sha256:838b2833a882699a942c61d53ed2aea67e3aeda1eb82e7f18636f82c11733098`. Each is the old layers + 1, with unchanged image config; 34/34 files equal the target; packages and Python unchanged; `derivation.py` `root:root 0644`; imports pass (jobs as uid 1000) and the diff-write functions are present |
| S5 — recreate | api healthy 6 s after recreation (`/` and `/api/pft/sync/status` 200; no migration). jobs created, not started; user, command and mounts unchanged; web/db unchanged |
| S6 — controlled sync (00:34 UTC) | Run `3a2aa3a6`, success for all 5 Items, Plaid delta 0/0/0. **144 SQL statements** (SELECT 103, UPDATE 24, INSERT 7, SAVEPOINT/RELEASE 5/5), wall 2.57 s, `duration_ms` 2,176, classification 61 ms. `normalized_count` 2,615 and `classified_count` 2,574 are unchanged from Phase 1 |
| 7 — comparison | Every business table identical **including full fingerprints with timestamps**: `transactions.updated_at` is no longer rewritten. Row level 0/0/0/0; classification digest identical; integrity zero. Expected only: `sync_runs` +1, `sync_item_runs` +5; `items` `last_sync_attempt_at`, `last_sync_success_at`, `updated_at`; `sync_runtime_state` `last_published_run_id`, `published_at`. **PASS** |
| S7 — start jobs (00:35:27 UTC) | Heartbeat within 1 s; status `running`; backup healthy; no log errors; all four containers restarts 0 |

### Production before/after, same data and zero Plaid delta [M]

| Metric | Old path (Phase 1 run) | Fixed (Phase 2 run) |
| --- | --- | --- |
| SQL statements | 5,374 | **144** |
| Wall time | 5.92 s | **2.57 s** |
| `duration_ms` | 5,331 | 2,176 |
| Classification | 1,375 ms | **61 ms** |
| Rows rewritten with no change | 2,636 (`updated_at`) | **0** |

### Running state and rollback after Phase 2

Running pins: api `sha256:6f6d9560…`, jobs `sha256:838b2833…`, web `sha256:6ad6b7bc…`, db `postgres:16`. The pin files are in the Phase 2 evidence directory (`current-images.yml` + `api-new.yml` + `jobs-new.yml`). **Any future recreation must use these pins or pins regenerated from the running IDs, never `:latest`.** These files contain image IDs only, but `/tmp` is not durable.

Rollback to the Phase 1 state:
- `compose -f "$PH/api-rollback.yml" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 api`
- `compose -f "$PH/api-rollback.yml" -f "$PH/jobs-rollback.yml" up --no-deps --no-build --pull never --force-recreate --no-start jobs`, then start jobs after verification.
- Local `git reset --hard a047b0f4b32c2db23203fbab9b25cd5fe7678400` on `main`, after checking for no tracked changes.

Derived data re-converges on the next sync under either code version.

## Appendix A — Read-only SQL

Run each inside the DB container, in a read-only session. Credentials stay inside the container environment.

```bash
docker exec -i pft-runtime-db-1 sh -c 'exec psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < A1.sql > $P/A1.txt
```

**A1 — raw payload size.** This covers the rows each sync's normalization reads (active Items, consumer-enabled accounts, not removed).

```sql
SET default_transaction_read_only = on;
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT current_database() AS database, current_setting('transaction_read_only') AS read_only;
SELECT coalesce(r.source, 'all') AS source,
       count(*) AS eligible_rows,
       round(avg(pg_column_size(r.payload))) AS avg_stored_bytes,
       sum(pg_column_size(r.payload)) AS total_stored_bytes,
       round(avg(octet_length(r.payload::text))) AS avg_text_bytes,
       sum(octet_length(r.payload::text)) AS total_text_bytes
FROM raw_transactions r
JOIN accounts a ON a.account_id = r.account_id AND a.item_id = r.item_id
JOIN items i ON i.item_id = r.item_id
WHERE NOT r.is_removed AND a.consumer_transactions_enabled AND i.status = 'active'
GROUP BY ROLLUP (r.source)
ORDER BY 1;
COMMIT;
```

`pg_column_size` is the stored, possibly TOAST-compressed, size. The text length is closer to what the driver receives per sync.

**A2 — actual sync frequency.** Configuration is in `api/jobs.py`: `SYNC_INTERVAL = 24 h`, `POLL_SECONDS = 60`. `api/services/sync_state.py` `due_items`: an Item is due 24 h after its last success, unless a retry deadline applies. `api/services/sync_all.py` `RETRY_DELAYS` are 15 min, 1 h and 6 h.

```sql
SET default_transaction_read_only = on;
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT trigger_source, status, count(*) AS runs,
       min(started_at) AS first_run, max(started_at) AS last_run,
       round(avg(duration_ms)) AS avg_ms, max(duration_ms) AS max_ms,
       round(avg(classification_duration_ms)) AS avg_classification_ms
FROM sync_runs WHERE started_at > now() - interval '30 days'
GROUP BY 1, 2 ORDER BY 1, 2;
SELECT date_trunc('day', started_at) AS day, count(*) AS runs,
       count(*) FILTER (WHERE published_at IS NOT NULL) AS published
FROM sync_runs WHERE started_at > now() - interval '30 days'
GROUP BY 1 ORDER BY 1;
SELECT institution_name, left(item_id, 6) AS item, status, sync_paused, last_sync_success_at,
       last_sync_change_at, next_sync_retry_at, sync_retry_count
FROM items ORDER BY institution_name, item_id;
-- After a controlled sync, for the returned run_id:
-- SELECT run_id, status, duration_ms, classification_duration_ms, classified_count FROM sync_runs WHERE run_id = '<RUN_ID>';
-- SELECT item_id, status, added_count, modified_count, removed_count, normalized_count FROM sync_item_runs WHERE run_id = '<RUN_ID>';
COMMIT;
```

**A3 — per-row hashes without timestamps** (private output; contains transaction IDs, not amounts or descriptions).

```sql
SET default_transaction_read_only = on;
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
\copy (SELECT 'raw', transaction_id, md5((to_jsonb(r) - 'created_at' - 'updated_at')::text) FROM raw_transactions r ORDER BY transaction_id) TO STDOUT WITH CSV
\copy (SELECT 'normalized', transaction_id, md5((to_jsonb(t) - 'created_at' - 'updated_at')::text), coalesce(transaction_type, '-') || '|' || coalesce(is_spending::text, '-') || '|' || coalesce(is_internal_transfer::text, '-') FROM transactions t ORDER BY transaction_id) TO STDOUT WITH CSV
COMMIT;
```

Diff the before/after CSVs by `(table, transaction_id)` to list added, removed and changed rows. The fourth column shows classification changes directly.

## Appendix B — Helper scripts

Create these inside `$P`; they are not committed.

**B1 — classification digest** (prints one SHA-256; read-only transaction):

```python
import asyncio
from sqlalchemy import text
from api.db import SessionLocal, engine
from api.routes.plaid import _user_id
from statement_imports.persistence import external_classifications

async def main():
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        print(await external_classifications(db, _user_id()))
    await engine.dispose()

asyncio.run(main())
```

**B2 — instrumented one-shot sync** (step 6 only; Production Plaid call):

```python
import asyncio, json, time
from collections import Counter
from sqlalchemy import event
from api.db import engine
from api.sync_once import run_once

verbs = Counter()

@event.listens_for(engine.sync_engine, "before_cursor_execute")
def count(connection, cursor, statement, parameters, context, executemany):
    verbs[statement.split(None, 1)[0].upper()] += 1

async def main():
    started = time.perf_counter()
    try:
        result = await run_once(allow_production=True)
    finally:
        await engine.dispose()
    print(json.dumps({"wall_s": round(time.perf_counter() - started, 3),
                      "sql_statements": sum(verbs.values()), "by_verb": dict(verbs),
                      "status": result["status"], "run_id": result["run_id"],
                      "published": result.get("published"), "items": result["items"],
                      "classification_duration_ms": result.get("classification_duration_ms")}))

asyncio.run(main())
```

The count includes `run_once`'s own preflight queries (about 3) and excludes protocol-level BEGIN/COMMIT.

## Appendix C — Per-file source comparison [READ-ONLY]

```bash
SHA=<SHA>   # $ALIGN_SHA in Phase 1, $MERGE_SHA in Phase 2
for svc in api jobs; do
  docker exec pft-runtime-$svc-1 sh -c 'cd /app && find api statement_imports scripts -type f -name "*.py" | sort | xargs sha256sum' > $P/<PH>/$svc-running.sha256
  docker exec pft-runtime-$svc-1 sh -c 'pip freeze 2>/dev/null || python -m pip freeze' > $P/<PH>/$svc-running.pip
done
git ls-tree -r --name-only $SHA -- api statement_imports scripts/pft_dining_migration.py | grep '\.py$' \
  | while read -r f; do printf '%s  %s\n' "$(git show $SHA:$f | sha256sum | cut -d' ' -f1)" "$f"; done > $P/<PH>/commit.sha256
for svc in api jobs; do diff <(sort -k2 $P/<PH>/$svc-running.sha256) <(sort -k2 $P/<PH>/commit.sha256) > $P/<PH>/$svc-diff.txt; done
```

To check a newly built image that is not running (step 4.3), use `docker run --rm --entrypoint sh <image> -c '...'` instead of `docker exec`.

For each differing, missing or extra path, record `diff -u <(docker exec pft-runtime-<svc>-1 cat /app/<path>) <(git show $SHA:<path>)` and the commits that touched it (`git log --oneline -- <path>`). Group the results for review:

| Group | Paths |
| --- | --- |
| Derivation and classification | `api/services/derivation.py`, `api/classification*.py`, `api/statement_semantics.py`, `api/card_benefits.py`, `api/categories.py`, `api/benefit_categories.py`, `api/labels.py`, `api/services/category_attribution.py`, `api/services/dining_migration.py` |
| Sync, persistence and scheduling | `api/services/sync_all.py`, `api/services/sync_state.py`, `api/services/persistence.py`, `api/jobs.py`, `api/sync_once.py`, `api/routes/sync.py`, `api/routes/plaid.py`, `api/consumer_scope.py` |
| Read/edit routes | `api/routes/analytics.py`, `api/routes/review.py`, `api/main.py` |
| Backup and recovery | `api/backup.py`, `api/backup_crypto.py` |
| Schema and startup | `api/models.py`, `api/migrations.py`, `api/migrate_once.py`, `api/db.py` |
| Statement imports | `statement_imports/*.py` |
| Scripts and other | `scripts/*.py`, anything else |

Also report package-version differences between `$svc-running.pip` and `api/requirements.txt` at `$SHA`.
