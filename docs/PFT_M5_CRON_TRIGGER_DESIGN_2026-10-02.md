# M5 scheduled trigger (Cron) — design and endpoint authentication (2026-10-02)

**Status: design plus local code and tests. This does not close inventory item R4.** Nothing was scheduled, enabled or deployed. Supabase, Vercel and Production were not contacted. All limits below were looked up on 2026-10-02 unless marked otherwise.

Legend: **[M]** measured locally tonight; **[D]** official documentation quote; **[E]** estimate or inference; **未核实** not verified.

## 1. What the trigger must preserve

From `api/jobs.py`, `api/services/sync_all.py` and plan §12.3:

| Current behaviour (Windows jobs loop) | Source |
| --- | --- |
| Poll every **60 s** (`POLL_SECONDS`); each tick holds the `pft-jobs:<user>` session advisory lock | `api/jobs.py` |
| Item due **24 h** after last success (`due_items`) | `api/services/sync_state.py` |
| Retry after blocked/failed Items: **15 min → 1 h → 6 h** (`RETRY_DELAYS`), persisted in `next_sync_retry_at` | `api/services/sync_all.py:39` |
| Manual request: coalesced `requested/running/handled_sequence`; picked up at the next tick (≤ 60 s today) | `api/jobs.py:request_sync`, `tick` |
| Daily backup when `last_backup_at` ≤ now − 24 h; runs before sync; a failure does not block sync | `api/jobs.py:tick` |
| Idle tick still calls `sync_all` to reconcile interrupted runs | `api/jobs.py:tick` |

Every due, retry and manual decision is already **durable in the database**. The trigger only needs to deliver "run one tick now" often enough. It does not need to remember anything itself.

## 2. Candidates on the free tiers

| | Supabase Cron (pg_cron + pg_net) | Vercel Cron on Hobby |
| --- | --- | --- |
| Cadence | Cron syntax plus sub-minute: "You can use [1-59] seconds (e.g. '30 seconds')" (needs Postgres ≥ 15.1.1.61) [D, [quickstart](https://supabase.com/docs/guides/cron/quickstart)] | "Once per day"; "Expressions that run more frequently will fail deployment" [D, [usage & pricing](https://vercel.com/docs/cron-jobs/usage-and-pricing), page last updated 2026-07-15] |
| Precision | Per schedule; real jitter 未核实 | "Per-hour (±59 min)"; `0 8 * * *` "could trigger an invocation anytime between 08:00:00 and 08:59:59" [D, [manage](https://vercel.com/docs/cron-jobs/manage-cron-jobs)] |
| Free-plan availability | Docs state no plan restriction; actual Free-project enablement 未核实 (the M5 project never enabled it) | "Cron Jobs are available on all plans"; 100 per project [D] |
| Retries | pg_cron: no documented retry for scheduled jobs (未核实). pg_net: retries not documented. | "Vercel will not retry an invocation if a cron job fails" [D] |
| Delivery guarantees | pg_net requests and responses "are stored in unlogged tables, which are not preserved during a crash or unclean shutdown"; "HTTP requests are not started until the transaction is committed" [D, [pg_net](https://supabase.com/docs/guides/database/extensions/pg_net)] | "Cron job delivery is best effort … occasional transient network errors can prevent a request from reaching your function"; "can also occasionally invoke the same scheduled run more than once" [D] |
| Overlap | Each pg_cron run only enqueues HTTP and finishes; overlap is handled at the endpoint (advisory lock) | "Vercel can trigger a second instance while the first is still running" [D] |
| HTTP timeout | Default **2,000 ms** [D]. Settable per request (`timeout_milliseconds`); documented maximum 未核实 | Function duration limits apply [D] |
| Recommended load | "no more than 8 Jobs run concurrently. Each Job should run no more than 10 minutes" [D, [cron](https://supabase.com/docs/guides/cron)]; pg_net "Intended to handle at most 200 requests per second" [D] | — |
| History / logs | `cron.job_run_details` "grows with every Job run and is never cleaned up automatically" [D, quickstart]. `net._http_response` kept "for 6 hours" by default (`pg_net.ttl`) [D] | Runtime logs; Hobby log retention 1 hour (feasibility pass, 2026-10-01) |
| Auth to endpoint | Signed header computed in SQL from a Vault secret (§4) | `CRON_SECRET` sent as `Authorization: Bearer …` [D] |
| Reaching a protected deployment | Needs a reachable endpoint. Preview protection returned 302 without bypass in M5 [M, compatibility pass]. A production deployment or automation bypass is required: **decision P2-3** | Vercel-internal |
| When the DB is paused | Cron lives in the paused DB, so **nothing fires** | Fires, but the function cannot reach the DB; errors are visible |

**Mapping to current semantics, at a 5-minute Supabase tick [E]:**
- 24 h due → 24 h to 24 h 5 min.
- 15 min retry → 15–20 min; 1 h → 1 h–1 h 5 min; 6 h → 6 h–6 h 5 min.
- Manual request: ≤ 5 min plus delivery time, versus ≤ 60 s today. The UI must say "queued" rather than imply that it is running (plan §12.4).
- 8,640 invocations per 30 days, far below Vercel Hobby's 1 million (feasibility pass). A 1-minute tick (43,200 per month) would restore today's latency. Its CPU and connection cost are unmeasured: **decision P2-1**.

**Vercel Hobby cannot preserve these semantics.** It has one run per day with up to 59 minutes of drift and no retry. The 15 min, 1 h and 6 h retries collapse to "next day", and manual requests wait up to 24 h. This confirms the feasibility BLOCKER. GitHub Actions `schedule` (minimum "once every 5 minutes", runs "can be delayed during periods of high loads … some queued jobs may be dropped") [D, [events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)] would be possible only as a fallback trigger. It is not recommended as the primary because of the documented drops at peak times.

**Recommendation: Supabase Cron, one job, `*/5 * * * *`.**
- Signed `net.http_post` straight to the protected Python jobs endpoint. Never through the Next.js rewrite, which has a 120 s proxy cap.
- `timeout_milliseconds` ≥ function `maxDuration` (300 s), so pg_net keeps the connection while Python runs. The maximum pg_net accepts is 未核实 and is the first cloud test.
- A second daily job prunes `cron.job_run_details` older than 14 days.

## 3. Does scheduled sync keep a Free project active?

Official text [D, [project pausing](https://supabase.com/docs/guides/platform/free-project-pausing); [pricing](https://supabase.com/pricing)]:
- "Free projects are paused after 1 week of inactivity" (pricing).
- "A Free plan project is considered inactive if it does not receive sufficient user database activity over the past week."
- "Typically a few user requests to the database each day over the previous week is enough to keep the project from being paused."
- Prevention per the guide: "To prevent future automatic pausing, upgrade to the Pro Plan from Billing Settings."
- Warnings: "A warning email roughly one week before the pause takes effect", and a confirmation email after pausing.
- Restore: "You can restore a paused project for up to 1 year after it was paused."

Assessment:
- **pg_cron alone** is activity inside the database. Whether it counts as "user database activity" is not stated: 未核实.
- **The real sync path** is different. Each tick, Vercel jobs connects back through Supavisor and runs application queries as the jobs role. That is genuine external application traffic, and on the documented wording it is likely to count [E].
- **Not artificial keep-alive.** This is the product doing its job, not keep-alive traffic. Plan §12.5 forbids "artificial keepalive to evade policy", so the design adds **no** extra ping. If the provider's measure of activity excludes it, the project may still pause. That must be observed, not engineered around.
- **Consequence if it pauses:** cron stops with it, so the system cannot recover itself. The owner gets the warning email, and the stale-sync and overdue-backup warnings fire. The independent backup is unaffected (backup design §1.3).
- **Decision P2-2:** accept this, given that the documented prevention route is a paid upgrade.

## 4. Endpoint authentication

Implemented in `api/trigger_auth.py` (not mounted in `api/main.py`). The SQL signer is in `experiments/m5_cloud/trigger_cron.sql.template`.

- **Header:** `x-pft-trigger-signature: kid=<id>,ts=<unix>,nonce=<32 hex>,sig=<64 hex>`.
- **MAC:** HMAC-SHA256 over `pft-trigger-v1`, audience, key ID, timestamp, nonce, `POST`, the pinned path and SHA-256 of the canonical JSON body.
  - The audience is a per-environment label such as `pft-jobs-production`. A signature from the synthetic environment fails against Production even if a key were accidentally shared.
  - The body is canonicalised because the exact bytes pg_net produces from `jsonb` are 未核实. The MAC covers the parsed object's canonical form, not raw bytes. Body size is capped at 4 KB before parsing.
- **Verification order** (`verify`, pure, no I/O):
  1. Configuration: ≥ 32-byte keys and an audience, else 503.
  2. Method and pinned path, else 404.
  3. Size, else 413.
  4. Exactly one header, matched case-insensitively.
  5. Format, then known key ID.
  6. Constant-time MAC compare.
  7. Timestamp within **±300 s**.
  8. Payload exactly `{"kind": "tick"}`.
- **Replay protection:** after verification, `handle_trigger` claims the nonce in its **own committed transaction** (`SqlNonceStore`: primary-key insert, then delete rows past their window). A replay inside the window returns **409** and never runs. After the window the timestamp check rejects it. A forged request never touches the nonce table or `run_once`.
- **Rotation:** `keys` accepts two key IDs at once. Add `v2` to Vault and Vercel, switch the cron to `v2`, then remove `v1`.
- **Why HMAC and not a static bearer like Vercel's `CRON_SECRET`:**
  - The signed header passes through `net.http_request_queue` and possibly logs.
  - A leaked signature is useful for at most 5 minutes, once, against one audience.
  - A leaked bearer is useful until rotation.
- **Secret placement:** Supabase Vault (read only inside the cron command) and the Vercel jobs project's encrypted environment. Never in SQL text, `cron.job`, the repo or the browser.
- **Relation to the advisory lock:** authentication happens before any lock or database work. A valid overlapping delivery reaches `tick`, whose `pft-jobs:<user>` advisory lock returns `busy` without calling sync. Durable request coalescing is unchanged. Tested [M]: of two concurrent valid deliveries with distinct nonces, the second returns `busy` and only one sync runs. A third delivery after release succeeds.
- **What HTTP 200 means:** the payload only reports this delivery's tick status. Completion evidence remains the durable `sync_runs` / `sync_runtime_state`. A pg_net timeout or a lost response is never treated as failure or success (plan §12.4).

### Tests [M]

`tests/test_m5_trigger_auth.py`: **10 pass**. 4 use a database (`PFT_M5_TRIGGER_SYNTHETIC_TEST=1`, disposable PG 16 on 127.0.0.1:55439).

- **Valid cases:** valid signature with pg_net-style spacing; upper-case header name.
- **Rejected requests:** missing, malformed, unknown key, wrong secret, duplicate header; wrong audience, path or method; body tampering, invalid JSON, oversize body, unsupported kind.
- **Timestamp window:** boundary values accepted, one second outside rejected.
- **Rotation and configuration:** both key IDs accepted during rotation; missing or short keys and missing audience fail closed with 503.
- **`handle_trigger`:** a replay returns 409 and runs nothing; a forgery neither runs nor claims a nonce; the response never echoes the secret.
- **SQL signer:** the template rendered with pgcrypto produces headers that `verify` accepts, with distinct nonces per call; the same header fails under another audience.
- **`SqlNonceStore`:** single use, expired rows pruned, table name validated.
- **Advisory lock:** overlapping deliveries are serialised by the existing jobs lock via `run_scheduler_once`.

## 5. Still open (cloud tests, need approval)

1. Enable `pg_cron`, `pg_net` and Vault on the **synthetic** M5 project. Verify Free availability, the maximum `timeout_milliseconds`, and the exact body bytes sent.
2. Deploy a jobs preview with this verification in front of `run_scheduler_once`. Choose how pg_net reaches it through deployment protection (P2-3).
3. Observe real cadence and jitter. Inject duplicates and timeouts. Confirm that durable state, not the net response, decides the outcome. Run one deliberately overdue interval. Prune history.
4. **Honest status (R15):** replace the 7-minute heartbeat interpretation with last trigger / start / completion and next due / retry. "Idle and healthy" must not hide stale bank or backup state.
5. **Known gap carried from M5 (R10):** cancellation leaves a durable `running` row until the next owner reconciles it. On a 5-minute tick that bounds staleness to about 5 minutes [E], but the unattended policy still needs review.
6. **Backup separation (R3):** the backup design recommends taking backups out of `tick`. If they stay in, the 300 s function must fit backup plus sync.

## 6. Files

- `api/trigger_auth.py`: verification, `handle_trigger`, memory and SQL nonce stores.
- `experiments/m5_cloud/trigger_cron.sql.template`: SQL signer, nonce table, commented-out schedules.
- `tests/test_m5_trigger_auth.py`: tests.
