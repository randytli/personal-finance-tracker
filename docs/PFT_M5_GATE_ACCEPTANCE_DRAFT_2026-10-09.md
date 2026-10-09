# M5 SERVERLESS_GO gate acceptance — consolidated draft, 2026-10-09

**SERVERLESS_GO remains withheld.** This draft adds no cloud measurement. It consolidates the record on branch `m5-remaining-20261002` @ `a18ca05`, plus tonight's local R13 result.

Sources:
- [inventory](PFT_M5_REMAINING_INVENTORY_2026-10-02.md)
- [cron acceptance](PFT_M5_CRON_ACCEPTANCE_2026-10-02.md)
- [real-cloud latency](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md)
- [compatibility](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md)
- [backup design](PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md)
- [owner-auth acceptance](PFT_M5_OWNER_AUTH_ACCEPTANCE_2026-10-08.md)
- [R13](PFT_M5_R13_CLASSIFICATION_CPU_2026-10-09.md)

Markers: [M] measured, [D] documented by the provider, [E] estimate.

## Verdict per gate

| Gate | Verdict | Affirmative evidence | Blocking gaps | Next step (who) |
| --- | --- | --- | --- | --- |
| G1 Free FastAPI on Vercel | **Likely pass, thin sample** | Python 3.12, native packages, TLS, pool, locks and protected routing on Hobby [M] | Cold/warm distributions n ≤ 5 | More samples on the next approved cloud run (approval) |
| G2 Sync / catch-up headroom | **Partially evidenced** | No-op at 35.6k rows: 5/5, 5.27 s median [M]. S3 catch-up of 10k rows in 65.7 s [M]. S6 deadline 210 s, unpublished, reserve **89.4 s** of D = 300 s [M]. Classification CPU fix proven locally (R13) | Run-level p95 not available (n = 1 per scenario). Thresholds not reviewed. R9 deadline not formally adopted | Owner: adopt 210 s (R9). Approved cloud run for repeat samples |
| G3 One-shot due / retry / manual | **Mostly evidenced** | S4 retry, S5 partial, S5b retry after backoff, S8 lost response: all as designed [M]. Duplicate delivery: 1 of 4 ran, 3 `busy` (S9) [M] | Real cadence/jitter only n = 2. S9 wave 2 (nothing due) not run | Approved short cron run (approval) |
| G4 Ownership and atomic publication | **Evidenced for tested paths** | S6 rolled back unpublished; S7 hard kill at ~300 s, locks freed at once, next tick reconciled `interrupted`, no `running` left [M]. R10 recovery committed (`4db0a84`) | Frozen-but-not-terminated instance not observed; the 330 s idle timeouts are the bound | S7 idle-in-transaction fix applied tonight on the branch, uncommitted: owner checks now commit, with a test against PG. Optional freeze drill |
| G5 Supabase Free fit | **Open** | Connectivity [M]. Egress estimate ~0.2 GB / 5 GB per month [E]. Jobs backends peak 5 of limit 12 (S9) [M] | Pause/resume behaviour, dashboard egress, quota-denial behaviour unknown. Connection budget across warm instances (R14) | Owner dashboards. R14 analysis (Codex task C2, tonight) |
| G6 Owner authentication | **Open — owner in progress (2026-10-09)** | Provider-level flow on Free: sign-up refused, password + TOTP → `aal2`, refresh, global sign-out, admin recovery, P3-2 verifier on real tokens [M] | A1 recovery leaves sessions alive (F1). A2 no app-integrated path. A3 no deployed negative matrix | Owner (in progress). This section was intentionally not updated tonight |
| G7 Independent encrypted backup | **Open — design decided, not run** | P1-1..P1-5 decided. Runner, store adapter and restore tool exist. Local synthetic dump/encrypt/restore [M]. Backup repo created | No real chain: PG17 dump via pooler → upload → download on another machine → restore → fingerprint | Owner: keys, gh login, repo variables, then first manual run (approval) |
| G8 No paid prerequisite | **Open** | Console showed $0 (owner report). Capacity estimates ≤ 20% of every Hobby/Free limit [E] | Vercel usage/billing APIs returned no data; no billing evidence | Owner: screenshot or export of usage and billing pages |

## Decisions the owner can take without new runs

1. **R9 — adopt the 210 s application deadline.**
   - Measured: S6 finalized at 209.9 s and kept 89.4 s in reserve.
   - Plan threshold: the reserve must be ≥ max(30 s, 0.20·D) = 60 s. 89.4 s meets it.
   - Recommendation: adopt it.
2. **R13 — land the bucketed classification scans** as a behaviour-preserving change (see the R13 document).
3. **R21 — set a teardown date** for the disposable M5 resources (Vercel previews and bypasses, Vault secrets, the `pft_m5_cron` fixture).

## Items no single run will close

- **R15 honest status model.** Design draft: [R15](PFT_M5_R15_STATUS_MODEL_2026-10-09.md). Owner decisions D1 and D2 are inside. This is M6 work, not a gate measurement.
- **R16 PUBLIC TEMP privilege.** Handle it at Production configuration (C4), as already decided.

## What would make SERVERLESS_GO possible

All of G1–G8 need affirmative evidence. The minimum remaining set is:

| Gate | Remaining work |
| --- | --- |
| G6 | A1–A3 |
| G7 | One real backup chain plus a restore |
| G8 | Billing evidence |
| G5 | Pause/resume and dashboard egress observation |
| G2 / G3 | One more approved cloud session for repeat samples |

None of these can run unattended. Each needs owner credentials, dashboards or approval.
