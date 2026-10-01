# M5 cloud compatibility follow-up — 2026-10-01

**Basic runtime, verified TLS, session/pool/lock and protected routing probes pass. Compatible PostgreSQL client packaging is feasible in the actual Hobby jobs deployment. M5 remains incomplete; SERVERLESS_GO remains withheld. The large 35.6k synthetic cloud sync benchmark was not run and still requires the owner's next authorization.** Production and Production Plaid credentials/data were untouched; no Plaid call occurred. B2 remains unapproved. No dump, external backup storage, cron, paid add-on or trial was created.

Later owner-approved follow-up: the [bounded real-cloud latency and cancellation pass](PFT_M5_REAL_CLOUD_LATENCY_2026-10-01.md) is complete. Current-scale no-op succeeds; all five 35.6k attempts time out before publication. The growth headroom gate fails, and SERVERLESS_GO remains withheld. The compatibility results below are the preceding historical pass.

This continues the approved disposable resources in [the initial cloud run](PFT_M5_CLOUD_RUN_2026-10-01.md), using the existing preparation packet. It supersedes that run's unresolved SSL, connection and web-routing results. The packet was updated incrementally; completed preparation and local benchmarks were not repeated. [Sanitized evidence](evidence/m5-2026-10-01/cloud-compatibility/) contains the raw bounded results.

## SSL enforcement and the two TLS layers

The Supabase connector remains callable for SQL and project inspection. It has no SSL-enforcement settings operation, and no Management API credential was available. The owner enabled **Enforce SSL on incoming connections** in the dashboard for only `acyghoemtdrilsdszolq`, then replied `enabled`. The control-plane setting is owner-reported; the connection behavior below is directly verified. [Provider enforcement documentation](https://supabase.com/docs/guides/platform/ssl-enforcement).

The endpoint is the previously confirmed **session** pooler `aws-0-us-east-1.pooler.supabase.com:5432`. The public Supabase root certificate supplied by the owner was added to the default trust context; certificate and hostname validation remain mandatory. No global trust changes or insecure application option was introduced.

| Local synthetic reader attempt | Observed result |
| --- | --- |
| Supplied CA + correct hostname, `CERT_REQUIRED`, hostname checking | Connected; TLS 1.3, `TLS_AES_256_GCM_SHA384`; expected database/role |
| Plaintext, deliberately `ssl=False` in isolated negative test | Rejected: `SSL connection is required` |
| Encrypted TLS with verification deliberately disabled in isolated negative test | Connected; server enforcement cannot determine whether the client verified its certificate |
| Default CA without the supplied provider root | Certificate validation failure; no database connection |
| Supplied CA with intentionally wrong server hostname | Hostname mismatch; handshake rejected before authentication |

[TLS matrix](evidence/m5-2026-10-01/cloud-compatibility/ssl-matrix.json). The requested server rejection of **unverified encrypted** clients is not a capability of SSL enforcement: the client performs certificate validation. Application TLS construction always uses `CERT_REQUIRED` and hostname checking, rejects URL/query overrides and invalid CA material, and the diagnostic refuses an unverified context. Local tests exercise these fail-closed controls. The insecure context is confined to the negative-test script and is never configured in Vercel.

**Client/Vercel → Supavisor:** both deployed roles report a real TLS transport, required certificate verification and hostname checking, TLS 1.3, and the expected role/sentinel. **Supavisor → PostgreSQL backend:** both report `pg_stat_ssl.ssl=true` after enforcement; before enforcement this was false. These are different observations. A positive backend row alone would not prove client certificate validation.

The existing identity guard still requires positive backend SSL plus database, role and dataset/deployment/project sentinel checks. It now passes on the session pooler and was **not weakened or replaced**. No provider-aware exception is needed for this observed configuration. If a future pooled session reports false, the guard still rejects it; the diagnostic can record the layers separately but never grants acceptance (`acceptance_pass=false` is intentional). A replacement would require separate review, not silent fallback.

Both roles passed NullPool and bounded small-pool queries, prepared-query result **42**, and stable backend PID after commit. Jobs advisory locking excluded a second session and retained PID ownership; reader lock access returned **403**. Final state showed no advisory locks or open transactions. PostgreSQL retained **one idle reader and two idle jobs pooler backends**, all TLS-positive; these database-side idle sessions must not be mislabeled open application connections or a zero-connection cleanup result. Request engines are disposed and diagnostic connections closed. Hard termination/disconnect cleanup at scale remains untested.

## Protected web → reader routing

Preview protection remains `all_except_custom_domains`. Automation bypass was provisioned only for the synthetic reader and stored as encrypted **preview-only server environment** `M5_READER_PROTECTION_BYPASS` on the synthetic web project. Provisioning/tests kept the value transiently in memory; it was not written to a request file, repository, browser response, log or chat. No `NEXT_PUBLIC_` variable is used. The route pins the exact HTTPS reader hostname, refuses redirects, sends the server-owned bypass header, and separately sends the reader application capability. Incoming browser cookies/bypass values are not forwarded. [Automation bypass documentation](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation).

The new bypass initially returned 302 during propagation; retries succeeded without changing protection. Direct reader results: valid application capability **without bypass: 302**; bypass with missing/wrong application capability: **401/401**; bypass with valid application capability: **200**. These establish independent provider and application gates, not owner-login/Auth acceptance.

The deployed web route returned **401** for missing web capability, **422** for unsupported operation, and **200** for both runtime and guarded database connection. The latter returned query result 42, verified TLS and stable backend PID. The web preview pins the existing immutable CA-enabled reader `dpl_59puPXsPtgK7nRyb5GuRxthFo5eD`; the later reader diagnostic deployment is separate. This is intentional exact-host routing, not an alias change.

Current READY preview deployments, all `target:null`, Hobby / `iad1`:

- Reader diagnostic: `dpl_UBs7eXg9GNWZ6H6ku4xPgtThNWZy`.
- Jobs client prototype: `dpl_CfFrmrfWLRJRiUYiQCJuha7rs4Ys`.
- Protected web probe: `dpl_6iLXs6XhNKYjy5L5zxsuHQ7ZEVJY`.

## PostgreSQL client packaging

SQL confirms server **17.11**, `server_version_num=170011`; Supabase control-plane build is 17.11.0.002. The local PostgreSQL 16 client is unsuitable for dumping this newer major. Matching 17.11 clients were extracted from official `postgres:17.11-alpine`, digest `sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24`. Extraction ran in a disposable container with networking disabled and without starting PostgreSQL or mounting data. [PostgreSQL compatibility rules](https://www.postgresql.org/docs/17/app-pgdump.html).

The package contains **18 files / 10,411,592 bytes**: pg_dump, pg_restore, the musl loader, and the required libpq, OpenSSL, compression, Kerberos, LDAP/SASL and support libraries. [File hashes and sizes](evidence/m5-2026-10-01/cloud-compatibility/pg-client-manifest.json) record the dependency closure. It runs through its explicit bundled loader/library path, avoiding a glibc ABI mismatch with Vercel's observed **x86_64 / glibc 2.34** runtime.

Inline binary upload was rejected with HTTP 400; using the documented file-upload endpoint and SHA references succeeded. Jobs `includeFiles` includes the package. **`VERCEL_SUPPORT_LARGE_FUNCTIONS=0`** was explicitly set before building both Python previews; the jobs build reached READY and both **pg_dump 17.11 / pg_restore 17.11** executed successfully in the real function. Native files are copied to a private temporary directory, the loader made executable there, and the directory removed afterward. Reader access to this endpoint returns 403.

This proves basic compatible binary/library packaging under the **standard 500 MB Python bundle path**, without the 5 GB beta or a paid runtime. Hobby metadata confirms standard Fluid with a 300-second configured maximum. Exact total installed bundle bytes were not exposed in the inspected deployment metadata; the 10.4 MB figure is the added client package, not total dependencies. [Current limits](https://vercel.com/docs/functions/limitations).

**This is version execution, not backup acceptance.** pg_dump is not on PATH, and the existing backup module is not yet adapted to the explicit loader. No dump output was produced. Source export permissions, consistent full object export, peak temporary space/memory, compression/encryption, duration/deadline cleanup and isolated restore fidelity remain unproved. The independent-backup requirement is unchanged; no external backup provider/storage was provisioned.

## Usage metrics and free-capacity evidence

| Area | Available evidence | Unavailable / UNKNOWN |
| --- | --- | --- |
| Provider/project state | Supabase Free and Vercel Hobby, regions, READY previews, standard runtime configuration; no paid add-on enabled | Exact account monthly remaining allowances |
| Supabase database | SQL server version, database bytes **10,892,979**, one identity row, grants, current backend state/TLS, transaction/lock state; growth from recorded baseline | Monthly billed/aggregated egress, Auth use and provider storage/quota totals; no aggregate usage tool exposed |
| Runtime/request samples | Actual import/runtime versions, probe/status counts, bounded wall times, temporary free space **538,324,992 bytes**, package bytes/hashes, source uploads/build timestamps; scoped runtime logs can diagnose failures | Complete invocation census, billed CPU and provisioned-memory time, actual full-workload peak memory and scale distribution |
| Vercel billing/observability | Metric schema is readable; current `usage --json` failed for the selected date range; scoped invocation query returned `payment_required` / Observability Plus required | Billing totals and observability aggregates; no paid feature purchased/enabled |

Missing convenience APIs are **UNKNOWN, not zero usage and not by themselves SERVERLESS_NO_GO**. A later bounded benchmark can instrument wall/process CPU, peak RSS, request/response bytes, sample counts and SQL connection/storage growth, then conservatively project invocation/memory/transfer use against current free allowances. Process CPU and payload bytes must not be mislabeled provider-billed CPU or egress. Account-wide usage and workload headroom still require evidence before GO; the present identity-only database does not prove the complete monthly free envelope.

## Validation and next boundary

Focused Python suite: **19 tests passed**. Node server-route tests passed; changed Python compiled and whitespace checks passed. A value-based redaction scan checked **48 repository files and 142 private/packet files**: no exported synthetic/provider credentials and no saved new bypass value were found. Real preview builds/runtime probes supply packaging validation; full financial tests and rendered UI QA were not repeated because financial behavior/product UI were unchanged. No Production restart is needed.

The preliminary runtime/TLS/session/lock/protected-routing prerequisites now pass. The next owner-authorized step may be a bounded large **synthetic** real-cloud latency benchmark with explicit deadlines, connection limits and usage instrumentation. It has not started. Cold/warm distributions, full shared-sync correctness/cancellation/publication, hard-kill locks, cron, owner Auth/recovery, complete quota/growth envelope and independent encrypted recovery remain M5 work. PUBLIC TEMP privilege remains a recorded least-privilege gap. B2 stays unapproved, and SERVERLESS_GO stays withheld. No commit or push performed.
