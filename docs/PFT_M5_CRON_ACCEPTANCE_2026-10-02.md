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

### S6 — application deadline (manual trigger, 02:01:59) [M]

Evidence: [s6-deadline.json](evidence/m5-2026-10-02/cloud/s6-deadline.json). Fixture: items 3 and 4, 5 pages × 25 s each (about 250 s of fetch), deadline 210 s.

- Run `failed / run_deadline`, 209.9 s, **unpublished**; item 3 fetched all 5 pages and was rolled back (`publication_rolled_back`), item 4 stopped in fetch (`run_deadline`, 3 pages, 1 transient retry). No generation-3 row exists; cursors unchanged.
- Both Items recorded the first retry step (15 min, `sync_retry_count = 1`).
- Handler 210.6 s, HTTP 500 to pg_net (the service raises after finalizing). **Reserve 89.4 s against D = 300 s**, above the 60 s target.
- 1 s sampling: ≤ 3 jobs backends, ≤ 1 idle-in-transaction; both advisory locks free one second after the handler ended.
- The delivery landed on a new instance (previous one idle ~6.5 min); dispatch-to-receipt 2.78 s including cold start [M], against 0.43 s for a warm instance at 01:50.

<!-- Remaining scenario rows are filled in as each scenario completes. -->
