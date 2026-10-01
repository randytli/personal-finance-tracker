# M5 cloud preparation while latency sensitivity is running

**Cloud decision remains WITHHELD.** This document records completed local preparation. The subsequent fresh-session [cloud smoke execution](PFT_M5_CLOUD_RUN_2026-10-01.md) created only the approved disposable Supabase/Vercel resources; the subsequent [compatibility follow-up](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md) passes basic connection/TLS/session/lock/protected-routing and PostgreSQL client packaging checks. The later owner-approved [bounded real-cloud benchmark](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md) is complete: current-scale no-op succeeds, while the 35.6k growth envelope fails. This preparation record remains historical.

This packet supplements the [approved experiment](PFT_M5_CLOUD_EXPERIMENT_2026-10-01.md) and [M5 plan](PFT_PHASE_2_ARCHITECTURE_PLAN.md). It does not update the other agent's latency report or evidence. The running synthetic database, latency harness and its outputs were not accessed or changed. No second database benchmark, Production action, Plaid call, commit or B2 operation occurred.

## Provider access

Latest integration discovery on 2026-10-01 now returns Supabase and Vercel as **installed and enabled** (`installed:true`). Dependency inspection confirms both plugins are installed and user-enabled, with no unresolved app dependencies. This supersedes the earlier installation failure. However, the session's callable tool catalog still exposes **no Supabase or Vercel provider tools**. Installation does not establish that this session can query accounts or provision/deploy resources; provider OAuth usability and account entitlement remain untested.

Local presence-only checks also confirm neither provider CLI executable, neither `SUPABASE_ACCESS_TOKEN` nor `VERCEL_TOKEN`, and no auth file at the three previously checked standard paths. No credentials were read or printed. No external resource or deployment was created. Resume in a session that exposes the installed provider tools, or establish local provider CLI authentication without pasting tokens into chat. The existing cloud authorization persists; no additional approval for the same disposable scope is required. Once tools are exposed, inspect actual capabilities; SQL-only or read-only connectors may still need authenticated CLI access for build/source upload and metrics.

## Local deployment packet

Generate a fresh private directory with:

```sh
.venv/bin/python -m scripts.pft_m5_prepare_cloud_packet --destination /tmp/NEW_PRIVATE_M5_PACKET
```

Prepared final instance: `/tmp/pft-m5-cloud-preparation-20261001-final-packet`.

| Upload directory | Candidate | Local source measurement |
| --- | --- | --- |
| `reader/` | `pft-m5-reader-20261001`, Python 3.12, FastAPI root `main.py`, configured 300 s | 23 manifest entries, 176,995 bytes |
| `jobs/` | `pft-m5-jobs-20261001`, same runtime/configuration, separate capability and DB role | 28 manifest entries, 182,658 bytes |
| `web-probe/` | `pft-m5-web-probe-20261001`, Next.js Node API route `/api/probe`, configured 90 s | 5 files; existing repository npm manifest/lock reused |

Counts exclude their subsequently written Python source manifests. These are source candidates, **not installed dependency sizes or Vercel build artifacts**. Both Python candidates intentionally retain the repository's complete pinned requirements; package-level separation and real installed bundle size remain unmeasured. Reader application sources exclude scheduler/sync, backup and Plaid routes; jobs carries its own import closure. No financial routes are mounted. Each generated bundle enforces its immutable reader/jobs role even if its environment is misconfigured. Source hashes capture the copied working-tree version; regenerate and inspect them immediately before uploading if another agent changes shared probe source.

Only upload the three subdirectories, each to its own project. Never upload the packet root: `*.env.template`, SQL template and local proof outputs stay outside the upload trees. Do not link the repository root or existing Vercel project. No `.env`, database dump, export, existing provider configuration or `.git` is copied. Keep private credentials out of source and shell output. Use separate provider environment entries for the exact disposable projects, with no Production/branch-inherited secrets.

Vercel documents root `main.py` FastAPI discovery, Python 3.12 and requirements installation. Real provider builds still must prove import discovery, native wheels, source/dependency size, configured duration and installed versions. [FastAPI](https://vercel.com/docs/frameworks/backend/fastapi), [Python runtime](https://vercel.com/docs/functions/runtimes/python), [function limits](https://vercel.com/docs/functions/limitations).

## Local checks completed

- Four Python tests pass: source/role separation, template exclusion, fresh-directory rejection, invalid pool bounds and sibling-task cleanup after failure.
- The Node test file passes: unauthorized/configuration rejection, pinned upstream/capability forwarding, no forwarded cookies and sanitized upstream failures.
- Isolated fresh-process import checks pass for all **7 reader / 9 jobs** modules. Socket connect and DNS operations were blocked: **zero network attempts**, no `api.main`, zero global-engine checkouts. Results are `reader-local-import-proof.json` and `jobs-local-import-proof.json` in the private packet root. These use fabricated configuration, not real credentials.
- No local Next.js build/dependency installation or heavy test suite was run while another agent measures latency. The web route's relative import resolves; actual Next/Vercel build remains required. No product UI changes or rendered UI QA are involved.

## Exact first cloud actions, after authentication

1. Read account identity, Free/Hobby eligibility, project capacity and current quota usage. Refresh primary provider limits before provisioning. Stop for review if the approved configuration needs paid services, trial credits or a different resource scope. Record provider IDs, plans, regions and baseline usage without secrets.
2. Create **one Supabase Free project `pft-m5-synthetic-20261001`** in a dedicated synthetic scope. Disable any unnecessary sample/auto workloads. Generate a new project password and record the new control-plane ref before any SQL. Create no paid IPv4 add-on or upgrade. Never use a pre-existing project just because a sentinel matches.
3. Render `synthetic-identity.sql.template` privately with fresh dataset/experiment IDs and separate reader/jobs passwords; apply only to that newly verified project. It fails on existing probe schema/roles, grants both roles only identity SELECT, makes reader transactions read-only, and provides connection limits (8 reader / 12 jobs). Verify inherited/default privileges separately: this template is not proof that provider defaults satisfy least privilege. Confirm authenticated roles see their own `pg_stat_ssl` rows. No financial table or fixture is created in this first step.
4. Read the new project's actual Connect dialog. Prefer the free shared **session** endpoint on port 5432 for initial IPv4 testing; also test direct IPv6 without buying IPv4. Pin project ref, username, DB, sentinel IDs and exact endpoint. Supabase documents direct IPv6 and shared session pooling; transaction pooling cannot preserve this application's session locks and is rejected by the probe. [Provider connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).
5. Create the three named **Vercel Hobby projects**, with no Git/Production linkage, domains or scheduled Vercel cron. Set each exact environment template with only new experiment credentials. Build/deploy each candidate from its own directory as a disposable preview. Keep project production configuration empty; exercise the pinned preview URLs. Record CLI/tool/build versions, project deployment IDs, provider build logs, actual Python/Node versions, installed/native package sizes, limits and runtime region. The FastAPI documentation specifies CLI 48.1.8+ if CLI deployment is used; verify installed/current tooling first. [FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi).
6. Set the web upstream to the exact immutable reader deployment hostname and separate reader capability. Its service routing is **not Supabase owner Auth**. Do not expose service capabilities in browser bundles or `NEXT_PUBLIC_*`. Use an HTTPS client with redirects disabled, explicit timeouts and private output files. Never put bearer values in URLs, logs or pasted commands.

## First probe checklist and evidence format

For every sample record UTC timestamp, project/deployment ID, role, endpoint, HTTP status, client wall time, response, instance ID when available and provider logs/metrics correlation. Save only sanitized evidence in a new cloud-only output directory. Report failures and censored timeouts as well as successes. Do not reuse the latency agent's output path.

| Probe | Calls / measurements | Acceptance or remaining gap |
| --- | --- | --- |
| Packaging/runtime | Reader and jobs GET `/probe/runtime`, GET `/probe/imports` | All imports succeed; no main/financial app loaded; actual versions, temp write/hardlink/cleanup, binary presence. Runtime response does not prove `pg_dump` backup feasibility. |
| Capability boundaries | Missing/wrong token, swapped role/project environment; reader POST `/probe/locks`; web unknown operation / wrong host | 401, configuration rejection, reader 403; no SQL on unauthorized requests. Verify provider deployment protection does not make the external free trigger impossible. |
| TLS/session/direct | GET `/probe/connection?pool=null` and `pool=small` for each endpoint | Validating SSL context, actual role/database/sentinel and TLS-positive server identity, prepared result 42, stable PID across commit. Wrong ref/sentinel/credentials, certificate/hostname and unavailable IPv6 failures must be measured safely on disposable configuration. |
| Pool comparison | GET `/probe/pool?pool=null&reads=5&concurrency=1`, repeat `pool=small`; then concurrency 2 and 4, at most 20 reads/request | Compare wall time, acquisition/identity timing, PID reuse, failures and server/session client counts. Engine is per request and disposed; these results **do not prove global warm-invocation pooling/event-loop compatibility**. Identity reads include two SQL statements and must not be labeled pure network RTT. |
| Session advisory lock | Jobs POST `/probe/locks`, then two concurrent calls | Owner PID survives commit; contender denied; duplicate request may return 409; release after completion. Abrupt process kill, stale owner/fencing and uncertain publication remain separate experiments. |
| Cold/warm endpoints | Sequential runtime/import samples, then 2 and 4 concurrent requests; initial budget 20 serial + 10 samples per concurrency per role | Classify instance-first observations versus repeat instance observations; report n/min/median/p95/max and failures. A client idle gap is not proof of a cold start. Separate client latency, import timing and provider execution duration; concurrency workers and same-instance co-residence require provider evidence. |
| Web routing | GET `/api/probe?operation=runtime`, `imports`, `connection` | Reader capability remains server-side; no Set-Cookie forwarding, redirects or raw upstream errors. Separate web-to-reader extra latency. Owner JWT/session/refresh/logout/CSRF tests remain unimplemented. |
| Quotas | Before/after actual provider metrics per project: DB/storage/egress/connections, Vercel requests/CPU/memory/transfer | Record reporting lag and unexplained usage. Source sizes and local timings are not quota evidence. |

The pool helper uses structured task cancellation, bounded reads/concurrency, a 55-second cooperative deadline and final engine disposal. Its mock cleanup test does not prove Vercel hard-timeout cleanup. The underlying shared application import creates an unused global engine with its existing defaults; the identity probes use fresh validating-TLS engines. Test any proposed real shared execution adapter separately before asserting the application itself uses these safe connection settings.

## Work deliberately deferred

Do not start the large cloud shared-sync benchmark until the latency agent finishes. Afterwards use a **new cloud synthetic fixture**, not local/Production data, and the same unoptimized financial services. The plan's targets remain normal execution ≤0.50D, worst/catch-up ≤0.70D, reserve ≥max(30 s, 0.20D); determine measured usable D before comparison and retain real timing distributions and tail failures. This preparation supplies no cloud headroom result.

Five-minute Supabase Cron, pg_net timeout/delivery/duplicate/recovery, one-shot scheduler execution, interrupted sync/publication, owner Auth, growth/quota projections and backup packaging/restore remain pending; do not infer success from these connection probes. Configure the single approved Cron only after the jobs execution endpoint and authentication/deadline handling are concretely prepared and measured. B2 creation/billing/uploads remain **blocked and unapproved**. No migration or cutover is authorized, regardless of experiment outcome.
