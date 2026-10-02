# Frontend redesign — local Production web release packet — 2026-10-02

**Status: EXECUTED — 2026-10-02 01:38 UTC (2026-10-01 21:38 EDT).** The owner authorized the complete frontend deployment in the current session. Production web now runs the redesign plus the reviewed negative-net-cost composition fix at `b219188`. Only web was recreated.

The preparation and proposed commands below are retained as the original packet. The execution record at the end supersedes their source revision, image tags, evidence directory and step-by-step approval wording. No separate approval was required for each step after the owner's complete web deployment authorization.

Scope: deploy the dark-theme redesign of Overview, Review and Memberships (`38c04f5`, on top of `main` `4c3594d`) to the local Production runtime, Compose project `pft-runtime`. **Only `web` is rebuilt and recreated.** `api`, `jobs` and `db` are not touched, so jobs keeps running, no backup is needed, and there is no schema change, migration, sync or Plaid call. A web interruption of a few seconds is expected during recreation.

Authority: AGENTS.md, pft-safe-development, the [M4 web deployment](PFT_PHASE_2_M4_WEB_DEPLOYMENT_2026-09-30.md) (web-only recreate, real-phone acceptance, Serve route preserved) and the [sync diff-writes packet](PFT_SYNC_DIFF_WRITES_PRODUCTION_ACTION_PACKET_2026-10-01.md) (pin files, durable rollback tags, never `:latest`).

Labels: **[READ-ONLY]** no state change. **[LOCAL]** changes only local Git or local files outside Production. **[STATE]** changes Production containers, images or the pin file that decides which images Compose starts, with the effect named. **[M]** measured; **[E]** estimate.

## What is being released

| Item | Value |
| --- | --- |
| Commit | `38c04f5fb14e337fadf71c0d22422c48f8ab2264` "Redesign Overview, Review and Memberships (dark theme)", one commit on `4c3594d` |
| Changed paths | 26 files, all under `app/`, `components/`, `scripts/pft_m4_browser_qa.cjs` and `tailwind.config.js` [M]. No `api/`, `statement_imports/`, Dockerfile, `package*.json`, `next.config.js` or `compose*.yml` change |
| API contract | Same endpoint set and request parameters as the current frontend; no new response fields read [M]. One new request pattern: selecting the Gross Spending, Refunds or Card Benefits card loads `GET /analytics/monthly` once for each of the 12 trend months. Net Spending and Reimbursements use the existing `/analytics/trend` values |
| Build-time API target | `PFT_API_URL=http://api:8000` from `Dockerfile.web`, baked into the Next.js rewrites. No `basePath`, no preview code |
| Visible changes | Dark theme, summary cards with a trend that follows the selected card, toggling category rows with a separate breakdown chevron, colour emoji category icons, account and institution swatches that follow the real cards and banks |

Pre-merge verification on `38c04f5` [M]: Jest 57/57 in 12 suites, standalone TypeScript, `git diff --check main HEAD`, `next build`, M4 browser harness 27/27 and M4 bottom harness 54/54 against an isolated `next start` on `127.0.0.1:3023`, and the full backend suite (304 tests, 0 skipped, including the 7 `tests.test_derivation_writes` cases) against a disposable PostgreSQL 16 on `127.0.0.1:55439` with the seven synthetic opt-ins.

## Running state before the release

From `~/.local/share/pft/releases/2026-10-02/running-images.yml`, the single pin file recorded by the sync diff-writes release:

| Service | Image | Notes |
| --- | --- | --- |
| api | `sha256:6f6d9560…` | Not touched |
| jobs | `sha256:838b2833…` | Not touched; keeps its `PFT_APP_COMMIT` |
| web | `sha256:6ad6b7bc0f9962854c1c61467ea049baa61266ab281ed3b369774ba3be0f2180` | M4 release, also tagged `pft-web:m4-responsive-20260930`. This becomes the rollback image |
| db | `postgres:16` | Not touched |

Step 1 must confirm that the running containers still match these IDs before anything else runs.

## Known issues

- **`pft-runtime-web:latest` is stale.** Like api and jobs, web runs a pinned image ID. Any `docker compose up` without the pin file would recreate web from `:latest`, which is an older build. Every Compose command here includes a pin file, and step 8 updates the single pin file so later recreations start the new image.
- **The build is not byte-reproducible.** `npm ci` installs the locked dependency versions, but the `node:22-alpine` base comes from the local image cache. If the base is missing, Docker pulls the current one. Step 1 records the cached base; a missing base is a decision point, not an automatic pull.
- **Emoji depend on the device's emoji font.** iOS, Android and Windows 10/11 draw all 19 category emoji. Older systems may show monochrome glyphs or empty boxes. The label text is unaffected.
- **Image tags protect against `docker image prune`, not `docker image prune -a`.** Do not run `prune -a` while rollback is still possible.

## Stop conditions

- `38c04f5…` is not an ancestor of `HEAD`, the web image paths differ between `38c04f5…` and `HEAD`, or there are tracked or untracked changes under the web image paths (step 1).
- A running container's image differs from `running-images.yml`, or `compose config --images` does not resolve exactly the running IDs.
- The tag `pft-runtime-web:rollback-20261002` or `pft-runtime-web:redesign-38c04f5` already exists.
- The new image's routes manifest has a `basePath`, rewrites that do not point at `http://api:8000`, or any `design-preview` string.
- A dry run shows any service other than `web` being created or recreated.
- After recreation: web not healthy within 120 s, any route not 200, any api/jobs/db container ID, image, start time or restart count changed, a different Serve mapping, or an unexplained difference in the analytics fingerprints.
- A sync is due within 1 hour (it would change the analytics fingerprints mid-release), or a sync is running.
- The owner has not accepted the redesign on a real phone in the private preview.

## Fixed values and private evidence directory

Run from the repository root in WSL after the merge. Never print, copy or commit the env files.

```bash
cd ~/code/personal-finance-tracker
export PFT_RUNTIME_ENV_FILE=.env.runtime.production.local
export PFT_DB_ENV_FILE=.env.runtime.db.production.local
export PFT_BACKUP_ENV_FILE=.env.runtime.backup.production.local
export PFT_BACKUP_HOST_DIR=/mnt/c/Users/tianr/PFTBackups/Production
export PFT_WEB_PORT=3000
export PFT_APP_COMMIT=pinned-by-override   # interpolation only; the pin file sets the jobs value
export NEW_SHA=38c04f5fb14e337fadf71c0d22422c48f8ab2264
export PINS=~/.local/share/pft/releases/2026-10-02/running-images.yml
export R=~/.local/share/pft/releases/2026-10-02-web   # private pins and evidence; never commit
(umask 077; mkdir -p "$R")
cp -p "$PINS" "$R/current-images.yml"
compose() { env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime \
  -f compose.runtime.yml -f docker-compose.production.yml -f "$R/current-images.yml" "$@"; }
```

`env -u` keeps stale shell values for the HTTP allowlists from overriding the private env file, as in earlier releases. Keep `$R` at mode 0700/0600.

## Procedure

### Step 0 — Merge [LOCAL]

```bash
git status --short                       # must be empty
git merge --ff-only frontend-redesign
git merge-base --is-ancestor $NEW_SHA HEAD && echo "redesign commit included"
git diff --stat $NEW_SHA HEAD            # may list only docs/ (this packet)
```

No push. If `--ff-only` refuses, stop. The packet itself is committed after `$NEW_SHA`, so `HEAD` may be that docs commit. The web image is built from `HEAD`, whose web source must be identical to `$NEW_SHA`; step 1.1 checks this.

### Step 1 — Preflight [READ-ONLY]

1. Source scope. Both commands must print nothing:

   ```bash
   WEB_PATHS="app components lib Dockerfile.web package.json package-lock.json next.config.js
     next-env.d.ts tsconfig.json tailwind.config.js postcss.config.js compose.runtime.yml docker-compose.production.yml"
   git status --short -- $WEB_PATHS
   git diff --stat $NEW_SHA HEAD -- $WEB_PATHS
   ```

2. Containers and pins:

   ```bash
   docker inspect -f '{{.Name}} {{.Image}} {{.State.StartedAt}} {{.RestartCount}}' \
     pft-runtime-api-1 pft-runtime-jobs-1 pft-runtime-web-1 pft-runtime-db-1 | tee "$R/containers-before.txt"
   compose config --images | tee "$R/config-images-before.txt"
   ```

   The api, web and jobs IDs must equal those in `$PINS`, and `compose config --images` must list exactly those IDs plus `postgres:16`.
3. Tags and base image:

   ```bash
   docker image inspect pft-runtime-web:rollback-20261002 >/dev/null 2>&1 && echo "rollback tag exists; stop"
   docker image inspect pft-runtime-web:redesign-38c04f5 >/dev/null 2>&1 && echo "release tag exists; stop"
   docker image inspect -f '{{.Id}} {{.Created}}' node:22-alpine | tee "$R/node-base.txt"
   docker compose version                   # --dry-run needs Compose 2.20 or later
   ```

4. Serve route and sync timing:

   ```bash
   tailscale serve status | tee "$R/serve-before.txt"      # expect / -> http://127.0.0.1:3000
   curl -s http://127.0.0.1:3000/api/pft/sync/status > "$R/status-before.json"
   ```

   Require that no sync is running and that the next scheduled sync is more than 1 hour away.
5. Read-only analytics fingerprints through the running web proxy. Use the current month and the two before it:

   ```bash
   for q in "monthly?month=2026-10" "monthly?month=2026-09" "monthly?month=2026-08" "trend?end_month=2026-10" \
            "breakdown?month=2026-09&group_by=account" "memberships?end_month=2026-09"; do
     printf '%s %s\n' "$q" "$(curl -s "http://127.0.0.1:3000/api/pft/analytics/$q" | sha256sum | cut -c1-64)"
   done | tee "$R/analytics-before.txt"
   ```

### Step 2 — Rollback tag for the running web image [STATE: one new image tag only]

```bash
docker image tag "$(docker inspect -f '{{.Image}}' pft-runtime-web-1)" pft-runtime-web:rollback-20261002
docker image inspect -f '{{.Id}}' pft-runtime-web:rollback-20261002   # [READ-ONLY] must be sha256:6ad6b7bc…
```

### Step 3 — Rollback pin [LOCAL]

```bash
OLD_WEB=$(docker inspect -f '{{.Image}}' pft-runtime-web-1)
printf 'services:\n  web:\n    image: %s\n    pull_policy: never\n' "$OLD_WEB" > "$R/web-rollback.yml"
```

### Step 4 — Build the new web image [STATE: builds one new image; containers untouched; `pft-runtime-web:latest` not moved]

`docker build` with an explicit tag is used instead of `compose build`, so `:latest` stays where it is and nothing else is rebuilt. `npm ci` downloads the locked dependencies.

```bash
docker build -f Dockerfile.web -t pft-runtime-web:redesign-38c04f5 \
  --label org.opencontainers.image.revision=$NEW_SHA .
NEW_WEB=$(docker image inspect -f '{{.Id}}' pft-runtime-web:redesign-38c04f5)
printf 'services:\n  web:\n    image: %s\n    pull_policy: never\n' "$NEW_WEB" > "$R/web-new.yml"
```

If step 1 found no cached `node:22-alpine`, stop before this step and decide whether to allow the pull.

### Step 5 — Verify the new image [READ-ONLY]

```bash
docker run --rm --network none --entrypoint node pft-runtime-web:redesign-38c04f5 -e \
 'const m=require("/app/.next/routes-manifest.json");console.log(JSON.stringify(m.basePath),[].concat(m.rewrites.beforeFiles||[],m.rewrites.afterFiles||[],m.rewrites.fallback||[]).map(r=>r.destination).join(" "))'
docker run --rm --network none --entrypoint sh pft-runtime-web:redesign-38c04f5 -c \
  'grep -rl "design-preview" /app/.next >/dev/null && echo FOUND || echo ok-no-preview'
docker run --rm --network none --entrypoint sh pft-runtime-web:redesign-38c04f5 -c \
  'grep -rl "category-emoji" /app/.next/static | head -1'
compose -f "$R/web-new.yml" config --images
compose -f "$R/web-new.yml" up --dry-run -d --no-deps --no-build --pull never --force-recreate web
```

Pass:
- `basePath` is `""` and the four rewrites go to `http://api:8000/plaid`, `/review`, `/analytics` and `/sync`;
- `ok-no-preview` is printed;
- one static file contains `category-emoji`;
- `config --images` changes only web, to `$NEW_WEB`;
- the dry run recreates only web.

### Step 6 — Recreate web [STATE: recreates `pft-runtime-web-1` from the new image; web interruption of a few seconds; api, jobs and db untouched]

```bash
compose -f "$R/web-new.yml" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 web
```

### Step 7 — Post-deploy verification [READ-ONLY]

```bash
docker inspect -f '{{.Image}} {{.State.Health.Status}} {{.RestartCount}}' pft-runtime-web-1   # $NEW_WEB healthy 0
docker inspect -f '{{.Name}} {{.Image}} {{.State.StartedAt}} {{.RestartCount}}' \
  pft-runtime-api-1 pft-runtime-jobs-1 pft-runtime-db-1 > "$R/containers-after.txt"
grep -v pft-runtime-web-1 "$R/containers-before.txt" | diff - "$R/containers-after.txt" && echo "api/jobs/db unchanged"
for p in / /review /memberships /api/pft/sync/status; do
  curl -s -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:3000$p
done
tailscale serve status | diff "$R/serve-before.txt" - && echo "serve unchanged"
```

Repeat the step 1.5 loop into `$R/analytics-after.txt` and `diff` it with `analytics-before.txt`. The files must be identical unless `last_published_run_id` in `/sync/status` changed in between. In that case, record the new run and compare again after the next quiet period.

Then open Overview, Review and Memberships through private HTTPS on a phone and a desktop. Check:
- category emoji, account swatches and the summary cards;
- a category row selects and clears its transactions;
- the chevron opens the breakdown;
- the trend follows the selected card.

Do not make edits during this check.

### Step 8 — Update the pin file [STATE: changes which web image future Compose commands start]

```bash
cp -p "$PINS" "$R/running-images.before-web.yml"
sed -i "s|$OLD_WEB|$NEW_WEB|" "$PINS"
grep -c "$NEW_WEB" "$PINS"               # [READ-ONLY] must print 1
```

### Step 9 — Confirm Compose will not return to the old image [READ-ONLY]

```bash
env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime \
  -f compose.runtime.yml -f docker-compose.production.yml -f "$PINS" config --images
env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime \
  -f compose.runtime.yml -f docker-compose.production.yml -f "$PINS" \
  up --dry-run -d --no-build --pull never api web jobs
docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' pft-runtime-web-1
```

Pass:
- `config --images` lists the new web ID with the unchanged api and jobs IDs;
- the dry run shows no service needing to be created or recreated;
- the restart policy is `unless-stopped`, so a Docker or host restart restarts the existing container with its own image.

Record in this document's execution record. Commit the record [LOCAL] without the private files.

## Rollback

1. **[STATE: recreates `pft-runtime-web-1` from the pre-release image; api, jobs and db untouched]**

   ```bash
   compose -f "$R/web-rollback.yml" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 web
   ```

   `web-rollback.yml` pins `sha256:6ad6b7bc…`, which is also kept by the durable tag `pft-runtime-web:rollback-20261002`. If `$R` is lost, write the same file from that tag's ID.
2. **[STATE: changes which web image future Compose commands start]** If step 8 already ran:

   ```bash
   cp -p "$R/running-images.before-web.yml" "$PINS"
   ```

3. Verify as in step 7, expecting `sha256:6ad6b7bc…`.
4. **Code [LOCAL], only if the redesign itself is withdrawn:** `git revert 38c04f5`. Nothing was pushed.

No data rollback is needed. The release changes no data, and the frontend makes the same API calls as before.

## Execution record

Executed under the owner's instruction to deploy the frontend redesign. Actual released source is `b219188bcd7b5fcc45b1f888c6c8c757cd9fdedb`: redesign `38c04f5`, the release packet, and the reviewed Membership composition fix. The fix hides the part-to-whole bar when any component is negative while retaining the signed monetary amounts and calculation explanation. The worktree was clean at packaging; no API or dependency changes were included.

Private durable evidence: `~/.local/share/pft/releases/2026-10-02-web-redesign-b219188/` (directories 0700, files 0600). It contains source fingerprints, the allowlisted build context, fixed base-image digest, container/Serve baselines, table and analytics fingerprints, image checks, candidate and live browser results, rollback pins, before/after running pins and the release receipt. `/tmp/pft-redesign-release-b219188/` is the working copy, not the sole retained evidence.

| Step | Result |
| --- | --- |
| 0 — source | `38c04f5` already on main; reviewed correction committed locally as `b219188`. No push. |
| 1 — preflight | Running api/jobs/web matched the durable pins; DB image matched `postgres:16`. Web healthy, jobs running, no current sync, earliest automatic sync approximately 23 hours away. Baseline captured for 14 public tables excluding the active heartbeat table `sync_runtime_state`, plus 8 analytics responses. |
| 2 — rollback tag | Pre-release web `sha256:6ad6b7bc0f9962854c1c61467ea049baa61266ab281ed3b369774ba3be0f2180` retained as `pft-runtime-web:rollback-redesign-b219188`. |
| 4 — build | `node:22-alpine` was missing, so downloaded under the authorized deployment and pinned to `node@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402` in both stages of the isolated Dockerfile. Only tracked web-build inputs were staged; no env files, financial exports or backend source. Next.js production build, lint and type validation passed. |
| 5 — image verification | New image `sha256:60f50b6b4fb71d607cef9f6826d53ea5eabf3a17e40c441bda551ada2c12a2f1`, tagged `pft-runtime-web:redesign-b219188`, with source revision label `b219188…`. Empty basePath, four rewrites to `http://api:8000`, no design-preview code, category emoji assets present. Dry run recreated only web. |
| 6 — recreate web | Web-only `--no-deps --no-build --pull never --force-recreate --wait` completed; new web healthy. API, jobs and DB were not recreated or restarted. |
| 7 — post-deploy verification | 14 table fingerprints and all 8 analytics fingerprints identical. API/jobs/DB container IDs, image IDs, start times and restart counts identical. Serve configuration unchanged. Three pages and sync status returned 200. Local/private HTTPS HTML for all three pages, 16 static assets and 2 analytics responses matched. |
| 8 — pin file | Atomically updated only the web image in `~/.local/share/pft/releases/2026-10-02/running-images.yml`; previous pins retained in durable evidence. API/jobs pins and the jobs commit value unchanged. |
| 9 — Compose resolution | Final config resolves new web and unchanged api/jobs/DB. Full api/web/jobs dry run required no creates or recreates. Web restart policy remains `unless-stopped`. |

Validation [M]:

- Jest: 60/60 tests in 12 suites, including positive, zero and negative Membership net-cost regressions.
- Candidate image at isolated `127.0.0.1:3026`, synthetic APIs only: 12/12 page-flow cases at 320/390/768/1440 px; 18/18 bottom-layout cases at 320/390/1440 px; 6/6 composition cases at 320/1440 px. Checks cover filters, category disclosures, editing with synthetic writes, loading/error recovery, pagination, bulk toolbar, keyboard viewport and overflow.
- Live Production: 12/12 read-only browser cases (three pages × 390/1440 px × local/private origins). Overview component history, category select/clear and chevrons, both Review modes, and Membership filters passed. No runtime errors, rendered API errors or horizontal overflow. All non-GET requests were blocked; no mutation attempts occurred.
- Private-origin browser content was retrieved over Windows curl HTTPS and rendered in Chromium because Tailscale runs on Windows. This verifies private HTTPS transport plus browser rendering; no physical-phone acceptance was performed in this session.
- No financial-data write, schema migration, manual sync or Plaid API call. Jobs stayed running throughout. The jobs heartbeat table was excluded from financial preservation comparison because its routine heartbeat continues to advance.

### Rollback for this executed release

The retained `web-rollback.yml` pins the full pre-release image ID above. With the runtime environment variables from the original packet set, the web-only rollback command is:

```bash
PFT_WEB_RELEASE="$HOME/.local/share/pft/releases/2026-10-02-web-redesign-b219188"
env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime \
  -f compose.runtime.yml -f docker-compose.production.yml \
  -f "$PFT_WEB_RELEASE/current-images.yml" -f "$PFT_WEB_RELEASE/web-rollback.yml" \
  up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 web
```

After an authorized rollback, restore the single durable pin file from `running-images.before-web.yml` and repeat the container/Serve/analytics checks. No data rollback is needed.
