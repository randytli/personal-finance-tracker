# M5 sync round-trip amplification fix — 2026-10-01

**A no-op sync of 35,600 synthetic retained rows went from 71,341 SQL statements and 5/5 cloud timeouts at the 210-second deadline to 141 statements and 5/5 cloud successes (shared-sync median 5.27 s). The 2,610-row no-op went from a 24.75 s to a 1.29 s shared-sync median. SERVERLESS_GO remains withheld: this removes the round-trip blocker only; data transfer and CPU still grow with history, and the other open M5 items are unchanged.**

This follows the [bounded real-cloud latency pass](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md), which found that the unchanged 35.6k no-op could not complete. It records the read-only investigation, the two-commit fix on branch `m5-derivation-diff-writes`, local verification, and an owner-authorized cloud rerun on the existing disposable M5 resources. During that work, Production, Production data/credentials and Plaid were not accessed.

Later owner-approved follow-up: the fix was **deployed to the local Production runtime on 2026-10-02** in two phases, following the [Production action packet](PFT_SYNC_DIFF_WRITES_PRODUCTION_ACTION_PACKET_2026-10-01.md). On the same data with zero Plaid delta, a controlled sync went from 5,374 statements and 5.92 s on the old path to **144 statements and 2.57 s** with the fix. Classification time fell from 1,375 ms to 61 ms. No unchanged row was rewritten, and every business table, including full `transactions` fingerprints with timestamps, was identical before and after [M].

Legend: **[M]** measured; **[E]** estimate or inference, not measured.

## Background

M5 asks whether PFT can run on Vercel + Supabase within the free/Hobby envelope. The jobs function has a configured 300 s limit; the benchmark gives the shared sync a 210 s deadline and keeps the remainder as cleanup reserve.

The synthetic fixtures live in two private schemas of Supabase project `acyghoemtdrilsdszolq` (database `postgres`): `pft_m5_bench_2610` and `pft_m5_bench_35600`. Each has five active synthetic Items and 13 accounts, including disabled consumer accounts. Retained raw and normalized rows are spread evenly over the five enabled credit accounts (`account-{i}-0`), with synthetic merchants, categories, dates and amounts. 2,610 rows matches the current retained-history size; 35,600 models grown history. They are not a copy of financial data and not a worst-case classification corpus.

The earlier pass measured 5,361 SQL statements for every 2,610-row no-op and 34k–47k statements before the 35,600-row attempts were aborted. With weighted mean statement latency of about 3.5–3.7 ms [M, earlier pass], serial round trips alone exceed the deadline at 35,600 rows.

## Root cause

A no-op sync issues exactly **2N + 141** statements, where N is the number of retained, enabled, non-removed rows [M, local, at 2,610 / 7,830 / 35,600 rows]. The two per-row loops were both **writes**:

| Location (before fix) | Statement | Per no-op sync |
| --- | --- | --- |
| `api/services/derivation.py` `normalize_item_transactions`, per-row loop | `INSERT INTO transactions … ON CONFLICT (transaction_id) DO UPDATE SET …, updated_at = now()` | N |
| `api/services/derivation.py` `classify_active_transactions`, per-row loop | `UPDATE transactions SET transaction_type, is_spending, is_internal_transfer, updated_at = now() WHERE transaction_id = …` | N |
| Locks, revalidation, savepoints, run records, per-Item counts | fixed | 141 (grows with Item count, not history) |

Reading history was not the amplifier: normalization reads each Item's raw rows in one query and classification reads all active rows in one query. The models define no ORM relationships, so there are no lazy loads. **This corrects the initial hypothesis of an N+1 read pattern.**

With zero new transactions, both derived values are deterministic functions of unchanged inputs, so every one of those 2N writes rewrote an identical value (and refreshed `updated_at`). Reading the full history for classification is still logically required: refund matching has no lookback bound, Zelle confirmation codes are grouped across all time, transfer pairing requires uniqueness within ±3 days, and active manual overrides affect pairing. A new or changed row can therefore reclassify older rows.

`persist_consumer_transactions` also issues about two statements per added or modified row, but that grows with the delta, not with history (2,610 rows seeded at once: 5,260 persist statements [M, local]).

## Fix

Both changes are in `api/services/derivation.py`, so jobs, one-shot sync, the legacy FastAPI split routes and activation share them without a fork. Branch `m5-derivation-diff-writes` on `a047b0f4b32c2db23203fbab9b25cd5fe7678400`:

- **A — `a5f2dfd8868e268e5a64f5b67efb3042c27db93f`: write only changed classifications.** Every active row is still recomputed over the full history. Each result is compared with the stored row already loaded by `_classification_inputs`, and only differences are written through one `UPDATE … FROM unnest(…)` statement.
- **B — `b646fb9e9d52e795f177cf9c4d2f202f5d71f99a`: upsert only missing or changed normalized rows.** The per-Item raw query now outer joins the stored normalized row. Derived values are compared, with numeric scale compared exactly (`-2000` vs `-2000.0`) because the old rewrite preserved the payload's scale. Only differences are written through one `INSERT … SELECT FROM unnest(…) ON CONFLICT DO UPDATE`.

Batch writes are single statements rather than `executemany`, because `executemany` round trips depend on driver batching; the code comments record this.

Preserved behavior:

- Every eligible raw row is still validated by `validate_normalization_input`. An invalid historical row still blocks its Item on every sync, including a no-op.
- Missing normalized rows are still restored on any sync.
- `normalized_count` still counts every eligible row, not rows written.
- New normalized rows still start unclassified; classification stays untouched on normalization updates.
- All writes stay inside the existing publication transaction and per-Item savepoints. Cursor, financial rows and publication marker still commit or roll back together.
- Loaded ORM rows are kept consistent with the database after the batch writes.

Behavior change: `transactions.updated_at` now changes only when a row's derived data changes. Previously every sync refreshed it on every row twice. No code reads `transactions.updated_at`. Fingerprint comparisons across this change must exclude `created_at`/`updated_at`.

## Verification

All local database tests used disposable PostgreSQL 16 clusters on loopback with synthetic data only.

New tests in `tests/test_derivation_writes.py`:

- **Old/new equivalence.** The pre-fix loops are kept verbatim in the test as a reference. Two schemas replay the same synthetic sync sequence:
  - seed with a historical refund match, a Zelle pair, an unmatched transfer, income and a disabled-account row;
  - no-op;
  - added counterpart that turns an older row into a transfer pair;
  - modified expense that breaks the refund match, plus a scale-only amount change;
  - manual override followed by a no-op that blocks the Zelle pair;
  - removal that unpairs the transfer;
  - final no-op.

  After each step the test compares `external_classifications()` digests, a `transactions` hash without `created_at`/`updated_at`, and Item cursors. It also asserts expected classifications so equality cannot be vacuous.
- **Statement-count regression.** A no-op sync issues the same number of statements at 50 and 500 retained rows. It failed at 122 vs 572 after A and before B.
- **Write behavior and preserved behavior.** A no-op classification issues no `UPDATE transactions`. Changed classifications are written in one statement. A no-op normalization issues no `INSERT INTO transactions` and reports every eligible row. A deleted normalized row is restored. An invalid historical row still blocks its Item.

Mutation checks, applied at runtime only:

- Comparing amounts without scale was caught by the equivalence test.
- Dropping missing-row restoration was initially **missed**, because both snapshots in that test were empty under the mutant. An absolute assertion was added, and the mutant is now caught.

Test totals with all seven PostgreSQL opt-ins and zero skips [M]: baseline 289 → 292 after A → 296 after B → 304 with the benchmark-adapter tests. Python compilation and `git diff --check` passed.

## Results

### Local, loopback PostgreSQL 16, synthetic data

| Retained rows | No-op before | No-op after | +1 row per Item before | +1 row per Item after |
| --- | --- | --- | --- | --- |
| 2,610 | 5,361 SQL / 3.28 s [M] | **141 SQL / 0.18 s** [M] | 5,386 / 3.25 s [M] | 162 / 0.18 s [M] |
| 7,830 | 15,801 / 9.40 s [M] | **141 / 0.45 s** [M] | 15,826 / 9.32 s [M] | 162 / 0.42 s [M] |
| 35,600 | 71,341 / 43.59 s [M] | **141 / 1.86 s** [M] | 71,366 / 44.58 s [M] | 162 / 1.82 s [M] |

Single runs per cell. Loopback latency hides most of the round-trip cost that the cloud exposes.

`build_classifications` pure CPU on 35,600 synthetic rows [M]: **2.87 s median** over 3 runs (2.84–2.91 s). The mix was 26,489 expenses, 978 refunds (all matched), 662 unmatched credits, 2,048 transfer pairs, 364 Zelle pairs, 999 income and 1,648 loan payments. The cost comes mainly from scanning credits against expenses and from transfer pair comparison, which is close to quadratic [E].

### Cloud, Vercel `iad1` jobs preview → Supabase `us-east-1`

Seconds, shown as min / median / max [M]. "Before" is the [earlier pass](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md).

| Scale / action | n | Client wall | Handler wall | Shared-sync wall | SQL |
| --- | --- | --- | --- | --- | --- |
| 2,610 no-op, before | 5 | 19.01 / 25.34 / 29.28 | 18.57 / 25.00 / 28.73 | 18.34 / 24.75 / 27.62 | 5,361 |
| 2,610 no-op, after | 4 | 1.51 / **1.85** / 2.93 | 1.27 / 1.54 / 2.57 | 1.05 / **1.29** / 1.40 | **141** |
| 2,610 append_one, after | 3 | 2.20 / 2.22 / 2.47 | not recorded | 1.12 / 1.16 / 1.43 | 162 |
| 35,600 no-op, before | 5 | 0/5 complete; 213.76 / 213.94 / 215.42 to abort | 212.06 / 212.22 / 213.61 | aborted at 210 | 34,449–47,195 before abort |
| 35,600 no-op, after | 5 | 6.90 / **7.37** / 10.64 | 6.82 / 7.12 / 10.31 | 5.03 / **5.27** / 7.30 | **141** (first run 146) |
| 35,600 append_one, after | 5 | 9.97 / 10.56 / 10.72 | 9.89 / 10.22 / 10.48 | 5.12 / 5.41 / 5.58 | 162 |

- Five or fewer runs give observed ranges, not reliable p95 values.
- The 2,610 maximum (2.93 s) is the first request in a fresh process.
- append_one handler time includes about 5 s of post-sync snapshot and verification at 35,600 rows; that work is outside the shared sync.
- Warm 35,600 no-op stages [M]: normalization about 2.5 s, classification about 1.8–1.9 s; process CPU 4.4–5.3 s; RSS high-water about 200 MiB.
- "+1 row per Item" (`append_one`) had no cloud baseline before this pass.

**First 35.6k no-op: 146 statements.** That run rewrote all 35,600 pre-existing normalized rows, using one upsert per Item [M]. The nine later runs rewrote none [M]. The 35.6k schema had never completed a sync before (all earlier attempts rolled back), whereas the 2,610 schema had already been converged by the old code's successful runs. The likely cause is that the bulk-created fixture rows differed from normalization output, for example in numeric scale [E]. The old code would also have rewritten every row.

### Bytes received from Supabase

**Method:** driver-level count of TLS ciphertext bytes received on the benchmark engine's own connections. Each connection's asyncio `SSLProtocol.buffer_updated` is wrapped on that instance only. The count excludes setup, verification, the observer connection and TLS handshakes. `pg_stat_statements` was not used because it has no network-byte columns. The counter tracked 3 connections per run, with no untracked connections, on the `asyncio` event loop in Vercel.

| Scale / action | Bytes per sync [M] | Per retained row |
| --- | --- | --- |
| 2,610 no-op | 1,717,991–1,718,013 (≈ 1.72 MB) | ≈ 658 B |
| 2,610 append_one | 1,725,141–1,733,737 | — |
| 35,600 no-op | 23,320,227–23,321,556 (≈ 23.3 MB) | ≈ 655 B |
| 35,600 append_one | 23,327,175–23,343,715 | — |
| 17 counted calls in total (timeout run not counted) | **245,341,538 B** | — |

Bytes still grow linearly with retained history. At 35,600 rows, one sync per day is about 0.7 GB per month [E]. The synthetic raw payload is about 212 B per row [M, local text length]; real Plaid transaction payloads are larger, likely 1–2 KB [E, not measured]. Supabase usage-dashboard egress was not read by tooling and is **UNKNOWN** pending the owner's before/after screenshots. It should exceed the counted total slightly, because it also includes verification reads, observer polling, the timeout run and read-only checks.

### Negative test and positive verification

**Timeout injection** (2,610 schema at 2,625 rows; 20 s deadline; 30 s pause after the first Item's uncommitted publication) [M]:
- aborted at 20.12 s, unpublished; run recorded as `failed / publication_failed`;
- full financial-table row hashes (including timestamps), cursors and publication marker all unchanged (`state_unchanged: true`);
- locks released.

**append_one positive verification**, all 8 successful runs [M]:
- raw and normalized rows each grew by exactly 5;
- every Item cursor advanced; the publication marker moved to the run;
- pre-existing raw rows unchanged, hashed without timestamps;
- pre-existing normalized rows unchanged, hashed without timestamps and classification columns;
- classification digest unchanged, with 0 rows reclassified.

A changed classification digest would have been listed row by row rather than failed, because a new row can legitimately reclassify an older one; none occurred.

**Final read-only state** [M]:
- rows 2,625 / 35,625 raw and normalized;
- zero running runs and zero advisory locks;
- database size 45,659,827 B.

## Rejected or deferred options

- **Skip classification when nothing changed — rejected.** Review override changes do not reclassify immediately; their effect on Zelle and transfer pairing is materialized by the next sync's full classification. Skipping would delay that indefinitely.
- **Window-limited classification — rejected for now.** Unbounded refund lookback, all-time Zelle grouping and transfer uniqueness chains mean a correct window is a dependency closure. A simple window could produce different results.
- **C, incremental normalization (changed IDs plus missing rows) — deferred.** It would remove most of the per-sync raw payload transfer [E]. It also drops every-sync validation of historical rows and automatic repair after normalization-logic changes, which would then need explicit migrations.
- **D, batched persistence — deferred.** No effect on no-ops; it matters for catch-up and initial syncs at about two statements per added row.
- **E, set-based SQL normalization — rejected for now.** It would duplicate normalization semantics (sign, source branches, payload parsing, validation) in SQL, with a divergence risk.

## Open decisions

- **Historical validation cadence.** Should every-sync validation of all historical rows continue, or move to a periodic check? This trades the egress and transfer cost above against "an invalid historical row blocks its Item immediately".
- **When to do C.** Real Plaid payload size per row is unmeasured, and the actual Production sync frequency determines monthly egress.
- **`build_classifications` CPU** is close to O(n²) [E]: 2.87 s at 35,600 rows [M], with a likely 4× increase if history doubles [E].
- **Review override latency.** Override changes do not reclassify until the next sync.
- **Test isolation.** `test_category_overrides` fails when the shell inherits `PLAID_PILOT_USER_ID`, so tests must run with a clean environment.
- **Rollout — done 2026-10-02.** Local `main` was fast-forwarded to include the fix and was not pushed. The action packet records the full procedure: backup with a restorability check, pre/post fingerprints with timestamps excluded, single-file image overlays, and a controlled sync.
  - The predicted one-time convergence write did **not** occur in Production [M]. The old code had kept derived rows converged by rewriting them on every sync.
  - Open items: the running image pin files live only under `/tmp`, so a durable copy is needed. The `:latest` image tags are stale. Pushing `main` is a separate decision.
- Earlier M5 items remain open: the cancellation terminal-status gap, cron, owner Auth, backup packaging and B2.

## Safety boundaries and operation record

**Local.**
- Disposable PostgreSQL 16 clusters ran in the session scratchpad on `127.0.0.1:55439`, TCP only, plus one TLS-enabled cluster on `127.0.0.1:55441` used to check the byte counter. All were deleted after use.
- Existing Docker databases, including the Production pilot container, were never contacted. `.env` files were not read.
- Tests ran under `env -i` with only synthetic variables.

**Credential isolation.**
- The private experiment directory stayed read-denied by the owner's permission policy. The owner later allowed reading three controller files only: `deploy_benchmark.py`, `run_benchmark.py` and `compatibility.py`.
- Credential files were never read or printed; credentials existed only in controller process memory.
- An initial `--help` probe ran in a network-less namespace (`unshare -rn`), and the private files were verified unchanged afterwards.
- The deployment uploaded only the 29 manifest files plus `pg-bin/`. The only JSON among them is the generated `vercel.json` function configuration. No private JSON was uploaded or committed.

**Supabase.** MCP OAuth was granted with broader scopes than used. Usage was `get_project` plus five read-only `SELECT`s.

**Vercel.**
- One jobs preview `dpl_8e1kFXqwPTEmbkSXruTGGDBVP6Ax` was deployed (READY, `target: null`, `iad1`) in project `prj_T8mZTCne3EfvSAS1y7DvmNcJ17Kb`.
- `M5_BENCHMARK_ENABLED` was re-upserted to the preview target with its previous value.
- Reader and web-probe projects were not redeployed.

**Controllers** (private, not committed).
- The deploy guard now pins domain source to `b646fb9` (packet, commit and working tree must match byte for byte) and the uncommitted adapter to SHA-256 `3aaf2664fab38f85b6fef7f3d0e9dee925074f1bc5b6bb1262ac1ce9a1397ed7`.
- Refreshing the packet is a separate explicit step; it refreshed only `api/services/derivation.py`.
- The runner gained `append_one` and writes to a new samples file, leaving the earlier evidence untouched.

**Invocation budget.** 2,610 schema: 16/16 (exhausted). 35,600 schema: 15/16. Synthetic fixtures grew by design: 2,610 → 2,625 and 35,600 → 35,625 published rows.

**Deployment pointer.** The controllers' `jobs-preview.json` points at `dpl_8e1kFXqwPTEmbkSXruTGGDBVP6Ax`. The previous pointer, to `dpl_Ea8nMxHw3xcE5ZZ2fq9WdJDpHu9Q`, is backed up as `jobs-preview.before-derivation.json`. The new pointer was kept because it matches the pinned controller baseline and the old code cannot complete the 35.6k workload. No traffic or cron uses either preview. To roll back:

```
cp -p "$M5_PRIVATE_DIR/jobs-preview.before-derivation.json" "$M5_PRIVATE_DIR/jobs-preview.json"
```

## How to reproduce

**Local.**
1. Start a disposable PostgreSQL 16 cluster on `127.0.0.1:55439` with role `pft_m5` and database `pft_m5_synthetic`, as in earlier M0/M6 work. Never point these tests at Production.
2. Run `python -m unittest tests.test_derivation_writes` (plus the full suite) under a clean environment with `DATABASE_URL` set to that database, `PLAID_ENV=sandbox`, and the seven `PFT_*_SYNTHETIC_TEST=1` opt-ins.
3. To count statements by template:
   - attach a SQLAlchemy `before_cursor_execute` listener to a per-schema engine;
   - wrap the `sync_all` module's persistence, normalization and classification functions with phase labels;
   - seed 5 Items × N/5 rows on `account-{i}-0` through `sync_all` with a synthetic client, then run a no-op sync.

   The counting script was session-temporary and is not in the repository. `scripts/pft_m5_benchmark.py` covers local wall-time scenarios.

**Cloud** (controllers in the private experiment directory, not in the repository).
1. Read-only check: project ref, `current_database()`, both schemas' raw and normalized row counts, `bench_manifest.invocations`, running runs.
2. `deploy_benchmark.py --refresh-domain-from-commit`, then confirm that only the expected domain files were refreshed.
3. `deploy_benchmark.py`, then wait for the new jobs preview to be READY.
4. `run_benchmark.py <scale> <action> <count>`. Run all `noop` samples before `append_one`; the adapter rejects a no-op once rows have been appended. Run `timeout_publication` only on the 2,610 schema.
5. Run a read-only final check (row counts, budget, running runs, advisory locks), then decide whether to restore the previous deployment pointer.
