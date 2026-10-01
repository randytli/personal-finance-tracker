# M5 bounded real-cloud latency and cancellation — 2026-10-01

**The 2,610-row no-op completes with substantial observed headroom. The unchanged 35,600-row no-op fails the growth envelope: all five attempts time out before publication at the 210-second application deadline. Cancellation preserves financial state and releases locks, but explicit cancellation leaves a durable `running` record until next-owner reconciliation. SERVERLESS_GO remains withheld.**

Later owner-approved follow-up: the [sync round-trip amplification fix](PFT_M5_SYNC_ROUND_TRIP_FIX_2026-10-01.md) replaces per-row normalization/classification writes with changed-row-only batch writes. With it, the 35,600-row no-op completes in 5/5 cloud runs (141 statements, shared-sync median 5.27 s). Data transfer still grows with history, and SERVERLESS_GO remains withheld.

The owner explicitly authorized this bounded follow-up after [compatibility probes](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md). Only existing disposable project `acyghoemtdrilsdszolq` and the existing protected Vercel jobs project were used. Production, Production env files/credentials/tokens/data and Production Plaid were not accessed. No real Plaid call, paid feature, cron, owner Auth, backup upload, B2 action or migration of Production occurred. B2 remains unapproved. Execution stopped after timing, cancellation and final preservation evidence.

[Evidence directory](evidence/m5-2026-10-01/real-cloud-latency/) contains [samples](evidence/m5-2026-10-01/real-cloud-latency/samples.json), [summary](evidence/m5-2026-10-01/real-cloud-latency/summary.json), protocol, deployment metadata, source hashes, size samples and final financial-state fingerprints. No commit/push performed.

## Protocol and preserved path

Migration `m5_bounded_synthetic_sync_fixtures` created two private schemas, `pft_m5_bench_2610` and `pft_m5_bench_35600`, inside the approved synthetic database. Each contains the unchanged SQLAlchemy model schema plus a fixture/attempt-budget manifest. Only the synthetic jobs role received table write privileges; PUBLIC/anon/authenticated access was revoked. No Data API exposure or owner Auth was introduced.

Each fixture has five active synthetic Items, 13 owned accounts including disabled consumer accounts, and exactly the stated number of raw transactions and matching normalized rows. Retained rows are distributed over five enabled credit accounts, with synthetic merchant/category/date/amount values. Fixtures were bulk-created outside timing. They reproduce the prior local synthetic shape; they are not a copy of financial history or a worst-case classification corpus.

The actual deployed `api/` and `statement_imports/` source was byte-compared with the repository before both uploads and kept unchanged. The adapter calls **`api.services.sync_all.sync_all`**, one-shot, using an explicit per-invocation engine/session factory and a strictly synthetic client. It retains persistence, revalidation, savepoints, whole-history normalization, classification, cursors, publication markers and lock cleanup. **No batching, SQL reduction or query-amplification optimization was made.** Empty synthetic SDK pages preserve the cursor and contain no added/modified/removed rows. Successful no-op publication still updates the run marker as the existing service does.

The adapter uses the existing required CA/hostname-verifying SSL context, positive backend `pg_stat_ssl`, role and sentinel checks, plus pinned private search paths, fixture counts, project ref and dataset ID. A control transaction prevents concurrent benchmark invocations. Pool size is four with no overflow; an independent observer is limited to one connection. A 200 MB database-size stop guard and 16-attempt-per-schema cap bound the prototype.

Direct jobs configuration is standard Hobby Fluid in `iad1`, 300 seconds, with large-function beta disabled. It uses no BFF/web route timeout. The reference `D=300 s` is the documented/configured direct runtime, not a forced platform-termination experiment. [Current Vercel limits](https://vercel.com/docs/functions/limitations).

For each benchmark call, the probe temporarily overrides the shared service's deadline to **210 seconds**, restores its original default afterward, and allows an outer join bound of 240 seconds. The controller waits at most 285 seconds. This preserves financial behavior while leaving cleanup reserve below the platform limit. The negative publication-timeout test uses a separate 20-second deadline and a deliberate pause after the first Item's uncommitted publication work.

Five serial no-op attempts per scale: one first benchmark request in a fresh observed process, followed by four requests in that same process. Current-scale preview: `dpl_8rCoZKyQ7S9vJgk2sL2FBotTbyXB`; grown/negative-test preview: `dpl_Ea8nMxHw3xcE5ZZ2fq9WdJDpHu9Q`, READY / `target:null`. Preview protection and independent service capability checks remained enabled. Existing automation bypass values were used transiently in controller memory, never in a URL or saved request file.

## Timing and resources

Five runs support observed ranges and medians, **not a reliable run-level p95**. Grown results are right-censored: approximately 214 seconds is time to abort, verify and respond, not successful completion time.

| Measurement | Current: 2,610 retained rows, n=5 | Grown: 35,600 retained rows, n=5 |
| --- | --- | --- |
| Completion/publication | 5/5 success, published | 0/5 complete; 5/5 timeout, unpublished |
| Client total wall, min / median / max | 19.012 / **25.335** / 29.285 s | 213.755 / **213.942** / 215.423 s, abort responses |
| Handler wall, min / median / max | 18.566 / **24.995** / 28.730 s | 212.064 / **212.223** / 213.609 s |
| Shared-sync wall | 18.341–27.615 s; median 24.751 | 210.149–210.191 s; deadline reached |
| SQL attempts in shared path | **5,361 each**, 26,805 total | **34,449; 37,832; 47,195; 46,646; 44,032**, 210,154 total before abort |
| Physical connection setup | 39.7–103.0 ms; median 73.4, 15 observations | 41.2–102.9 ms; median 61.6, 20 observations |
| Connection + identity/fixture guard | 123.4–153.9 ms | 130.9–188.6 ms |
| Sync session-lock acquisition | 9.9–20.6 ms | 11.5–24.1 ms |
| Normalization stage | 9.613–14.137 s | 163.186–209.241 s; first attempt canceled within this stage |
| Classification stage | 8.093–12.772 s | First did not reach it; four reached it for 12.499–46.151 s, all canceled |
| Item publication/persistence stage | 9.793–14.415 s, includes normalization | 163.460–209.562 s, includes normalization |
| Successful final publication transaction exit | 9.1–15.1 ms, includes flush/commit/exit | No successful publication commit |
| Failure finalization | Not applicable | 116.8–154.4 ms, plus transaction rollback/unlock in shared-sync wall |
| Final observer join/engine disposal | 5.8–8.5 ms | 6.3–39.4 ms |
| Process CPU per handler | 6.645–8.451 s | 63.293–79.616 s through abort |
| Process RSS high-water | 108.3–116.4 MiB | 126.6–203.0 MiB through abort |
| Exact benchmark-engine checkout peak | 3, including control guard | 3, including control guard |
| Extra observer connection bound | 1 | 1 |
| Sampled jobs / all database backend peaks during timing | 4 / 11 | 4 / 11 |

Stage timings overlap: normalization is inside Item publication. They must not be summed as independent phases. SQL statement counts exclude setup/verification/observer traffic and protocol-level commits; they include the shared path's SQL/savepoints and failed statement attempts. CPU covers the process during the handler, including instrumentation; it is not provider-billed CPU. RSS high-water is process-lifetime and can reflect earlier requests. The observer also samples current RSS/backend counts every 0.5 seconds; sampled peaks are not guaranteed instantaneous server peaks.

Across all **13 calls**, including three negatives, there were **238,132 shared-path SQL attempts** and **405.417 seconds of measured process CPU**. Exact application checkout peak was three plus the single observer, at most four for this serial harness. The negative scale switch observed **eight jobs / fifteen total database backends**, including idle Supavisor backends retained from other schema sessions. This is distinct from four application sockets. Final inspection found five idle TLS-positive jobs backends with zero open transactions; all invocation engines reported zero checkouts after disposal.

## Cold/warm and measured database latency

Current first-process handler: **28.730 s**, service import **0.849 s**. Four warm handlers: **18.566–27.807 s**, median **23.921 s**, imports about 5–7 microseconds. The observed first-versus-warm-median difference is **4.809 s**, but database variation also contributes; it is not an isolated cold-start penalty. Provider startup time itself is unavailable through the current tools. Client time includes TLS/routing/transport and must not be treated as internal function time.

Grown first-process handler: **213.609 s**, import **0.877 s**. Four warm handlers: **212.064–212.330 s**, median **212.147 s**. All are censored by the same deadline. There is no supported cold/warm comparison of full grown completion time; warming did not establish a passing envelope.

SQLAlchemy cursor-event observations measure **driver/database round trips for the actual queries**, including execution and result transfer, not pure network RTT or server-only execution time. They exclude subsequent ORM construction and Python statement/classification work. Per-invocation query medians were **2.403–4.030 ms current**, **3.087–4.536 ms grown**. Weighted mean over observed statements was **3.514 ms current / 3.690 ms grown**. Largest observed statements were **153.2 ms / 530.5 ms** respectively.

Each no-op contributed thousands of query observations; their empirical query-order-statistic 95th percentiles ranged **2.731–4.382 ms / 3.548–4.946 ms**. These are descriptive query samples, not a run p95 or independent future-tail guarantee. Small phase subsets' tail fields in the raw diagnostic are not interpreted. All five grown attempts preserve substantial serial SQL amplification: four finished whole-history normalization, but none finished classification/publication in time.

## Cancellation, publication and status

Negative responses include an added synthetic transaction and a deliberately different cursor, so an accidental publication would be detectable. Full raw/normalized/other financial-table row hashes, account state, cursor/success fields and publication marker were compared. Operational attempt/run logs are expected to change and are checked separately.

| Negative scenario | Observed result |
| --- | --- |
| Deadline after first Item's uncommitted writes | Shared sync aborted at 20.093 s; handler 20.917 s. Full financial state/cursors/marker unchanged, no publication, lock reacquired successfully; durable run immediately **failed** |
| Explicit task cancellation after first Item's uncommitted writes | Handler 3.134 s. Same preservation and lock-release checks pass. API reports **cancelled**; durable run initially **running**, then **interrupted** after explicit next-owner reconciliation |
| Explicit cancellation during delayed synthetic SDK thread | Handler 1.887 s, including waiting for the 0.8 s thread to finish. No later publication/cursor change; locks released. Durable status likewise initially **running**, then **interrupted** after next-owner reconciliation |

All five grown timeout attempts also returned unchanged full financial fingerprints, no publication/cursor advance, released locks and durable **failed** status. Final independent, verified-TLS reads confirmed preservation after every failure **and after reconciliation**, zero `running` run/Item-run rows and zero advisory locks. Current schema contains five published successful runs, one unpublished failed run and two unpublished interrupted runs; grown schema contains five unpublished failed runs. [Final preservation evidence](evidence/m5-2026-10-01/real-cloud-latency/final-preservation.json).

**Immediate terminal cancellation status is not satisfied by the unmodified shared service.** Its `CancelledError` escapes ordinary `Exception` handlers; the next owner reconciles the abandoned running row. The test explicitly observed this gap rather than silently finalizing or weakening the service. Financial rollback/lock safety passes for the tested pre-commit cases; an unattended lifecycle/status policy still needs review. Provider hard termination, HTTP disconnect and uncertain/post-commit acknowledgement are not proved by these cooperative/application-deadline tests.

## Bytes, growth and headroom decision

Across the timing runs, actual HTTP request bodies total **150 bytes current / 155 bytes grown**; response bodies **20,030 / 32,667 bytes**. Across all thirteen calls: **432 request-body / 72,226 response-body bytes**. The controller records response-header and selected request-header lengths separately; these are not complete TLS wire bytes or provider-billed transfer. Synthetic SDK request/response shape bytes are recorded but **no SDK network traffic occurred**. Database protocol bytes/Supabase billed egress remain **UNKNOWN**; no paid observability feature was enabled.

The pre-fixture database sample was **10,892,979 bytes**; the early first-current-run sample was **36,705,971 bytes**; one intermediate in-flight sample was **45,684,403 bytes**; final sample **40,515,251 bytes**. These are physical SQL samples, not an exact peak or billing dashboard. Both scales coexist; counts remain 2,610/35,600 raw and normalized. Final table/index sizes are **4,808,704 / 24,248,320 bytes**. Rolled-back writes can grow physical storage and background vacuum can reclaim it while logical fingerprints remain unchanged. [Size samples](evidence/m5-2026-10-01/real-cloud-latency/database-growth.json).

| Existing target, D=300 s | Finding |
| --- | --- |
| Normal representative p95 ≤ **150 s** (50%) | Current observed samples **PASS** with max client 29.285 s, but formal run-p95 acceptance **UNKNOWN** at n=5. Grown no-op envelope **FAIL**: all five are incomplete at 210 s |
| Worst plausible catch-up/retry/partial-failure completion ≤ **210 s** (70%) | **UNKNOWN**: those workload scenarios were outside this pass. Grown normal no-op already fails to complete at that bound |
| Reserve ≥ **60 s** (20%, minimum 30 s) | **PASS for observed bounded abort/cleanup responses**: largest client wall 215.423 s leaves 84.577 s against 300 s, and 69.577 s against the controller's 285 s wait. This does not rescue an incomplete workload |

**Overall headroom for the requested grown row envelope: FAIL.** Empirically proven successful point: **2,610 synthetic retained rows** on this fixture/path. **35,600 is unsupported under the tested bound.** The maximum passing row count between those points is **UNKNOWN**; no interpolation is presented as a supported envelope, and no further scales were run.

New blockers are the grown no-op's serial whole-history processing and the cancellation terminal-status gap. Full worst-workload timing, reliable run-tail statistics, hard termination/uncertain commit, real bank latency and account-wide quota/billing headroom remain unknown. The prior cron, owner Auth/recovery and independent-backup requirements remain open; B2 is still unapproved. No source optimization or revised headroom threshold is proposed as accepted by this pass, and no SERVERLESS_GO/Production migration authorization is implied.

Local guard/packet/scheduler tests: **22 passed**; changed Python compiled and whitespace checks passed. Financial source remained unchanged, so completed local financial benchmarks/product UI builds were not repeated. No Production restart is required.
