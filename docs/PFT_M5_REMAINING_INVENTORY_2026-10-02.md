# M5 remaining work: authoritative inventory — 2026-10-02

**SERVERLESS_GO remains withheld.** This is a documentation-only consolidation of the M5 record as of `main` at `47183eb`. It adds no measurement. Sources read in full: [Phase 2 plan §2, §12–§16](PFT_PHASE_2_ARCHITECTURE_PLAN.md#12-m5--zero-cost-serverless-feasibility), [feasibility](PFT_M5_FEASIBILITY_2026-10-01.md), [cloud experiment / B2 gate](PFT_M5_CLOUD_EXPERIMENT_2026-10-01.md), [preparation](PFT_M5_CLOUD_PREPARATION_2026-10-01.md), [cloud run](PFT_M5_CLOUD_RUN_2026-10-01.md), [compatibility](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md), [real-cloud latency](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md), [sync round-trip fix](PFT_M5_SYNC_ROUND_TRIP_FIX_2026-10-01.md) and the [diff-writes Production packet](PFT_SYNC_DIFF_WRITES_PRODUCTION_ACTION_PACKET_2026-10-01.md).

Where a later document supersedes an earlier row of the feasibility matrix, the later state is shown.

## SERVERLESS_GO release criteria (plan §12, verbatim intent)

`SERVERLESS_GO` requires **affirmative evidence for every item**; a material unknown cannot count as a pass ([plan §12 "Tests, acceptance, rollback and decision"](PFT_PHASE_2_ARCHITECTURE_PLAN.md#tests-acceptance-rollback-and-decision)):

| # | Criterion | Current state |
| --- | --- | --- |
| G1 | Reliable free FastAPI on Vercel | Mostly measured: Python 3.12.14, native packages, imports, TLS, session pool, locks, protected routing all pass on Hobby. Cold/warm distributions only n≤5. |
| G2 | Adequate sync and catch-up headroom (normal p95 ≤ 0.50·D, worst ≤ 0.70·D, reserve ≥ max(30 s, 0.20·D)) | No-op at 35.6k rows now 5/5 at 5.27 s median after the diff-writes fix. **Catch-up, retry and partial-failure scenarios have not run in the cloud.** Application deadline (210 s candidate) not adopted. Run-level p95 unsupported at n=5. Thresholds unreviewed. |
| G3 | Equivalent one-shot due/retry/manual behaviour | Local draft passes. Duplicate delivery, lost response before/after commit and real cadence/jitter untested. |
| G4 | Correct ownership and atomic publication | Pre-commit cancellation/timeout preserve state in the cloud. **Cancellation terminal-status gap** (durable `running` until next owner) unresolved. Hard termination / uncertain commit untested. |
| G5 | Supabase Free capacity, connectivity, pause and recovery fit | Connectivity passes. Egress grows ~655 B per retained row per sync (measured, synthetic). Dashboard egress, pause/resume, quota-denial behaviour all UNKNOWN. |
| G6 | Viable free owner authentication | **Not started** in the cloud. Current routes are a BLOCKER for public exposure. SMTP recovery path unknown. |
| G7 | Proven independent encrypted backup design and restore | **Not started** beyond a local synthetic dump/encrypt/restore. B2 gate closed (exact $0 unproven). No backup destination selected. Remote backup profile and non-interactive key are BLOCKERs in the current adapter. |
| G8 | No paid prerequisite | Vercel billing/usage APIs returned no data (UNKNOWN, not $0 evidence). |

## Remaining items

Status keys: **BLOCKER** = known incompatibility of current code or config; **UNKNOWN** = evidence missing; **OPEN-DECISION** = owner choice needed.

| ID | Item | Status | Source | Covered tonight? |
| --- | --- | --- | --- | --- |
| R1 | Independent encrypted backup: destination, key custody, retention, unattended run, restore drill | BLOCKER/UNKNOWN | feasibility matrix; plan §12.6, §16.1–16.2; experiment B2 gate | Task 1 (design + local prototype) |
| R2 | Remote backup connection profile (TLS/identity) replacing `api/backup.py:connection()` local-only guard; PG17 client | BLOCKER | feasibility; compatibility (pg_dump 17.11 packaged, not wired) | Task 1 (design; prototype uses its own guarded profile, local guard untouched) |
| R3 | Backup-before-sync coupling in `tick`; cancelled backup thread can outlive caller | **Resolved by design 2026-10-02** (owner P1-2: backups move to GitHub Actions; cloud tick uses `backup_fn=None`). Still to be proven in M7. | feasibility "tick", matrix | Backup design §3 |
| R4 | Single free trigger: Supabase Cron + pg_net, 5-minute tick; pg_net timeout; duplicate/timeout delivery | UNKNOWN / BLOCKER (default 2 s timeout) | plan §12.4; feasibility | Task 2 (design + endpoint auth code) |
| R5 | Free-project pause/inactivity rules; whether scheduled traffic keeps the project active; no anti-pause traffic | UNKNOWN | plan §12.5 | Task 2 (docs research) |
| R6 | Owner Auth (Supabase Auth), signup disabled, BFF vs bearer, FastAPI JWT verification, DB roles | BLOCKER (current code) / UNKNOWN | plan §13.1–13.2; feasibility | Task 3 (design only) |
| R7 | Owner login recovery without paid SMTP (default SMTP 2 msgs/hour, team addresses only) | UNKNOWN | feasibility limits table | Task 3 (design) |
| R8 | Cloud catch-up / retry / partial-failure headroom (0.70·D target), more samples for p95 | UNKNOWN | latency; round-trip fix | No (needs cloud run approval) |
| R9 | Application deadline below D (210 s candidate) and threshold review | OPEN-DECISION | feasibility §latency item 5 | No (listed as pending) |
| R10 | Cancellation terminal-status gap (`CancelledError` leaves `running` row) | BLOCKER (unattended policy) | latency "Cancellation" | No — not in tonight's list; recorded as pending |
| R11 | Hard termination / HTTP disconnect / uncertain commit on Vercel | UNKNOWN | latency | No (cloud) |
| R12 | Supabase egress and DB growth vs quota; historical-validation cadence; incremental normalization "C" | UNKNOWN / OPEN-DECISION | round-trip fix "Open decisions" | Partly (Task 1 sizes backups) |
| R13 | `build_classifications` ~O(n²) CPU | UNKNOWN | round-trip fix | No |
| R14 | Aggregate connection budget across warm instances | UNKNOWN | feasibility; compatibility | No |
| R15 | Honest serverless status model (heartbeat replacement) | UNKNOWN | feasibility "Status"; plan §13 | Task 2 design touches it |
| R16 | PUBLIC TEMP privilege least-privilege gap: every role (pft_m5_reader, pft_m5_jobs, pft_backup) can create temporary tables through PUBLIC | **Known issue (owner, 2026-10-02): handle once during Production configuration** (cutover prerequisite C4), not per role now | cloud run; backup role check 2026-10-02 [M] | Auth design §7 |
| R17 | `api.db` module-level engine should become lazy | M6 note | experiment follow-up | No |
| R18 | `PLAID_PILOT_USER_ID` leaks into `test_category_overrides` | Test defect | round-trip fix "Open decisions" | Task 5 |
| R19 | $0 billing proof (Vercel usage, Supabase dashboard, backup store) | UNKNOWN | compatibility usage table | No (owner dashboards) |
| R20 | Cutover/rollback packet | M8 artefact, premature for M5 | plan §15 | Task 4 (draft only) |
| R21 | Teardown of disposable M5 resources after retention decision | OPEN-DECISION | cloud run; experiment step 7 | No |

## Differences from the overnight task list

1. **Items the docs require that tonight's list omits:** R8–R11, R13, R14, R17, R19, R21. Most need cloud execution or owner dashboards, which tonight's boundaries forbid. They are carried as pending in the handoff.
2. **Task 3 (Auth design) cannot close G6.** The plan requires measured login/refresh/logout and negative tests on the synthetic project. A design narrows the choice; it is not GO evidence.
3. **Task 4 (cutover plan) is M8 work.** The plan says M5 "cannot authorize a Production migration" and each M8 packet is prepared before its gate. A draft is fine as long as it is labelled non-executable; it does not move M5.
4. **Task 1's prototype is local only.** G7 also requires a real independent upload/readback/download from the chosen store and a restore of the managed (PG17) object set. Destination selection needs owner approval (the B2 gate is explicitly closed).
5. **Plan §16.1 proposes 7 daily points.** The current local runtime keeps 7 daily + 4 weekly + 3 monthly (`api/backup.py:RETENTION`). Task 1 must not cover less than that local behaviour (owner requirement), so the design keeps the local tiers.
