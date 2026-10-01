# M5 approved cloud experiment: access preflight and B2 gate

**Decision: WITHHELD. Cloud execution is not complete.** No cloud resources created, no deployment, no provider SQL call, no cron job and no backup upload. Production was not accessed or modified. No Production data, exports, Plaid credentials/tokens or secrets were read/copied. No domain optimization or financial semantics changed.

The owner approved the disposable Supabase/Vercel experiment described in [the first-pass report](PFT_M5_FEASIBILITY_2026-10-01.md), then explicitly retained a separate B2 approval gate. That authorization persists; missing authentication is not a request to reapprove the experiment. [Phase 2 plan §12](PFT_PHASE_2_ARCHITECTURE_PLAN.md#12-m5--zero-cost-serverless-feasibility) and AGENTS.md govern execution. Current HEAD remains `5dbca0667eba5e305f6ad12925af46b01842d6ee`; unrelated working changes preserved.

## Access preflight — measured local facts

The workspace has no `vercel` or `supabase` executable, no available `VERCEL_TOKEN` or `SUPABASE_ACCESS_TOKEN`, and no standard provider CLI auth files at the three checked paths. Only presence/absence was checked; no credentials were printed or loaded from repository env files. Provider integrations were discovered and offered; both latest integration states are **not installed/connected**, with no callable provider tools available in this session. The owner's selection of the integration option is acknowledged; it is not evidence that installation/OAuth finished. No provider account or Free/Hobby entitlement can be verified until access exists.

**Next input needed:** complete both Supabase and Vercel integration connections in the app. Do not paste credentials into chat. After connection, inspect capabilities and account plan/usage read-only, then create only the previously approved named synthetic resources if their plan/eligibility/capacity checks pass. If the integrations cannot create/build/upload source or expose the needed metrics, report that specific gap and establish provider CLI authentication; do not claim a connector implies full API capability.

## Prepared local probe and source allowlist

- [runtime_probe.py](../experiments/m5_cloud/runtime_probe.py) exports only `/probe/runtime`, `/probe/connection`, `/probe/locks`, all behind a fresh experiment service capability. It disables docs/OpenAPI endpoints and does not mount `api.main` or any financial route. Reader cannot invoke the jobs lock probe.
- Configuration rejects Production mode and Plaid credentials, pins the exact reader/jobs project name and synthetic project ref, requires a role-specific direct/session URL and explicit dataset/deployment IDs, and rejects transaction-pool URLs. URL pinning must be initialized from the actual newly created project; a supplied sentinel alone cannot establish non-Production identity.
- Connection probes require default CA/hostname certificate validation, correct PostgreSQL database/role, a TLS-positive `pg_stat_ssl` row and matching restricted synthetic identity table. Request engines are bounded and disposed in finally. Lock probe tests PID continuity over commit and denial to a second session, then unlocks/invalidate-on-cleanup-error. This does **not** yet prove disconnect/hard-kill behavior.
- Runtime probe checks native package versions and temporary-file/private-mode/hardlink cleanup, temporary free space and `pg_dump` presence. No backup invocation or upload exists in this adapter.
- [prepare_cloud_bundle.py](../scripts/pft_m5_prepare_cloud_bundle.py) copies only Python files from four explicit source directories plus this probe. It excludes `api/main.py`, migration/sync CLI entrypoints, all env files, dumps, CSVs, frontend assets and `.git`. The bundle root declares Python 3.12, original API requirements and a 300-second Vercel maximum. That is a **candidate config**, not proof of runtime duration or a below-provider application deadline.
- Staged candidate: `/tmp/pft-m5-cloud-20261001-reader-source`, 34 manifest entries, **274,789 source bytes**. [Source manifest](evidence/m5-2026-10-01/cloud-source-manifest.json) records per-file hashes. This excludes installed dependencies/runtime/binaries and is not a Vercel build artifact. No upload happened. Build another fresh candidate for jobs before configuring it; do not accidentally share reader/job credentials.

The prepared service token is an isolated capability probe, **not owner Auth proof**. Supabase JWT verification/login/refresh/logout, BFF-versus-bearer comparison, synthetic fixture setup, full shared sync remote driver, failure injection, cron and quota collection remain to be implemented/executed against verified provider capabilities. No current probe offers arbitrary SQL or publicly callable seed/admin actions. Actual reader denied-write grants and jobs-only capabilities must be verified on the new synthetic DB.

Local verification: six cloud guard/bundle tests plus three prior scheduler draft tests **passed (9 total)**. No network/DB/Plaid call in these tests. Configuration rejection and endpoint enumeration are local evidence, not cloud security acceptance. Changed Python compiled and `git diff --check` passed. No frontend/UI change was made, so rendered UI QA/build is not applicable. No Production restart is required.

## B2 primary-source review — separate gate remains closed

Official documentation was fetched again on **2026-10-01**. **An enforceable exact $0 boundary is not established by the current published evidence.** B2 is not selected and bucket creation, billing exposure and uploads remain unauthorized pending the owner's separate approval after adequate evidence. No B2 account was opened or queried.

| Fact verified from primary source | Meaning / remaining gap |
| --- | --- |
| First 10 GB storage free; pay-as-you-go Class A/B/C API calls free; Class D first 2,500/day free then charged; ordinary free egress up to 3× monthly average stored bytes | Permanent allowance, not a credit trial. Count all versions/unfinished parts/account usage and actual recovery downloads. This alone is not a hard spending ceiling. [Current pricing](https://www.backblaze.com/cloud-storage/pricing) |
| Caps can be configured as dollar-per-day limits; updates can take up to ten minutes | No explicit exact-zero/overshoot/concurrent enforcement guarantee in this page. Settings must take effect before any use; alerts are separate from caps. [Set/manage caps](https://www.backblaze.com/docs/cloud-storage-create-and-manage-caps-and-alerts) |
| Class D operations cannot be capped; no-cap accounts can accrue unlimited charges | Disable Event Notifications, omit related capabilities and verify the account's existing settings/usage. Cannot represent category caps as an account-wide cap. [Cap coverage](https://www.backblaze.com/docs/cloud-storage-data-caps-and-alerts) |
| Native uploads can return `403 cap_exceeded`; integration guidance says stop and exposes a forced-cap-error test header | Actual request-denial mechanism documented. Forced error tests verify client handling, not actual billing enforcement or a $0 cap. [Upload API](https://www.backblaze.com/apidocs/b2-upload-file), [Integration checklist](https://www.backblaze.com/docs/cloud-storage-integration-checklist) |
| Signup says no credit card required | A candidate account can potentially avoid adding a payment method. That is not a contractual promise of no accrued usage liability or a confirmed permanent account configuration. [Signup](https://www.backblaze.com/sign-up/cloud-storage) |
| Usage-based fees continue to accrue with usage until data/account removal or termination under the service terms | **Inference:** rejecting new writes does not itself establish that previously retained over-limit bytes stop accruing storage charges. Need explicit provider enforcement/terms evidence for an exact-zero account before selection. This is not a claim that an overage occurred. [Service terms, usage-based services](https://www.backblaze.com/company/policy/terms-of-service) |

The proposed safe candidate remains: private bucket, experiment-only prefix-limited key, notifications disabled, no payment method added, seven recent encrypted points, bounded maximum object/part/version bytes and recovery download budget, and confirmed active $0 caps. **Do not create it now.** First resolve whether the actual account can forbid billed usage (including stored-byte-hour liability, all operation categories and downloads), whether zero-valued caps are accepted and enforced without an exposure window/overshoot, and what happens to recovery reads at the cap. Written primary-provider clarification may be necessary; no message to the provider is authorized or sent. If terms/enforcement cannot satisfy the permanent $0 requirement, document the backup architecture blocker for review rather than silently selecting paid storage or another provider.

## Required experiment report: current disposition

| Requested result | Current evidence / status |
| --- | --- |
| 1. Resources actually created | **None**. Supabase/Vercel/B2 account access not established |
| 2. Actual Vercel packaging/runtime | **UNKNOWN**. Only staged source and local guard checks; no Vercel build or invocation |
| 3. Supabase TLS/pooling/advisory locks | **UNKNOWN**. Probe prepared; no managed DB connection |
| 4. Real cold/warm/concurrent distributions | **UNKNOWN**. No cloud samples; do not reuse local import timings as cloud cold starts |
| 5. Shared sync/catch-up/headroom | **UNKNOWN**. Prior local grown no-op p95 43.17 s and injected-delay result 127.39 s/71,379 queries remain local only. Targets unchanged: normal ≤0.50D, worst ≤0.70D, reserve ≥max(30 s,0.20D). Real serial-query latency must be measured before any optimization review |
| 6. Cloud cancellation/timeout/publication safety | **UNKNOWN**. Local guard/lifecycle tests do not prove hard termination, uncertain commit, thread cleanup or stale-owner prevention on Supavisor |
| 7. Cron duplicate/delivery/recovery behavior | **UNKNOWN**. No schedule created. One five-minute Supabase trigger remains proposed; job direct endpoint and explicit pg_net timeout still require real verification |
| 8. Auth/security | **UNKNOWN cloud**. Service-capability guard checks pass locally. Owner Auth, DB grants, BFF/bearer, CSRF/cache/refresh/logout/recovery not tested on provider |
| 9. Measured quota/capacity and growth projection | **UNKNOWN**. No account/provider metrics available. Prior synthetic retained-history sizes and SQL amplification are not managed-provider quota measurements |
| 10. Backup | **BLOCKER / separate approval gate closed**. Exact $0 boundary unproven; no independent upload/download/restore. Packaging/remote profile/unattended keys still open |
| 11. Remaining UNKNOWN/BLOCKER | All real-runtime rows of the first-pass matrix remain open; identified current implementation blockers unchanged. Additional access prerequisite now recorded |
| 12. Decision | **WITHHELD**, not GO or evidence-based NO_GO. Access failure is not proof that the architecture cannot work; material unknowns prevent GO |

Do not migrate/cut over on any result. Resume the already approved cloud experiment after provider connections are confirmed, without requesting that approval again. B2 remains separate. Before writes, pin exact newly created project IDs, validate current Free/Hobby entitlement/account headroom and source manifest, generate only experiment secrets and deny every off-scope target.

## Follow-up 2026-10-01: probe/bundle hardening and local latency curve

Local, synthetic and non-Production only. No provider call, Production access, Plaid call or financial-behavior change.

**Bundle entrypoint correction.** Current [Vercel Python docs](https://vercel.com/docs/functions/runtimes/python/api-directory) state a detected framework preset takes precedence: files under `/api` do not become separate functions. The staged root `main.py` exports `app` and `requirements.txt` lists FastAPI, so the bundle's `api/` package is not expected to collide, and `functions["main.py"]` matches the documented resolved-entrypoint key. `prepare_cloud_bundle.stage` now fails closed if any documented entrypoint other than root `main.py` exists, or any other bundled module defines `app`, `application` or `handler`, so a preset-detection fallback cannot expose a module. The real build must still record which mode Vercel selected and the effective `maxDuration`.

**Import probe.** `/probe/imports` (capability-protected) imports root-relative application modules — shared models/derivation/`statement_imports`, plus reader routes or jobs `sync_all`/`jobs`/`backup` — without calling them, and reports per-module success, time and error type only. Locally both roles pass; reader modules do not load the Plaid SDK or `api.routes.plaid`. Both roles create `api.db`'s module-level default-pool engine on import (zero checked out); M6 should make that engine lazy/factory-owned rather than relying on callers never using it.

**Latency sensitivity.** Local injected-latency results, interpretation, corrected growth horizon and the deadline position are recorded once in the [feasibility report](PFT_M5_FEASIBILITY_2026-10-01.md#latency-sensitivity-curve-follow-up-2026-10-01) (raw: [latency-curve.json](evidence/m5-2026-10-01/latency-curve.json)). That is a local sensitivity test, not cloud evidence. Next decisive measurement for this experiment: actual Vercel-to-Supabase database latency and total sync wall time on the disposable synthetic environment.

Verification: M5 tests 12 passed; full backend 279 discovered, 193 passed, 86 opt-in integration skipped; changed Python compiled; `git diff --check` passed. Local cluster stopped after measurement.
