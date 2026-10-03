# M5 cron acceptance on the synthetic project — 2026-10-02/03

**Status: bounded synthetic run, not a GO decision.** Real path: Supabase Cron (pg_cron) → pg_net → Vercel preview (`POST /trigger`, HMAC + single-use nonce) → `api.jobs.tick(backup_fn=None)` → `api.services.sync_all` → Supabase Postgres through the Supavisor session pooler. Synthetic Plaid client only (database-driven fixture); **no real Plaid call, no Production access**.

Legend: **[M]** measured in this run; **[E]** estimate or inference; **[D]** official documentation (checked 2026-10-02).

Times are UTC (EDT + 4 h). Small samples: nothing here is a run-level p95.

## 1. Setup

| Item | Value |
| --- | --- |
| Supabase project | `acyghoemtdrilsdszolq` (`pft-m5-synthetic-20261001`, Free, PG 17.11, us-east-1) [M] |
| Fixture | migration `m5_cron_acceptance_fixture`: private schema `pft_m5_cron`, copied from the synthetic `pft_m5_bench_2610` (5 Items, 13 accounts, 2,625 raw + 2,625 normalized rows) under user `synthetic-cron`; only `pft_m5_jobs` has access [M] |
| Dispatch | migration `m5_cron_dispatch`: `pg_cron` 1.6.4, `pg_net` 0.20.4, `pft_ops.trigger_signature` (same signer as the tested template), `pft_ops.dispatch_tick(timeout_ms, source)` reading the HMAC key and the Vercel automation-bypass value from Vault [M] |
| Endpoint | `experiments/m5_cloud/cron_jobs_app.py` as `main.py` on project `pft-m5-jobs-20261001` (team `pft2`, Hobby, iad1); preview `dpl_S8nSP25gk85ZQ2zPdxiUiGNSXqgj`, `target: preview`, built from commit `97c8ba3` [M] |
| Application deadline | **210 s** (`service.MAX_RUN_SECONDS`, set by the adapter) = 0.70 × D, D = 300 s configured `maxDuration` [M config] |
| Jobs role | password rotated (SCRAM verifier only in SQL); `idle_session_timeout = idle_in_transaction_session_timeout = 330s` (> D) [M] |
| Delivery evidence | `pft_m5_cron.deliveries`: a row when an authenticated delivery starts, updated when it finishes; a platform-terminated delivery keeps `finished_at` NULL |

Deviation from P2-3 (owner choice in session): preview + bypass header from Vault instead of "unprotected production target + HMAC". See the handoff "待决".

## 2. Pooler lock behaviour (precondition) [M]

Evidence: [pooler-lock-probe.json](evidence/m5-2026-10-02/cloud/pooler-lock-probe.json). Local client through `aws-0-us-east-1.pooler.supabase.com:5432`, synthetic jobs role, verified TLS.

| Trial | Result |
| --- | --- |
| SIGKILL × 3 | lock released after 0.094–0.098 s; **backend not terminated** (≥ 60–120 s) and handed to the next client 9/9 times; no re-entry observed |
| SIGSTOP 90 s | lock held for the whole 90 s |
| SIGSTOP + session `idle_session_timeout=20s` | backend ended and lock released at 20.01 s; backend not reused |

Consequences (commit `e24f883`): lock acquisition refuses a key already held by the same backend (re-entry would leave a count behind after unlock) and invalidates the connection; the jobs role gets 330 s idle timeouts so a frozen client cannot hold the locks indefinitely.

## 3. Scenario results

Summary (all [M] unless marked):

| # | Scenario | Trigger | Result | Handler | Evidence |
| --- | --- | --- | --- | --- | --- |
| S0 | Smoke | pg_net, 01:42:16 | 200 idle; backend `idle_session_timeout` = 330s; engine checkouts ≤ 3 | 0.57 s | deliveries row, net response 1 |
| S1 | Authentication negatives (8 requests, direct HTTPS) | local controller | missing / wrong-secret / wrong-audience / stale / tampered body → 401; no bypass → Vercel 401 "Protected deployment"; valid → 200; exact replay → 409 | 0.16–0.91 s client | [auth-negatives.json](evidence/m5-2026-10-02/cloud/auth-negatives.json) |
| S2 | Duplicate / concurrent delivery | — | see S9 below | | |
| S3 | Multi-page catch-up, 5 Items × 4 pages × 500 rows | **real cron 01:50** | success, 10,000 rows added and published, 12,625 classified (1.4 s) | 65.7 s | [obs-s3-multipage-catchup.json](evidence/m5-2026-10-02/cloud/obs-s3-multipage-catchup.json) |
| S4 | Pagination mutation once, then retry | **real cron 01:55** | item 0: restart from original cursor, `retry_count = 1`, 300 rows, success | 8.4 s | [obs-s4s5-retry-partial.json](evidence/m5-2026-10-02/cloud/obs-s4s5-retry-partial.json) |
| S5 | Partial failure (one Item Plaid error) | same delivery as S4 | run `partial`; item 1 `failed/plaid_error`, `sync_retry_count = 1`, next retry +15 min; items 0 and 2 published | (same) | same |
| S5b | Retry after backoff | pg_net 03:26:50 | items 1, 3, 4 (all past their retry time) succeed; every backoff cleared (`next_sync_retry_at` NULL, count 0) | 3.1 s | MCP transcript in this document |
| S8 | Lost response | pg_net with 5 s timeout, 01:55:29 | pg_net `timed_out`; the function was **not** cancelled: finished at +14.2 s, run success, published, cursor advanced | 14.1 s | net response 4 + deliveries row |

Cron cadence (real pg_cron, two ticks before the owner asked for no resident schedule): run start 01:50:00.103 and 01:55:00.117; delivery received 0.43 s and 0.31 s after the scheduled minute (warm instance) [M, n = 2: not a jitter distribution].

### S6 — application deadline (manual trigger, 02:01:59) [M]

Evidence: [s6-deadline.json](evidence/m5-2026-10-02/cloud/s6-deadline.json). Fixture: items 3 and 4, 5 pages × 25 s each (about 250 s of fetch), deadline 210 s.

- Run `failed / run_deadline`, 209.9 s, **unpublished**; item 3 fetched all 5 pages and was rolled back (`publication_rolled_back`), item 4 stopped in fetch (`run_deadline`, 3 pages, 1 transient retry). No generation-3 row exists; cursors unchanged.
- Both Items recorded the first retry step (15 min, `sync_retry_count = 1`).
- Handler 210.6 s, HTTP 500 to pg_net (the service raises after finalizing). **Reserve 89.4 s against D = 300 s**, above the 60 s target.
- 1 s sampling: ≤ 3 jobs backends, ≤ 1 idle-in-transaction; both advisory locks free one second after the handler ended.
- The delivery landed on a new instance (previous one idle ~6.5 min); dispatch-to-receipt 2.78 s including cold start [M], against 0.43 s for a warm instance at 01:50.

### S7 — platform termination (hard kill) [M]

Evidence: [s7-hard-termination.json](evidence/m5-2026-10-02/cloud/s7-hard-termination.json). Item 2 publishes one page; the adapter then blocks the event loop for 400 s inside the publication transaction, so only the platform can end the invocation (D = 300 s).

- **The invocation was ended at ~300 s**: pg_net recorded `Timeout of 300000 ms`; the delivery row kept `finished_at` NULL; no handler, `finally` or finalization ran.
- **Locks were released when the platform ended it**: both advisory locks were held at 03:32:22.112 and free at 03:32:23.126, ~300.8 s after receipt; 3 → 1 jobs backend at the same second. The 330 s idle-in-transaction timeout (due ~03:32:53) was not needed in this trial. One idle pooled backend stayed until 03:34:21. (n = 1; whether a termination can instead freeze the process is not excluded — the 330 s timeouts remain the bound.)
- **The next tick reconciled it** (manual dispatch, 05:11:08): run `interrupted / interrupted`, unpublished; item run `interrupted`; cursor unchanged; Item 2 backed off 15 min (`sync_retry_count = 1`); 0 generation-3 rows; no `running` row left. The reconciling delivery itself returned `idle` in 0.63 s because Item 2 was now backed off.
- Observation [M]: during a run **all three jobs sessions are "idle in transaction"**, including both lock connections: SQLAlchemy autobegins on the owner checks after `acquire_session_lock` commits. The 330 s idle-in-transaction timeout therefore also bounds the lock connections, and each keeps a snapshot open for the run. Candidate M6 change: commit (or use autocommit) after each owner check. Not changed tonight.

<!-- Remaining scenario rows are filled in as each scenario completes. -->
