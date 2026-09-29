# Phase 2 M2 combined runtime and read-only acceptance — 2026-09-29

**Scope:** The accepted M2 backend and frontend were built and deployed together. Only `pft-runtime-api-1` and `pft-runtime-web-1` were recreated. No manual Production financial write, schema change, Plaid call, jobs/DB recreation, or Tailscale configuration change occurred. Source was the M2 working tree based on commit `ae1b4abac4ab0024ebc8296d7c6e9813ccb2cfb0`; the M2 changes were not committed at deployment time.

## Deployment and rollback evidence

| Service | Before image | Rollback tag | After image |
| --- | --- | --- | --- |
| API | `sha256:cec3537e5a6fb670aeb823bdde7c213f92c237a29cde48b58306be4d545b57a2` | `pft-runtime-api:m2-pre-20260929` | `sha256:5b11a147048f888fe9ee6e05ff5f9984a31749e95bdcd6db6dfdcb1b0ff66dcf` |
| Web | `sha256:428dec07c99fe04d8bca63a0c05d48793afd2d1612631ca577ecb43e2ea8fd1a` | `pft-runtime-web:m2-pre-20260929` | `sha256:aaa353283344398d2d58908e911704071a3c4f7623bbfc886f93e7747f7fa586` |

The first web image build failed because `Dockerfile.web` omitted the existing `lib/utils.ts` source. Adding `COPY lib ./lib` made the combined API/web build pass. The running containers were unchanged during the failed build. Compose `config --quiet` passed with the existing private runtime env files; their SHA-256 hashes and those of the two Compose files were identical before and after deployment. Their contents were not printed or changed.

The API and web containers are healthy. Their new container IDs begin `eb084eda` and `cec14f4f`. The DB and jobs container IDs remained `3b97f773` and `4bc21502`; DB health is healthy and jobs is running. Web still publishes only `127.0.0.1:3000`. The deployed API reports all nine M2 bulk operations. The Tailscale Serve status remained one tailnet-only HTTPS 443 handler for `pft-host.tailc4d964.ts.net/` proxying to `http://127.0.0.1:3000`; Funnel remained off.

**Rollback if needed:** Confirm the DB/jobs remain healthy and inspect the current state. Retag the two preserved `m2-pre-20260929` images as `pft-runtime-api:latest` and `pft-runtime-web:latest`, then use the same Production Compose files and existing private env interpolation to recreate **only** `api web` with `--no-deps --no-build --force-recreate --wait`. Verify image IDs, localhost/private HTTPS, status, and financial summaries. Do not reset the DB or reverse already accepted manual decisions. Any later Production write requires its own state-aware reversal before a backend rollback.

The exact image rollback commands are:

```bash
docker tag pft-runtime-api:m2-pre-20260929 pft-runtime-api:latest
docker tag pft-runtime-web:m2-pre-20260929 pft-runtime-web:latest
env PFT_RUNTIME_ENV_FILE=.env.runtime.production.local \
  PFT_DB_ENV_FILE=.env.runtime.db.production.local \
  PFT_BACKUP_ENV_FILE=.env.runtime.backup.production.local \
  PFT_BACKUP_HOST_DIR=/mnt/c/Users/tianr/PFTBackups/Production \
  PFT_APP_COMMIT=ae1b4abac4ab0024ebc8296d7c6e9813ccb2cfb0 \
  docker compose -f compose.runtime.yml -f docker-compose.production.yml \
  -p pft-runtime up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 api web
```

## Read-only integration evidence

- Windows localhost and private Tailscale HTTPS returned HTTP 200 for Overview, Review, and Membership. The Review benefit-category options route also returned 200.
- Real API reads returned 504 Credits & Transfers rows, two Needs Review rows, and the new Review automatic/manual/effective benefit fields. September Overview values were gross `$6,441.55`, refunds `$1,601.47`, reimbursements `$37.50`, benefits `$210.26`, and net spending `$4,592.32`. Membership showed 116 transactions and net cost `$2,009.14`. Publication stayed `6c611cff-3ad9-4e7c-abc7-f0c5545c8b5b`; jobs and backup stayed healthy, with no active sync.
- Rendered read-only Playwright checks on the deployed app at 390 and 1440 pixels covered Review, Overview, and Membership. Each showed the nine bulk actions, value-free restore confirmation, Clear behavior, a visible fixed toolbar at top/middle/end scroll, no horizontal overflow, and no browser errors. Browser interception blocked any non-GET financial API request; none was attempted. A separate Review check confirmed an eligible benefit Set enabled Review changes, changed selection invalidated confirmation, and changing the effective-type filter cleared selection.
- A mixed Review selection disabled Set Benefit Category with an ineligible-selection message. A synthetic intercepted GET failure showed the Review load error. These checks generated no Production write request.
- The owner replied “yes no problem” to the bundled real-iPhone Safari checklist covering Wi-Fi and cellular private access, displayed totals, all three pages, toolbar reachability, action options, and selection reset. No iPhone financial edit was requested or reported. The agent could not independently instrument Safari on the physical device.
- The owner separately confirmed “yes” to the real-iPhone mixed card-benefit/non-benefit selection check: Set Benefit Category was disabled with an ineligible-selection message, and selection was cleared without applying.

**Read-only checkpoint gate:** The one-ID set/restore acceptance action required separate owner approval, which was subsequently granted and exercised below.

## Authorized Production M2 write/restore acceptance — 2026-09-29

The owner separately approved exactly two one-ID bulk edits for transaction `4XvR41aqOmINvqV3mzoRcNwo4gZkK3izmN09kV`. Both requests went through the live localhost web/API proxy. No Plaid call, other Production write, schema change, or service recreation was performed in this acceptance step.

Fresh pre-Set state: the $13.81 transaction dated 2026-09-19 was active, consumer-enabled, non-removed, positive, non-internal, and automatically classified `card_benefit`. Automatic and effective benefit category were `SHOPPING_CREDIT`; no manual benefit override row existed. No sync run was active. The fresh baseline had 18 benefit override rows on *other* transactions.

| Step | Exact operation | API response | Verified target state |
| --- | --- | --- | --- |
| Set | `set_benefit_category`, `SHOPPING_CREDIT` | selected 1, changed 1, unchanged 0; automatic/effective/override all `SHOPPING_CREDIT` | Explicit active override row created at `2026-09-29 17:00:23.669016`; `cleared_at/by` null. |
| Restore | `restore_benefit_category_auto`, no value | selected 1, changed 1, unchanged 0; automatic/effective `SHOPPING_CREDIT`, override null | Same row retained as audit evidence with `benefit_category` null and `cleared_at=2026-09-29 17:00:40.093082`, `cleared_by` populated. |

The full raw and normalized target row hashes and the target's classification/category/label decision hash were unchanged across all three reads. Full-row aggregate fingerprints and counts for every *other* raw transaction, normalized transaction, classification override, category override, benefit override, and label override were identical before Set, before Restore, and after Restore. Other benefit overrides remained 18; the total became 19 when the target's audit row was created and remained 19 after Restore. The publication ID stayed `6c611cff-3ad9-4e7c-abc7-f0c5545c8b5b`, with the same published timestamp, request/handled sequences, and no running sync. September gross `$6,441.55`, refunds `$1,601.47`, reimbursements `$37.50`, benefits `$210.26`, and net spending `$4,592.32` remained identical; Membership stayed at 116 transactions, `$475.28` benefits, and `$2,009.14` net cost.

**M2 acceptance result:** Passed. The manual pin was created even though it equaled automatic, Restore cleared the active decision while preserving audit metadata, and the effective financial interpretation was unchanged throughout.
