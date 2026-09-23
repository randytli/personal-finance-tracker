# M6 runtime/recovery acceptance in progress (2026-09-23)

This continues the approved [initial Production sync](PFT_M6_INITIAL_SYNC_2026-09-23.md).
It is **not** M6 closure: two subsequent normal daily cycles remain. No clocks or cursors were altered, no
restore was run against Production, and no manual sync was requested.

## Recovery point and preservation baseline

- Before disruption, confirmed exactly five active/unpaused Items and one
  published run. The old `personal-finance-tracker-db-production-backfill-1`
  was exited with restart `no`; `pft-runtime-db-1` alone mounted the exact
  Production volume `personal-finance-tracker_pgdata_production_backfill`.
- Created a new protected `extra` checkpoint using the backup-only one-off
  command: `pft-extra-20260923T202320753385Z.dump`, 486,777 bytes, SHA-256
  `aba2f66c3a551690e6971dcb732d01fe925cb7f8773444a621a85dfed0f6863a`.
  Manifest size/checksum, archive listing, and restricted Windows ACL passed.
  The independently restore-verified post-sync checkpoint from stage 2 remains
  available. Captured a read-only, UTC-normalized fingerprint of all 15
  Production tables before the tests.

## Container and Docker Desktop recovery

- Restarted web, API, jobs, then DB individually. Web/API/DB health checks
  recovered; proxied status and September analytics returned 200. Jobs wrote
  a new heartbeat after restart. The run count stayed one and the published
  run marker remained `a2366920-bdf0-475a-8c96-e39216c14b06`. The DB
  reused the same volume; the old DB did not start.
- The WSL/Linux `docker desktop restart` CLI could not start a nonexistent
  Linux Desktop backend path and did not restart the engine. Used the installed
  **Windows-native** `docker.exe desktop restart --timeout 180` instead; it
  succeeded. Docker Desktop's session ID changed from
  `8d7c80c8-b4c0-4045-a77c-8f454d1f738c` to
  `c5307c85-de69-4ff7-8dd5-90e91bcb76f2`. All four `pft-runtime`
  containers restarted automatically around `20:29:40Z`; DB/API/web became
  healthy, jobs resumed, Windows-host web returned 200, and status/analytics
  returned 200. The old DB remained exited and the new DB was the sole
  running Production-volume owner. Five active Items, one run, 2,610 raw and
  2,610 normalized rows, and the publication marker were preserved.

## Offline and sleep/resume

- Temporarily disconnected **only** `pft-runtime-jobs-1` from
  `pft-runtime_default`, keeping API, web, and DB connected. During the
  outage, `/api/pft/sync/status` and September analytics returned 200; the
  month response was byte-for-byte equal to its online response with net
  spending `4421.50`. After the documented seven-minute heartbeat grace
  period, status showed `jobs=stopped`, `backup=healthy`, and the same
  publication marker. Reconnected jobs to the original network with alias
  `jobs`. The first delayed tick carried its original timestamp; the next
  normal poll wrote a fresh heartbeat at `20:40:21Z`, and status returned to
  `jobs=running`. No duplicate or premature sync occurred: the run count
  remained one.
- Windows reported S3 sleep as available. With the user ready to wake the PC,
  a temporary script called `SetSuspendState(false, false, false)`, which
  returned success. Windows Power-Troubleshooter recorded sleep from
  `2026-09-23 16:42:00` to `16:44:43` local time (about 2 minutes 43 seconds),
  and `powercfg /lastwake` identified the power button. After resume,
  Production containers were still running/healthy, the old DB remained
  exited, and the new DB alone mounted Production. Windows-host web and
  status, plus proxied September analytics, returned 200. Jobs had a fresh
  heartbeat, backup was healthy, the same single run and publication marker
  remained, and September net spending stayed `4421.50`.
- The post-recovery read-only fingerprint matched the pre-restart snapshot for
  every financial table, Item/account scope, source breakdown, and integrity
  check. All checked integrity counts remained zero. Only
  `sync_runtime_state` changed, as expected from normal heartbeat updates.

## Windows sign-in and elapsed-time gates

- The first actual Windows sign-out/sign-in check found Docker Desktop had not
  started: before any manual Desktop launch, its Windows status command did not
  complete, no Desktop/backend process was present, the WSL Docker daemon was
  unavailable, and the Windows-host web endpoint did not respond. The saved
  Docker Desktop setting showed `AutoStart: false`, while an HKCU Run entry
  existed and Windows StartupApproved showed the entry disabled. Starting
  Desktop manually with Windows-native `docker.exe desktop start --timeout 180`
  recovered all four `unless-stopped` runtime containers automatically; the
  old DB stayed exited, the new DB retained sole Production-volume ownership,
  and web/status/analytics returned 200. Five active Items, one sync run,
  2,610 raw and 2,610 normalized rows, and the publication marker remained.
- The user then enabled both Docker Desktop's **Start Docker Desktop when you
  sign in** setting and Windows Apps > Startup. A read-only settings check
  confirmed `AutoStart: true`, Ubuntu WSL integration, and the Windows
  StartupApproved Run entry enabled (`000000...`). Immediately before the
  repeat sign-in test, the read-only preservation digest across the 14 non-heartbeat
  tables plus institution scope, source breakdown, and integrity was
  `0e7eca1bfab232e3f318bb768eece0348d0f5ee8a42c5ca4166b82cdd38fdf79`.
  It matched the fingerprint taken after the first sign-in recovery. The
  `sync_runtime_state` heartbeat is deliberately excluded from this comparison.
- The repeat actual Windows sign-out/sign-in **passed**. Without manually
  starting Docker Desktop, Windows-native `docker.exe desktop status` reported
  `running` with a new session ID
  `9caf2911-65e7-4864-9c38-b739c6cbe599`. All four Production containers
  auto-resumed and were healthy. The old DB remained exited; the new DB alone
  mounted the Production volume. The Windows-host web, sync-status, and
  September monthly analytics endpoints returned 200. Status showed jobs
  `running`, backup `healthy`, unchanged five-active-Item scope, and the same
  single published run ID. The monthly net stayed `4421.50`, with 11 Review
  items. After sign-in, the 14-table/institution/source/integrity digest was
  exactly `0e7eca1bfab232e3f318bb768eece0348d0f5ee8a42c5ca4166b82cdd38fdf79`;
  there were still 2,610 raw and 2,610 normalized rows, and all four checked
  integrity counts were zero. No manual Desktop or Production service start
  was needed.
- An overdue startup catch-up was **not applicable yet**: the first successful
  run occurred at `2026-09-23 20:07:49Z`, and the tested restarts/outage/sleep
  were all within its 24-hour scheduling interval. No clock or cursor was
  forced to create an artificial overdue case. Two subsequent normal daily
  cycles must occur naturally and be checked for backup-before-sync, five-Item
  outcomes, marker, health, and financial reconciliation. They cannot be
  certified from the initial run or these short recovery tests. A future
  real downtime crossing a due time can supply overdue catch-up evidence.

No Production Plaid call or financial-data mutation was caused by the
restart/offline/sleep checks. Jobs remain connected and running. Keep M6 open
until two naturally elapsed daily cycles are verified.
