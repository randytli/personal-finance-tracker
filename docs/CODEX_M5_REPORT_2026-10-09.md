# Codex M5 report — 2026-10-09

**C1 / R17 and C2 / R14 complete.** Finished at approximately **00:45 EDT**, before the 02:45 EDT stop. All changes are uncommitted in `/home/randyli/code/pft-codex-m5`, branch `codex/m5-low-priority-20261009`, based on `origin/m5-remaining-20261002` at `a18ca05`.

## Files changed

| File | Change |
| --- | --- |
| `api/db.py` | Stable lazy wrappers construct the engine/sessionmaker on first use, with thread-safe initialization and a clear `DATABASE_URL is required before using the database` error. Existing engine attributes, `SessionLocal()` / `.begin()`, public helpers and engine patching remain usable. Pool settings and financial behavior are unchanged. |
| `tests/test_db_lazy.py` | Seven fresh-process regression tests cover import without configuration, missing/blank URL on first use, retry after late configuration, cached bindings, keyword session arguments and transactions, concurrent initialization, and `patch.object(database, "engine", ...)`. |
| `docs/PFT_M5_CONNECTION_BUDGET_2026-10-09.md` | Document-only source inventory, jobs/duplicates/API/backup demand, role and aggregate headroom, S9 measurement limitations, official documentation links/access date, and recommendations. Unverified project settings marked **未核实**. |
| `docs/CODEX_M5_REPORT_2026-10-09.md` | This report. |

## Verification

| Run | Executed | Failed | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Focused `python -m unittest -v test_db_lazy` | 7 | 0 | 0 | 0 |
| Full Python suite, explicit module loader (36 modules; includes the seven above) | **390** | **0** | **0** | **0** |

Full suite duration: **57.814 s**. `git diff --check`: **passed**. Full suite required-test and required-class inventory checks passed; all 390 planned tests started. No additional test failures were suppressed.

Tests ran under `env -i` with `DATABASE_URL=postgresql+asyncpg://pft_ci:synthetic@127.0.0.1:55440/pft_ci_synthetic`, `PLAID_ENV=sandbox`, and all nine synthetic opt-ins from `scripts/ci_backend_tests.py`: category, consumer, label, statement, sync, M3, M4, M5 backup and M5 trigger. Other values were explicit synthetic identity/client placeholders, PG16 tool paths, and the age executable. No environment files were sourced or changed. The main checkout's existing Python interpreter/dependencies were read only; missing PyJWT 2.10.1 was installed into `/tmp`, and age v1.3.2 was downloaded and verified against the CI-pinned SHA-256.

**55440 compatibility adjustment:** existing tests assert 55439 and the stock CI runner rewrites the URL to 55439. A temporary runner loaded every `tests/test_*.py` by explicit module name with `loadTestsFromNames`, not package discovery. It changed only integer port constants 55439 → 55440 in memory for these nine modules: `test_category_overrides`, `test_consumer_scope`, `test_derivation_writes`, `test_dining_migration`, `test_m3_recovery`, `test_m4_jobs`, `test_m5_sync_recovery`, `test_statement_persistence`, `test_sync_all`. Existing configurable label/cron test ports were set to 55440. Repository test guards and the CI runner were not edited. All auth test files were loaded unchanged.

The outer test socket guard allowed only the 55440 disposable database and registered live loopback HTTP fixtures; an unmocked Plaid SDK request would fail. CI isolation tests retained their original inner guard. PostgreSQL client subprocesses inherited only explicit synthetic connection settings. **No connection to 55439 was used.**

Local reproducibility artifacts remain outside Git:

- `/tmp/pft-codex-m5-verification/run-tests.sh` — exact `env -i` invocation.
- `/tmp/pft-codex-m5-verification/run_suite.py` — explicit module loader and port/network guards.
- `/tmp/pft-codex-m5-verification/full-suite.log` and `result.json` — test evidence.

The PostgreSQL **16** cluster was initialized with UTF-8 / locale C, listened only on `127.0.0.1:55440` (plus a private local Unix socket), and was **stopped and its data directory deleted** after verification. Re-running the harness requires a newly initialized disposable PG16 cluster/database on 55440.

## Review notes / open questions

- C1 has no outstanding blocker. The public engine and session factory are delegating wrappers, not concrete SQLAlchemy instances for `isinstance` checks; repository callers were inspected and the full suite passes. The sessionmaker binds once, as before; tests that replace an already-initialized engine and need sessions should patch both public objects, as existing fixtures do. Configuration is fixed after successful initialization; restart the affected service when adopting the change or changing its URL.
- C2 is a planning result, not live capacity acceptance. Actual project `max_connections`, reserved/platform usage, Supavisor pool sizes/client settings, role ceilings, retained-backend behavior and API instance/worker concurrency remain **未核实**. The document keeps measured S9 jobs peak **5** separate from estimated instantaneous demand **6**. Current default API demand is up to **15 per process**; smaller pools and aggregate concurrency controls are recommendations only.
- No Production access/writes, live Plaid calls, Supabase/Vercel project access, Docker mutations, `.env` changes, commits or pushes occurred. Only public official documentation was browsed for C2. No protected files, other worktrees or main-checkout working files were modified; requested worktree creation necessarily updated shared Git metadata.
- Next safe step: owner reviews the four-file diff and integrates it on their schedule. Live connection-budget validation requires separate authorization.
