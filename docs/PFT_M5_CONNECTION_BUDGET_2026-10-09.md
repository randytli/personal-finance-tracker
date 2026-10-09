# M5 connection budget — 2026-10-09

R14 document-only analysis, based on branch base `a18ca05` and C1's lazy initialization change. No cloud access or configuration changes. **The four-delivery jobs experiment fits its role budget; an unbounded number of default-pool API processes does not.** Lazy initialization fixes import-time configuration, not connection capacity.

Notation: **[C]** repository code; **[M]** previously recorded measurements; **[E]** calculation/recommendation; **[D]** official documentation accessed **2026-10-09**. **未核实** means not verified for the actual project in this task.

## Limits and what they count

| Boundary | Documented value / meaning | Project status |
| --- | --- | --- |
| Supabase Free / Nano PostgreSQL | 60 maximum connections in the compute table; the documentation describes these as recommended, customizable values | Current `max_connections`, reserved slots and usable ordinary-role capacity: **未核实** |
| Shared pooler client limit | 200 clients for Nano | Actual project setting: **未核实**; this is not 200 PostgreSQL backends |
| Supavisor pool size | Backend allowance per distinct user + database + mode, not one aggregate project allowance | Actual size for each combination: **未核实** |
| Application role ceilings | Reader 8, jobs 12 in the synthetic role template; jobs 12 also recorded in cron acceptance | Current role settings: **未核实** |

The Free values come from [Supabase compute limits](https://supabase.com/docs/guides/platform/compute-and-disk#limits-and-constraints) [D]. Free compute resources can change. [Pooler limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits) distinguish client and backend limits; PostgreSQL capacity is shared by direct connections, pooler backends and platform services. [Supavisor FAQ](https://supabase.com/docs/guides/troubleshooting/supavisor-faq-YyP5tI) defines the user/database/mode multiplier [D]. A pool size of 15 for several combinations must not be budgeted as 15 total.

For the current session-pooler jobs path, budget one backend for every concurrently held client connection. Transaction pooling can reuse backends between transactions but does not preserve session advisory locks; it is not a drop-in capacity fix for jobs. Official guidance recommends direct connections for native backup tools, with session pooling available for IPv4-only clients. [Connection modes and limitations](https://supabase.com/docs/guides/database/connecting-to-postgres) [D].

## Code inventory

| Path / role | Pool and lifecycle [C] | Capacity implication [E] |
| --- | --- | --- |
| `api/db.py`, application API / local jobs | `create_async_engine(..., echo=False, pool_pre_ping=True)`; no explicit pool limits; C1 defers construction | SQLAlchemy async default: pool 5, overflow 10, **15 per process**, up to 5 retained after demand; zero connections before first checkout |
| `experiments/m5_cloud/cron_jobs_app.py`, jobs | One `NullPool` engine per delivery, disposed in `finally`; `tick(..., backup_fn=None)` | No application idle pool; no intrinsic concurrency cap in NullPool; running tick needs up to 3 simultaneous checkouts |
| `experiments/m5_cloud/runtime_probe.py`, reader/jobs probes | Request-owned NullPool or pool 4 / overflow 0; disposed on completion | Small-pool ceiling 4 **per request engine**, not per warm instance; multiply by concurrent invocations |
| `experiments/m5_cloud/sync_benchmark_support.py` | Benchmark pool 4 / overflow 0; observer pool 1 / overflow 0 | Up to 4 benchmark + 1 observer sockets per harness; observer belongs in its actual role's budget |
| `experiments/m5_cloud/web_probe_handler.mjs` | HTTP forwarding; rejects `DATABASE_URL` | Zero direct DB connections from web instances; count their downstream reader instances instead |
| `deploy/backup_runner/pft_backup_runner.py` + `snapshot_dump.sql` | Exported-snapshot `psql` stays open while serial `pg_dump --snapshot` runs | **2 simultaneous source backends**; schema/version checks run serially; archive inspection/encryption needs none |
| `api/backup.py` legacy backup | Serial `pg_dump`; archive-only `pg_restore` inspection | 1 extra source connection; if invoked inside local jobs, also count the retained jobs-owner connection and any idle application pool sockets |

SQLAlchemy's [pool documentation](https://docs.sqlalchemy.org/en/20/core/pooling.html) confirms deferred physical connections, the async queue pool, default pool 5 + overflow 10, and NullPool behavior [D]. No pool tuning is part of C1. The cloud cron path does not run a backup; the independent backup runner can overlap it. Restore testing is separate capacity, excluded from routine backup's 2; parallel backup/restore would require another budget.

## Per-role demand

Let **D ≥ 1** be concurrent authenticated deliveries for the **same jobs owner/user**, **N** the number of database-owning warm API processes (multiply by workers per instance), **B** simultaneous independent backup runners, and **q** an explicit per-process API pool ceiling. Figures below describe successful live client demand before admission limits; pooler-retained idle backends are additional unless reused.

| Scenario | Jobs role | Reader/API role | Backup role | Explanation |
| --- | ---: | ---: | ---: | --- |
| One jobs tick | ≤3 | 0 | 0 | Jobs-owner lock + sync lock + working transaction; nonce/gate/finalization connections are sequential |
| D duplicate/concurrent deliveries | ≤`3 + (D−1) = D+2` | 0 | 0 | One winner, each loser needs ≤1 to reach `busy`; all-idle timing may be lower |
| Four deliveries (S9) | **5 sampled [M]; ≤6 estimated [E]** | 0 from this workload | 0 | 1-second sampling can miss ~0.2-second losers |
| N generic API processes, current defaults | 0 | ≤`15N`; retained idle ≤`5N` | 0 | Cold/import-only process opens 0; these are ceilings after demand, not eager allocation |
| N HTTP-only web instances | 0 | 0 locally | 0 | Downstream DB-owning API processes must still be counted |
| N API processes with proposed pool q / overflow 0 | 0 | ≤`qN` | 0 | Requires a separate implementation and concurrency acceptance |
| B independent snapshot backup runners | 0 | 0 | `2B` | Snapshot exporter + serial dump |
| Combined load | ≤`D+2` | ≤`15N` today, or `qN` proposed | `2B` | Add platform/admin/observer reserve and retained pooler backends |

The duplicate formula assumes the current single-user lock scope and code path. Distinct users can each win their own lock: budget up to 3 per simultaneous winning tick. A role limit is a rejection boundary, not proof that all client demand will succeed. For the recorded jobs ceiling 12, one tick leaves nominal role headroom 9; D=4 leaves 6 using the conservative demand 6, or 7 against sampled 5. These exclude other jobs-role work and retained backends. Demand alone reaches 12 at D=10; that is not a recommended delivery allowance. The reader ceiling 8 can reject requests even from **one** process allowed to demand 15.

## Measured evidence and uncertainty

[Cron acceptance, S9](PFT_M5_CRON_ACCEPTANCE_2026-10-02.md): four deliveries landed on four different instances; one succeeded, three returned `busy` in 205–243 ms. Sampled jobs backends peaked at **5** and all-role client backends at **11** [M]. Relative to a nominal 60, 11 leaves 49 arithmetically, **not 49 proven deployable slots**: this is a short sample including observer/cron/net paths, not a platform-reserve or full-load measurement. Do not add the 5 jobs backends to 11 again.

S6 had ≤3 jobs backends; S7 saw three during termination and one idle pooled backend persisting afterward [M]. The [compatibility report](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md) also records one idle reader and two idle jobs backends after request cleanup. Although the [Supavisor FAQ](https://supabase.com/docs/guides/troubleshooting/supavisor-faq-YyP5tI) describes immediate session-backend closure [D], this experiment observed retention. Current cleanup behavior and retained maxima are **未核实**. Budget retained backends explicitly; do not equate engine disposal or NullPool with zero server-side connections.

## Headroom model and recommendation

Let **R** include Supabase services, reserved/admin capacity, cron/net and observation; **I** be additional retained pooler backends not reused by the modeled live load. For one database and no dedicated pooler:

`backend headroom = 60 − R − I − (D+2) − API_demand − 2B` [E].

If all modeled application clients use Supavisor, client headroom is `200 − (D+2) − API_demand − 2B − other_pooler_clients`; direct backup clients are omitted there but remain in backend demand. Client headroom and backend headroom must both be positive, and each role/pool combination must independently fit.

Illustration only: D=4, B=1, **R=12 assumed**, I=0 (no extra retained backends), current API pool 15 [E; actual R/I **未核实**]:

| N API processes | API demand | Total including reserve | Nominal backend headroom | Modeled pooler client headroom, all apps pooled |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 15 | 35 | 25 | 177 |
| 2 | 30 | 50 | 10 | 162 |
| 3 | 45 | 65 | **−5** | 147 |

The reader-role limit 8 would bite before these aggregate ceilings if that role is used. The table exposes potential demand, not achievable admitted concurrency. Subtract I from every backend headroom value. R=12 is a planning allowance, not a measured platform requirement. [Supabase connection management](https://supabase.com/docs/guides/database/connection-management) advises retaining service headroom and gives context-dependent pool allocations around 40% or 80%; those are guidelines, not a guarantee [D].

Recommendations [E], **not implemented**:

1. Start the reader/API at **pool_size=1, max_overflow=0**, with a bounded checkout wait. Increase to 2 only after measuring request queuing. At N=4, q=1, D=4 and B=1, the illustrative total is 24 and backend headroom is `36−I`; reader demand 4 leaves nominal role headroom 4. With q=2 the reader role is already full at N=4. Enforce/verify aggregate instance and worker concurrency; per-process pooling cannot cap unbounded scale-out.
2. Retain session mode and invocation-owned NullPool for the current cloud jobs lock design. Budget a four-delivery wave at **6**, not sampled 5. Bound simultaneous delivery pressure separately; NullPool does not do this. Do not apply a one-connection pool to jobs: the owner and sync locks need connections while work proceeds.
3. Reserve **2 source connections** for one independent backup and serialize backup runners. Prefer the documented direct backup path when reachable; session-pooler backup compatibility remains **未核实** here.
4. A conservative allocation envelope using existing role ceilings is jobs **12** + reader **8** + backup **2** + assumed platform/admin reserve **12** = **34**, leaving **26** nominal backend slots. This includes idle retention within those application role envelopes, but depends on all workloads using those limited roles, sufficient per-combination pool sizes, no additional roles/modes, and a verified reserve. It is not an operational acceptance result.
5. Before any later cloud acceptance, read actual connection/pool/role limits and reserved capacity, measure all roles and both client/backend counts under overlapping backup + API + duplicates, and sample fast enough to catch short losers. Confirm idle-backend decay and distinct-user concurrency. All live settings, scale controls, actual backup role ceiling and this combined load test remain **未核实**. No recommendation requires a pool-size or plan upgrade on the evidence currently available.
