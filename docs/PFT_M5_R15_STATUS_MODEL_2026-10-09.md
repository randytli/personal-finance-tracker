# M5 R15: an honest status model for serverless ticks — design draft, 2026-10-09

Status: **design only. No code, no measurement.** This is input for M6. Owner decisions are marked **D**.

## Why the current model does not carry over

`api/routes/sync.py` reports jobs as `running` when either signal holds:
- the heartbeat `sync_runtime_state.jobs_heartbeat_at` is less than 7 minutes old;
- the session advisory lock `pft-jobs:<user>` is held.

On Vercel with Supabase Cron neither signal means "a process exists":

1. **There is no resident process.** The heartbeat is written only when a delivery arrives. A 5-minute cron tick makes it look fresh, but freshness actually reflects **pg_cron + pg_net + Vercel delivery + auth**, not a loop. The status must say which link failed.
2. **The advisory lock only exists during a tick.** Seeing it held means "a delivery is executing now", not "jobs is alive". After a platform kill, S7 measured the lock released within about 1 s.
3. **pg_net exposes delivery results.** `net._http_response` holds the status code or a timeout. A tick can be dispatched and still fail at the edge, for example with Vercel 401 or a timeout. The current model cannot see that.
4. **Pause.** A paused Supabase Free project stops pg_cron itself. Nothing inside the project can report this; only an external observer can (R5).

## Proposed signals (all already durable or cheap)

| Signal | Source | Meaning |
| --- | --- | --- |
| `last_tick_dispatched_at` | `cron.job_run_details` for `pft-tick` (end time, status) | The scheduler fired |
| `last_tick_received_at` | Written by the endpoint after HMAC acceptance (today: the heartbeat write) | The delivery reached the app and authenticated |
| `last_tick_outcome` | `idle` / `busy` / `ran` / `failed` / `deadline`, written at the end of the handler | The app finished the tick |
| `last_delivery_http` | Latest `net._http_response` row for the tick's request id (status or `timed_out`) | What the edge returned. A timeout alone is not a failure: S8 showed the work can still complete |
| current run | `sync_runs` row with `status='running'` plus lock held | A run is in progress |
| interrupted runs | `sync_runs.status='interrupted'` (R10 reconciliation) | The previous delivery was killed |

## Derived states (shown on the health panel)

| State | Rule (5-minute tick, T = 5 min) |
| --- | --- |
| `healthy` | received within 2T and the last outcome is not `failed`/`deadline` |
| `running` | lock held and a `running` row is younger than D = 300 s |
| `degraded` | received within 2T, but the last outcome is `failed`/`deadline`, or the last run was `interrupted` |
| `delivery_failing` | dispatched within 2T but not received within 2T. Show the last HTTP status or timeout from pg_net |
| `scheduler_silent` | nothing dispatched within 2T: cron unscheduled, broken, or project paused |
| `unknown` | the status API itself cannot reach the database. The UI shows this, never `healthy` |

Per-institution freshness (`last_success_at`, `next_retry_at`) stays as it is today. It already describes bank data truthfully.

## Rules

- Never report `running`/`healthy` on the lock alone. Under serverless, a lock means only "a delivery is executing".
- Thresholds derive from the configured tick interval. They are not constants copied from the local 60 s loop.
- The 7-minute heartbeat grace exists today because a local tick can spend 5 minutes syncing. It is replaced by `running` (lock plus a young `running` row).
- Reading `cron.*` and `net.*` needs a narrowly granted view, because those schemas are not exposed to the app roles. **D1:** add a `pft_ops.tick_health` view that is security-definer and read-only, or read only `last_tick_*` from `sync_runtime_state` and accept that dispatch failures cannot be seen.
- An external check for pause (R5) is out of scope here. **D2:** rely on Supabase's warning e-mail, or add a free external uptime ping. The plan forbids keep-alive traffic, so a ping must be read-only and infrequent, and it must be shown that it does not count as activity (未核实).

## Test plan for M6 (local, synthetic)

- Unit-test the derivation table above with fixed clocks. Cover every state, including the S7 sequence: `running` → kill → `interrupted` → `degraded`.
- On the synthetic project, after approval: unschedule the cron job, expect `scheduler_silent` within 2T; then revoke the HMAC key, expect `delivery_failing` with HTTP 401.
