# M3 Dining Production reopen — 2026-09-29

**Migration owner-accepted. Reviewed reopen complete; final owner runtime acceptance pending.**

The exact pinned web returned to localhost:3000, the original private Tailscale
HTTPS handler was restored, and the exact pinned jobs scheduler resumed. API and
database stayed in place. No additional migration, forced sync, or M4 work occurred.
Checks ran on September 29 EDT / September 30 UTC.

## Runtime results

- API/web/DB are running and healthy. All affected services use the approved image
  IDs recorded in the [execution report](PFT_PHASE_2_M3_DINING_PRODUCTION_EXECUTION_2026-09-29.md).
  All container restart counts are zero; the database container and authority
  volume are unchanged.
- Jobs is running `python -m api.jobs`. It has no Docker healthcheck; its operational
  health was verified through advancing heartbeats, the sync-status API, and its
  error-free startup/runtime log.
- First resumed heartbeat: **2026-09-30 01:06:57.743678 UTC**. Subsequent observed
  heartbeat: **01:09:58.028649 UTC**, spanning multiple scheduler ticks.
- Before resume there were no due Items, queued requests, or running syncs.
  After resume there were **zero new sync runs**, no catch-up, no errors, and no
  changes to request/publication/backup state. Backup status remains healthy.
- The only database difference from the accepted migration after-state is
  `sync_runtime_state.jobs_heartbeat_at`. All other **14 table fingerprints** match
  exactly, including every manual override, raw/normalized transaction, Item,
  account, benefit, label, classification, cursor, and sync audit row.

## Access and application checks

Overview, Review, and Membership each returned HTTP 200 on localhost:3000 and
`https://pft-host.tailc4d964.ts.net`. The HTTPS check used the actual private
Tailscale endpoint, with certificate validation enabled. Its API monthly response
matched localhost exactly. The Serve configuration contains only the original
HTTPS 443 handler pointing to localhost:3000; staging port 3004 is no longer used.

Read-only API checks confirmed:

- DINING is exposed as **Dining**, GROCERIES remains separate, and FOOD_AND_DRINK
  is absent from manual options. The obsolete manual filter returns HTTP 422.
- Dining spending filters and canonical Net Spending detail IDs/contributions
  match the accepted September preview exactly.
- September Overview totals and Membership YTD/trailing-12-month outputs match
  the accepted baseline. September Net Spending remains **4,634.29**.
- Manual DINING remains **80 active / 0 cleared**; manual FOOD_AND_DRINK remains
  **0 active / 0 cleared**. All **573** normalized source FOOD_AND_DRINK values and
  the raw-table fingerprint remain preserved.

Rendered browser smoke checks passed at **390 and 1440 px**:

- Overview Dining net drill-down and active category filter.
- Category editor opens with migrated Dining selected; Dining/Groceries selection,
  enabled Save control, and Cancel work. The old manual code is unavailable.
- Review loads, switches to Credits & Transfers, and applies the direction filter.
- Membership loads its summary. No page errors, failed API responses, or tested
  page overflow occurred.

**No category save was submitted.** Edit controls were checked through selection
and cancel; Production persistence was not exercised during this read-only smoke.
Browser mutations and external requests were blocked. The existing Plaid Link SDK
download was blocked before network access. No manual Plaid calls or sync requests
were made, and the resumed scheduler performed no sync run.

## Evidence and rollback

All 46 sealed migration/execution artifacts remain hash-identical, and all three
rollback images remain available. New runtime evidence is separate:

- Local: `/tmp/pft-m3-dining-reopen-20260929`
- Protected Windows copy:
  `C:\Users\tianr\PFTBackups\Production\M3-Dining-20260929\reopen`
- Evidence includes before/after table fingerprints, scheduler snapshots, worker
  logs, HTTP/UI results, exact service identities, `runtime-summary.json`, and a
  SHA-256 inventory. Windows ACLs restrict access to the owner, Administrators,
  and SYSTEM; the directory uses the previously owner-confirmed encrypted C: drive.

The guarded reverse procedure and original manifests are preserved unchanged.
**Automatic reverse is now ineligible because the normal jobs heartbeat has
advanced.** The guard must remain intact; do not bypass it or rewrite evidence.
Any rollback after reopening requires checking current state and reviewing a
recovery plan that preserves subsequent application activity.

Stop here for final owner runtime acceptance. No M4 work has begun.
