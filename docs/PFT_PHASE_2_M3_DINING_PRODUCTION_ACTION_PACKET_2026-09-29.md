# M3 Dining Production preflight and action packet — 2026-09-29

Status: final read-only preflight completed. Forward migration, service replacement,
access closure/reopen, and rollback commands below are **prepared only**. They have
not been executed. Stop here for owner authorization of this exact packet.

The authoritative snapshot was taken at **2026-09-29 20:20:17.867118 UTC** in one
verified `REPEATABLE READ READ ONLY` transaction. Production remains on the old
vocabulary and images.

| Manual override code | Active now | Cleared now | Active after proposed migration | Cleared after |
| --- | ---: | ---: | ---: | ---: |
| FOOD_AND_DRINK | 80 | 0 | 0 | 0 |
| DINING | 0 | 0 | 80 | 0 |

The exact target manifest contains 80 unique transaction IDs and their complete
before audit rows. The manual table has 180 rows; its other 100 rows remain
unchanged. No category table triggers exist. The current constraint permits
`FOOD_AND_DRINK` and rejects `DINING`; its full definition and exact rollback SQL
are preserved in the manifest. The final constraint substitutes `DINING` while
retaining all other allowed categories and null behavior. The 573 normalized
Plaid `FOOD_AND_DRINK` source values remain unchanged.

All 15 public tables have recorded count/SHA-256 fingerprints. A final read-only
check confirmed all 14 non-runtime-state table fingerprints and the constraint
were unchanged throughout preflight; runtime state was unchanged apart from the
permitted jobs heartbeat. No Production financial/schema writes or Plaid calls
occurred. No services were replaced, restarted, stopped, or paused.

Current Production replay covers 2,607 eligible rows and all 25 available months
(September 2024–September 2026). Every canonical category formula, component sum,
net sum, contribution count, and signed contribution sum reconciles exactly.
Canonical sums also match every account and institution. Existing monthly fields
match after the intentional category rename/sort-order change; all account and
institution outputs in spending, benefit, and reimbursement modes match exactly.
Monthly, YTD, and trailing-12-month Membership outputs match exactly.
September remains Gross 6,483.52 − Refunds 1,601.47 − Reimbursements 37.50 −
Card Benefits 210.26 = Net Spending 4,634.29. Full June/August/September category
and redistribution tables are in the private preview report.

**Identity and artifacts.** Database `pft_production_backfill`, role `pftbackfill`,
schema `public`, PostgreSQL 16.15; observed server address `172.20.0.4` on
`pft-runtime_default`. The preserved authority volume is
`personal-finance-tracker_pgdata_production_backfill`. API and jobs both confirmed
this expected database and Production environment; deployed API readiness passed.
Current API/web/DB health is healthy and no sync runs were running. The three
other running containers are standalone database services, not application
category consumers. No native Python/Node application process was found in the
WSL process inventory. API and database env files match their running values.
Jobs has no `PFT_ALLOWED_HOSTS` or `PFT_ALLOWED_ORIGINS` keys; the current shared
env file includes them for API HTTP enforcement. Jobs exposes no HTTP listener,
and its scheduler does not use these lists. Forward jobs inherits the current
shared API configuration; rollback explicitly removes the two keys to preserve
the original worker configuration. This nonfinancial configuration difference is
explicitly included in the reviewed service cutover. Recheck inventory and DB clients at the maintenance gate.

| Service | Exact new image ID | Exact running/rollback image ID |
| --- | --- | --- |
| API | `sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961` | `sha256:5b11a147048f888fe9ee6e05ff5f9984a31749e95bdcd6db6dfdcb1b0ff66dcf` |
| Web | `sha256:27ebccc049961a588f5fc8ced6c56bdcbe596920cdef41d2a1d4740550fb63f3` | `sha256:aaa353283344398d2d58908e911704071a3c4f7623bbfc886f93e7747f7fa586` |
| Jobs | `sha256:b1ae3322ba3ab7683d46b4026dda5f57ecd43463e8bbc1a6e4d51272ce59de6c` | `sha256:f3e3536c901ad23a4d3f1e2f007f11a4933dbc9cfa1c8b635565a8a2fbed60d2` |

All rollback images are still locally available. API/web/jobs are affected and
must move together. PostgreSQL and its volume stay in place. The new worker's
backup provenance identifies its exact image rather than claiming an uncommitted
source tree is an old Git commit. Rollback restores the recorded worker provenance
`2b413550433e83db151ef1f62ad98b26d70fbd9e`.

Private evidence directory:
`/tmp/pft-m3-dining-final-preflight-20260929` (0700; files 0600).
Do not commit its manifests, snapshot rows, target IDs, or detail IDs.

- `reviewed-manifest.json`: exact migration input, including all before fingerprints.
  File SHA-256: `3fa7fc7ba493893b660e73d5d3458a4035753ddbe9c90eef81754bf870a75147`.
- `snapshot.json`, `preview.json`, `preview-review.md`: same-snapshot deployed
  baseline and revised Dining preview.
- `preflight-summary.json`: exact counts, target/audit projection hashes, constraint,
  and preservation results. `runtime-identities.json` and `image-identities.json`
  record container/volume/environment provenance without secrets.
- `forward-images.yml`, `rollback-images.yml`, `staged-jobs.yml`: pinned Compose
  overrides. Both staged configurations validated with Compose 5.4.0 using the
  actual Production env-file paths; no rendered secret configuration was printed.
- `refresh_after_quiescence.py`: refuses every reviewed data/schema difference
  except a verified `jobs_heartbeat_at` change. Seven deterministic guard scenarios
  passed without database/network calls.
- `verify_staged_http.py`: prepared/compiled GET-only verifier for all months,
  account/institution modes, Membership periods, category summaries, and complete
  paginated component details/source preservation. It is not a claim that the new
  images have already been served against Production.
- `verify_jobs_schema.py`: prepared/compiled schema/import-only worker verification;
  never executes a tick, backup, sync, or Plaid call.
- `artifact-integrity.json`: SHA-256 inventory for the reviewed evidence and helpers.

**1. Before an authorized maintenance window.** Confirm owner acceptance of the
migration, all three pinned services, maintenance closure, and eventual resumption
of normal scheduler operation. Keep all image IDs available; do not build/pull
replacement images or change env files during this procedure. Preserve the private
packet on existing encrypted owner-only storage before execution, verify its hashes
and access controls, and record that location. `/tmp` alone is not durable recovery
storage. Confirm sufficient time for the full verification run and a guarded
rollback before reopening. Refresh counts/manifests if target/financial state has
changed; the current preflight is not permission to migrate later unreviewed rows.

Use the exact checked configuration paths and a task-specific shell variable:

```bash
cd /home/randyli/code/personal-finance-tracker
export PFT_RUNTIME_ENV_FILE=.env.runtime.production.local
export PFT_DB_ENV_FILE=.env.runtime.db.production.local
export PFT_BACKUP_ENV_FILE=.env.runtime.backup.production.local
export PFT_BACKUP_HOST_DIR=/mnt/c/Users/tianr/PFTBackups/Production
export PFT_APP_COMMIT=reviewed-m3-dining-image
export PFT_WEB_PORT=3004
PFT_M3_PACKET=/tmp/pft-m3-dining-final-preflight-20260929
PFT_M3_OWNER=$(.venv/bin/python -c 'import json; print(json.load(open("/tmp/pft-m3-dining-final-preflight-20260929/reviewed-manifest.json"))["pilot_user_id"])')
pft_m3_compose() {
  env -u PFT_ALLOWED_HOSTS -u PFT_ALLOWED_ORIGINS docker compose -p pft-runtime -f compose.runtime.yml \
    -f docker-compose.production.yml "$@"
}
```

Verify artifact hashes, image availability, current running image IDs, volume,
expected DB, both API/jobs owner identities, DB clients, and active sync state.
Inventory ad-hoc import/restore/migration processes and automatic restarters too.
Never print env files or the full interpolated Compose configuration.

**2. Close access, drain, and stop old affected services.** The observed ingress is
one Tailscale HTTPS 443 handler for `pft-host.tailc4d964.ts.net`, proxying `/` to
`http://127.0.0.1:3000`; no unrelated handler appeared. Recheck it and stop if scope
changed. In Windows PowerShell, disable only this handler:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --https=443 off
& 'C:\Program Files\Tailscale\tailscale.exe' serve status --json
```

Require the application HTTPS path to be closed. Do not alter tailnet policy,
Funnel, certificates, host identity, or unrelated networking. Stop web to close
localhost application access; drain existing API requests and current jobs work.
If a sync is running, do not begin migration or force a financial rollback;
wait for its normal completion or stop for owner direction. Then:

```bash
pft_m3_compose stop -t 90 web api jobs
```

Require all three old containers stopped, no listener at localhost:3000, no old
native application processes, and no unexpected DB clients/writers. Automatic
restart/recreation must remain disabled by the stopped service state. Keep DB up.
Do not use `compose down`, remove volumes, or alter Item sync flags/cursors.
From this point until verification/reopen, old incompatible services cannot serve
any reads or writes.

**3. Revalidate the quiescent manifest and execute one atomic transaction.** The
live heartbeat makes the current all-table manifest time-sensitive. Generate a
new maintenance manifest only after writers are stopped. The helper admits a
heartbeat-only change; altered requests, publications, financial rows, targets,
audit rows, schema, or counts require fresh owner review. It creates new evidence
files exclusively and never overwrites the original reviewed manifest:

```bash
docker run --rm --user 1000:1000 --network pft-runtime_default \
  --env-file .env.runtime.production.local \
  -v "$PFT_M3_PACKET:/evidence" \
  sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961 \
  python /evidence/refresh_after_quiescence.py
```

Review the heartbeat delta and the unchanged 80-target manifest. Only then execute
the explicit migration; the flag below is used only after owner authorization:

```bash
docker run --rm --user 1000:1000 --network pft-runtime_default \
  --env-file .env.runtime.production.local \
  -v "$PFT_M3_PACKET:/evidence" \
  sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961 \
  python -m scripts.pft_dining_migration apply \
  --expected-database pft_production_backfill --user-id "$PFT_M3_OWNER" \
  --manifest /evidence/maintenance-manifest.json \
  --output /evidence/forward-result.json --production-authorized
```

The command checks expected identity, obtains the existing derivation lock and
financial table locks, rechecks the entire before state, and uses bounded timeouts.
Within one transaction it drops the old constraint, updates only the 80 active
manifest targets' `category` cells, adds/validates the Dining-only constraint, and
checks all row/audit/fingerprint invariants before commit. No ORM edit timestamps
or actors change. Source/classification rows stay untouched.
Require successful `.committed` and `.verified` receipts, zero old-code rows,
80 active Dining rows, manual table count 180, and identical unrelated fingerprints.
A missing receipt means inspect actual state against the manifest; never replay a
mutation blindly. Any transaction failure rolls back its DDL and row changes.

**4. Activate matching services behind closed access.** Start all three new pinned
images together. Web is bound only to private verification port 3004; the normal
application port 3000 stays absent. Jobs runs `sleep infinity` while imports/schema
are verified; its scheduler has not started:

```bash
pft_m3_compose -f "$PFT_M3_PACKET/forward-images.yml" \
  -f "$PFT_M3_PACKET/staged-jobs.yml" up -d --no-deps --no-build \
  --pull never --force-recreate api web jobs
```

Verify actual `.Image` identities against all three pinned IDs, API/web health,
unchanged DB volume, and jobs' staging command. Check API readiness, worker
compatibility, and all staged financial responses:

```bash
docker exec pft-runtime-api-1 python -c \
  'import urllib.request,json; assert json.load(urllib.request.urlopen("http://127.0.0.1:8000/ready"))["ready"]'
docker exec -i pft-runtime-jobs-1 python - DINING \
  < "$PFT_M3_PACKET/verify_jobs_schema.py"
.venv/bin/python "$PFT_M3_PACKET/verify_staged_http.py"
```

Independently re-read committed DB fingerprints and compare to
`forward-result.json`'s `result.after`; require exact equality while staged jobs
cannot write. Confirm audit metadata and source values are unchanged. Inspect the
staged UI read-only for Dining and separate Groceries, without edits or sync clicks.
No classification, sync request, Plaid call, backup tick, or generic migration is
part of acceptance verification. On any failure keep access/writers closed and
use the guarded reverse procedure below.

**5. Reopen only after all checks pass.** Record acceptance and evidence on the
protected storage first. Removing staging restrictions closes the automatic
rollback window: subsequent user edits/heartbeat/sync activity may invalidate the
exact reverse manifest. Move the same new web image to the usual loopback port:

```bash
export PFT_WEB_PORT=3000
pft_m3_compose -f "$PFT_M3_PACKET/forward-images.yml" up -d \
  --no-deps --no-build --pull never --force-recreate web
```

Verify health/image and readonly localhost:3000 responses; API and staged jobs
must remain on their already verified new IDs. Restore only the recorded Tailscale
handler in Windows PowerShell:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --https=443 http://127.0.0.1:3000
& 'C:\Program Files\Tailscale\tailscale.exe' serve status --json
```

Confirm the exact tailnet-private endpoint and owner read-only access. Then remove
only the jobs staging override and resume its matching scheduler:

```bash
pft_m3_compose -f "$PFT_M3_PACKET/forward-images.yml" up -d \
  --no-deps --no-build --pull never --force-recreate jobs
```

Normal scheduler resumption may immediately perform due work; that is part of the
future reopening authorization, not a verification Plaid call. Do not enqueue a
sync, initiate Link, or force classification. Confirm worker identity and normal
heartbeat, then record the release result.

**Guarded reverse before reopen.** If the forward transaction rolled back, the old
DB remains authoritative: verify exact original state before restoring old
services. If forward committed, stop all affected new services with ingress still
closed and require exact `forward-result.json` after-state, including target audit
rows, constraint, all table fingerprints, and no subsequent writers. Reverse uses
the tested new operator image, not old code that lacks this command:

```bash
export PFT_WEB_PORT=3004
pft_m3_compose stop -t 90 web api jobs
docker run --rm --user 1000:1000 --network pft-runtime_default \
  --env-file .env.runtime.production.local \
  -v "$PFT_M3_PACKET:/evidence" \
  sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961 \
  python -m scripts.pft_dining_migration rollback \
  --expected-database pft_production_backfill --user-id "$PFT_M3_OWNER" \
  --manifest /evidence/forward-result.json \
  --output /evidence/reverse-result.json --production-authorized
pft_m3_compose -f "$PFT_M3_PACKET/rollback-images.yml" \
  -f "$PFT_M3_PACKET/staged-jobs.yml" up -d --no-deps --no-build \
  --pull never --force-recreate api web jobs
```

Require reverse `.committed`/`.verified` receipts, exact pre-migration fingerprints
and constraint, 80 active Food & Drink overrides, zero Dining overrides, and all
original target audit fields. Only manifest targets are reversed. Verify all old
image IDs/health and run the worker check with `FOOD_AND_DRINK`. Read-only legacy
API outputs must exactly match `snapshot.json`'s deployed baseline, without the
Dining rename; new-M3 HTTP verifier is not applicable to old images. Reopen old
web on port 3000 and Serve using the same verified sequence with
`rollback-images.yml`; resume old jobs last without `staged-jobs.yml`.

If any row, audit field, request sequence, heartbeat, publication, image identity,
or schema changed after the forward commit, reverse refuses. Keep access closed
and obtain a new owner-reviewed recovery plan. Never rewrite all Dining rows,
overwrite later manual edits, or restore an entire database to undo this rename.
There is no automatic fallback to old services against the Dining constraint.

Current authorization boundary: owner review of the complete preflight and this
forward/guarded-reverse packet. The only work performed in this turn was read-only
Production inspection and local evidence/packet preparation.
