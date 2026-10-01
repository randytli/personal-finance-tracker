# M5 fresh-session cloud smoke execution — 2026-10-01

**Historical initial smoke run.** Its connection/routing blockers were subsequently resolved in the [cloud compatibility follow-up](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md); compatible client packaging now passes. The historical results below are retained.

**M5 remains incomplete; SERVERLESS_GO is withheld. The large cloud sync benchmark and cron were not started because the basic connection/pool/lock gate failed.** Production remains untouched. No Production environment files, financial data, exports, Plaid credentials or tokens were accessed/copied. No Plaid calls, B2 operations, migrations of Production, or financial-domain changes occurred.

This execution continues the already approved disposable experiment in [the preparation packet](PFT_M5_CLOUD_PREPARATION_2026-10-01.md). Current repository HEAD observed during execution is `a047b0f4b32c2db23203fbab9b25cd5fe7678400`; the packet was reused and its original Python source manifests verified before upload. Only its probe entrypoint was subsequently updated for the supplied public CA certificate, preserving each immutable bundle-role suffix and refreshing the affected hashes. No local benchmark or broad preparation rerun was needed.

## Provider access and cost checks

- **Supabase callable:** organization list, organization details, cost, project creation, SQL, migration and security-advisor tools succeeded. The owner explicitly selected `randyli` (`luumrlkunkvunodouypt`); provider details show `free` / `tier_free`, with zero existing projects before creation. `get_cost` returned $0/month and `confirm_cost` succeeded before creation. Current [Free pricing](https://supabase.com/pricing) was refreshed.
- **Vercel connector partially callable:** team and personal-scope project listings succeeded and returned empty lists. Its advertised `deploy_to_vercel` returned `Tool deploy_to_vercel not found`. Access to the subsequently identified `pft2` team returned 403 requiring that scope's authentication. The empty connector listings therefore do not establish that the account has no teams.
- **Vercel CLI fallback authenticated:** installed pinned CLI **62.1.0** only under `/tmp/pft-m5-provider-cli-20261001`; owner completed device login. CLI account is `randytli`; team `pft2` (`team_DbyIy27VtFdYPG8hKeT20FFU`) is active **Hobby**, with no trial, no soft block and one concurrent basic build. Auth files stay under the private experiment directory. CLI team project listing was empty before creation. No repository-root linking or Git integration occurred.
- Vercel `usage --json` failed: billing cost data unavailable for the selected date range. **This is UNKNOWN, not zero usage or verified $0 billing evidence.** Current [Hobby documentation](https://vercel.com/docs/plans/hobby) was refreshed; actual monthly request/CPU/memory/transfer usage remains unmeasured.
- Supabase changelog was fetched. The fresh server is **PostgreSQL 17.11**, not the local PostgreSQL 16 backup tooling. The [17.11 breaking-change notice](https://supabase.com/changelog/postgres-15-19-17-11-breaking-changes) was inspected; the identity-only schema introduces none of the affected indexes/operators/legacy PGP data. Backup/recovery tools still need compatible versions.

## Exact resources created

| Resource | Provider ID | State / region |
| --- | --- | --- |
| Supabase `pft-m5-synthetic-20261001` | `acyghoemtdrilsdszolq` | Free, ACTIVE_HEALTHY, `us-east-1` |
| Vercel `pft-m5-reader-20261001` | `prj_Mwj8yCakhXMDDNa8d3wVgdOYk64p` | Hobby, `iad1` |
| Vercel `pft-m5-jobs-20261001` | `prj_T8mZTCne3EfvSAS1y7DvmNcJ17Kb` | Hobby, `iad1` |
| Vercel `pft-m5-web-probe-20261001` | `prj_fpqcRuzagxcs7WmNTZsS37tS3ECF` | Hobby, `iad1` |

Fresh dataset/deployment IDs, role passwords and separate service capabilities were generated privately. The prepared SQL created only `pft_m5_probe.identity`, one synthetic identity row, and `pft_m5_reader` / `pft_m5_jobs`. No financial fixtures or financial tables were created. Provider migration `m5_synthetic_identity` succeeded.

Grant inspection confirms no superuser/createdb/createrole/replication/bypass-RLS privileges, reader/job connection limits 8/12, reader default transactions read-only, identity SELECT only, no identity writes and no schema CREATE. A scan of all non-system tables found only that identity SELECT accessible to these roles. Both roles still inherit database TEMP privileges through PUBLIC: **recorded least-privilege gap**, not certified as fully hardened. Security advisor returned no lints; it does not prove connection/security acceptance.

Database size was **10,786,483 bytes** before probe schema creation and **10,892,979 bytes** at the cleanup check. These are SQL `pg_database_size` samples, not provider billing/egress/storage dashboards. The latter check found **one identity row, zero open probe-role sessions, zero advisory locks**.

## Deployment target correction

Vercel classified each project's first source deployment as its `production` target, even when the Python CLI invocation explicitly specified `--target preview`; the first web API upload behaved likewise. These were **new disposable synthetic projects**, never the PFT Production application. Their production environment configurations had no experiment credentials. Authentication protection was retained.

Separate subsequent deployments have provider `target: null`, the documented preview marker. See the [deployment API](https://vercel.com/docs/rest-api/deployments/create-a-new-deployment). The initial synthetic-project production-target builds remain recorded, not silently described as previews:

- Reader initial: `dpl_FVQPtGUE1GKNmLDzmBin1b677Ydo`.
- Jobs initial: `dpl_5gck4NKtjPUTwdkvGLotd7jkkTKB`.
- Web initial: `dpl_69mykgia7riwT9dwk7z6Q8ngxPZh`.

Python previews before CA support were `dpl_4Xc9zFprrbjhGzMdPJFRM93RgAeb` / `dpl_Hw9zGy23arPkdAYo9UDrxDdhc5d6`. Final CA-enabled previews are reader **`dpl_59puPXsPtgK7nRyb5GuRxthFo5eD`**, jobs **`dpl_6CTDrEMVHT5WDyGkGUSUmcSBGj6d`**. Web preview is **`dpl_43ikb59rwcf3ywebShoiT3d5H6Lx`**. Sanitized [deployment metadata](evidence/m5-2026-10-01/cloud-smoke/) records actual readiness/configuration; do not infer READY from source upload acceptance.

Only verified source allowlists were uploaded, never packet-root templates/private SQL/proof files. Python and web experiment environment entries target **preview only**. No custom domain, Git link, Vercel cron, Supabase cron, paid add-on or B2 resource was created.

## Measured Python runtime and capability results

Both Python previews returned 200 for capability-protected runtime and import probes. Actual runtime **Python 3.12.14**; native packages loaded at the pinned versions: FastAPI 0.141.1, SQLAlchemy 2.0.52, asyncpg 0.31.0, plaid-python 42.0.0, cryptography 41.0.7. All **7 reader / 9 jobs** imports passed. `api.main` was absent and the unused global application engine had zero checked-out connections. No financial route was mounted or domain service executed.

Private temporary write/hardlink/cleanup succeeded, with **538,324,992 bytes** temporary free space reported. **`pg_dump` is absent** in both runtimes; backup packaging is still open. Native imports are not an installed-bundle size measurement.

Missing and wrong capabilities returned **401** for each role. Authenticated reader POST `/probe/locks` returned **403**. CLI requests used Vercel's authenticated protection bypass; they do **not** prove a free external cron/web upstream can reach protected previews without owner authentication. Deployment protection remains enabled.

Provider metadata confirms Fluid and configured function timeout **300 seconds** in `iad1`; no timeout-limit experiment proves usable D yet. These are tiny smoke samples, not cold/warm distributions, p95 headroom, billed compute or scale/instance counts. Client times include CLI/control-plane work and must not be labeled function execution time or DB RTT. [Raw sanitized samples](evidence/m5-2026-10-01/cloud-smoke/cloud-smoke.json).

## TLS and basic connection gate failure

The control-plane direct host is `db.acyghoemtdrilsdszolq.supabase.co`. Its local DNS resolves to IPv6; the local client fails with `OSError` errno 101 (no network route). This is local-client reachability evidence, not a Vercel IPv6 result.

The owner confirmed the actual Connect dialog session endpoint **`aws-0-us-east-1.pooler.supabase.com:5432`**. Default CA validation failed with code 19, `self-signed certificate in certificate chain`. The owner supplied the public certificate at `/mnt/c/Users/tianr/Downloads/prod-ca-2021.crt` and explicitly required CA + hostname verification. Its SHA-256 fingerprint is `807025AD50D4ED219D2C9C7D299C004F824EB00CF7F65AFEF607D07B72E6CAFA`; expiry 2031-04-26. No private key was supplied/read.

The experimental probe now optionally adds `M5_SUPABASE_CA_PEM` to a default SSL context. It retains `CERT_REQUIRED` and hostname checking; malformed certificates fail. That public PEM was configured only on the synthetic Python previews. No global system trust store was changed.

With the supplied CA, the local reader connects and matches database/role/sentinel, **but `pg_stat_ssl` for the PostgreSQL backend reports `ssl=false`**. This view describes the database-side session behind Supavisor; it must not be conflated with the independently validated client-to-pooler TLS connection. The prepared identity gate requires a positive backend SSL row and remains unchanged.

Both final cloud previews return **500** for `/probe/connection?pool=null` and `pool=small`; jobs POST `/probe/locks` also returns 500 before lock acquisition. Runtime logs confirm **`RuntimeError: DB role/TLS identity rejected`**. No prepared-query/PID-continuity, successful pool comparison or advisory-lock acceptance is asserted. [Local direct result](evidence/m5-2026-10-01/cloud-smoke/direct-local-result.json), [local session result](evidence/m5-2026-10-01/cloud-smoke/session-local-result.json).

**Next safe step:** inspect the new project's SSL enforcement and Supavisor-to-PostgreSQL TLS policy through authenticated provider settings. Determine whether Free session pooling can satisfy the positive backend TLS gate, or prepare a separately reviewed, layer-specific proof of the required TLS boundary. Do not simply remove the guard, use `ssl=False`, disable certificate/hostname validation, or buy IPv4. Re-run basic connection/pool/lock probes before any large shared-sync benchmark. No architectural impossibility or SERVERLESS_NO_GO is inferred from this still-unresolved probe/configuration issue.

## Verification and remaining work

The CA change's focused M5 suite passed **17 tests**, including certificate-required/hostname preservation and invalid-certificate rejection. Changed Python compiled; `git diff --check` passed. Full financial integration suite/local frontend builds were not repeated: financial behavior and product UI were unchanged; actual isolated provider builds were used. No Production restart is required.

Web preview **READY**, `target: null`, Hobby / `iad1`. The original five-file Next.js packet built without local UI changes. Missing service capability returned **401**, invalid operation **422**, valid `operation=runtime` **502** with sanitized `Reader request unavailable`. A direct reader request with a valid service capability but no Vercel bypass returned **302**; no redirect was followed. The web source refuses redirects and does not forward Vercel protection bypass. [Web samples](evidence/m5-2026-10-01/cloud-smoke/web-smoke.json) demonstrate this routing barrier; a supported authenticated service-to-service path remains required before web/cron acceptance. The configured web route is 90 seconds, while deployment-wide config reports a 300-second default; per-route effective duration remains unverified. Web-to-reader success is not accepted.

Large sync/catch-up, timing distributions, cancellation/publication, owner Auth, cron, quotas/growth, independent encrypted recovery and backup packaging remain open. **B2 is unapproved and untouched.** No M6 or Production cutover authorization is implied. All resources remain disposable with no schedule; retain private credentials and sanitized evidence for continuation, and use the previously approved teardown scope after the agreed retention decision. No commit/push performed.
