# M5 owner-auth probe and A5 session-revocation design — r2, approved 2026-10-09

**Status: design approved by the owner on 2026-10-09** (D0–D5 in §8, constraints in §8.1). This is design only. No code has been written, no cloud resource created, nothing deployed. The approval permits writing the implementation plan; it does **not** permit any deployment. Every cloud step in §6 needs its own approval. SERVERLESS_GO stays withheld.

**Revision r2** incorporates the owner's review of r1:

| Review item | Change in r2 |
| --- | --- |
| 1. MFA vs. immediate revocation | Two separate requirements, R-MFA and R-REVOKE (§2.1). R-REVOKE is a new decision, D0. The 600-s lifetime is extra protection, not a precondition for C |
| 2. "Window 0" boundary | Exact guarantee and its snapshot limit (§2.4). No caching. Same-token procedure for proving revocation (§5.2, D12–D13) |
| 3. SQL privileges | Revokes and grants in the same migration transaction; executable privilege checks in S1; local PostgreSQL integration test (§2.6, §7) |
| 4. `session_id` and connection lifecycle | `session_id` validated before any connection; request-context dependency that owns the connection; pool and timeouts; 503 vs. 401 (§3, unit 1) |
| 5. Refresh evidence | Browser auto-refresh and middleware refresh tested separately; second request, concurrent requests, logout with back/reload (§5.1) |
| 6. C/D performance | Separate deployments per mode; timing breakdown; sample-p95 caveat; timeout and error-rate criteria (§5.3) |
| 7. A3 coverage | Two evidence tiers: local trusted test key vs. deployed trust boundary. Full claim list. "Changed owner setting" added as a deployed case; no test-key entry in the cloud verifier (§5.2) |
| Small fixes | Status mapping includes 200; per-request IDs and counters replace per-instance totals; failure and cleanup paths (§3, §6) |
| Added by the agent | A JWKS fetch failure returns 503, not 500. The new database test needs a CI opt-in, so the CI inventory must be updated |
| B8 clarification (owner-approved 2026-10-09) | A page restored from the browser's back-forward cache may appear after **Back**; the requirement is that nothing new is fetched (whoami 401) and a reload lands on `/login` |

Inputs:
- [owner-auth acceptance](PFT_M5_OWNER_AUTH_ACCEPTANCE_2026-10-08.md) §3–§4, gaps A2, A3 and A5;
- [Auth design](PFT_M5_AUTH_DESIGN_2026-10-02.md), decisions P3-1 to P3-4;
- earlier M5 probes: [cloud run](PFT_M5_CLOUD_RUN_2026-10-01.md), [compatibility](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md), `experiments/m5_cloud/runtime_probe.py`, `web_probe_handler.mjs`;
- the verifier, `experiments/m5_cloud/auth_probe.py`.

Legend: **[M]** measured earlier in M5; **[D]** official documentation, checked 2026-10-09; **[E]** inference; **未核实** not verified.

## 1. Purpose, constraints, success

**Given (from the owner and the record):**
- Close G6 gaps A2 (app-integrated path), A3 (negatives against a deployed FastAPI) and A5 (window for already-issued tokens).
- Synthetic project `acyghoemtdrilsdszolq` only. No Production, no Plaid, $0.
- The owner enters every secret in their own browser or terminal. The agent never sees passwords, TOTP material, the `sb_secret` key, DB passwords, Vercel bypass values or tokens.
- Each cloud change is approved on its own.
- Keep the probe independent, use new Vercel projects, and leave the product app unchanged (confirmed in the review).

**Assumed:** one owner, using a desktop browser for the browser part.

**Success** means evidence for:
- **A2:** browser login → `aal2` → same-origin server route → FastAPI owner verification. Browser auto-refresh and middleware refresh are each shown on their own; logout works.
- **A3:** every rule in §5.2 has evidence at its stated tier. Rejected requests never reach data.
- **A5** (if D0 is accepted): a token whose session was revoked is rejected by the first request whose check runs after the revocation commits. The cost of the chosen check is measured.

## 2. Requirements and A5

### 2.1 Two requirements, decided separately

- **R-MFA (P3-4, decided 2026-10-02):** every financial route requires `aal2`. This proves MFA was completed **when the token was issued**. It says nothing about whether the session is still valid later.
- **R-REVOKE (new; adopted by the owner as D0, 2026-10-09).** Authoritative wording:

  > 注销或账户恢复导致 session 撤销成功后，所有财务读写请求在新的授权检查中必须拒绝该 session 的旧 token，即使它尚未过期。已经通过检查的在途请求可能完成。检查失败或不可用时，不返回财务数据。

  In English: once a sign-out or account recovery has successfully revoked a session, every financial read or write request must reject that session's old tokens at a **new** authorization check, even if they have not expired. In-flight requests that already passed their check may complete. If the check fails or is unavailable, no financial data is returned.
  - Basis: F2. After the full recovery, an attacker's `aal2` access token still passed stateless verification with 3578 s left [M]. D0 records that access during the token's remaining lifetime is not accepted.
  - R-REVOKE is a new requirement. It does not follow from P3-4.
- **The 600-s lifetime is extra protection.** It bounds what stateless checks trust (Next.js page rendering) and limits damage if a route ever misses the check. C works without it.

### 2.2 Facts

- [M] An issued token still passes stateless verification after a global sign-out and after the revised recovery. `GET /auth/v1/user` rejects the same token with `403 session_not_found`.
- [M] `auth.sessions` holds one row per session, with an `aal` column. A password change and a global sign-out both delete the user's sessions (revocation-b).
- [D] [Sessions guide](https://supabase.com/docs/guides/auth/sessions):
  - `session_id` is the primary key of `auth.sessions`;
  - checking that row exists is the documented way to stop a token after sign-out;
  - "Most applications rarely need such strong guarantees. Consider adjusting the JWT expiry time";
  - do not go below 5 minutes; tokens are usually 5 minutes to 1 hour;
  - session time-boxes and inactivity timeouts are Pro only;
  - proactive client refresh is part of the design.
- [D] [Signing keys](https://supabase.com/docs/guides/auth/signing-keys): asymmetric validation is local and keeps the Auth server out of the hot path.
- [D] [Rate limits](https://supabase.com/docs/guides/auth/rate-limits): token refresh and MFA challenge/verify are limited per IP, with token-bucket bursts of 30. The exact per-hour numbers for this project are 未核实 (dashboard). `GET /auth/v1/user` is listed only for e-mail updates.
- [D] [Lint 0028](https://supabase.com/docs/guides/observability/advisors?queryGroups=lint&lint=0028_anon_security_definer_function_executable): "the Postgres default for new functions is `EXECUTE` to `PUBLIC`", and Supabase also grants default privileges for new functions to `anon`, `authenticated` and `service_role`. A `SECURITY DEFINER` function bypasses RLS with its owner's rights.
- [D] [PostgreSQL transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html): under Read Committed each statement sees a snapshot taken when it starts.
- [D] [SSR client guide](https://supabase.com/docs/guides/auth/server-side/creating-a-client):
  - the middleware/proxy refreshes with `getClaims()` and writes cookies to both `request.cookies` (for Server Components) and `response.cookies` (for the browser);
  - `setAll` also passes cache headers that must be applied to the response;
  - never trust `getSession()` in server code.
  - Current examples use Next.js 16 `proxy.ts`. This probe pins Next.js 15.5.24 like the product, where the file is `middleware.ts`.
- 未核实: whether the access-token expiry is editable on this Free project (S0).

### 2.3 Options

| Option | Meets R-MFA | Meets R-REVOKE | Per-request cost | Notes |
| --- | --- | --- | --- | --- |
| **A.** Stateless, 1 h (today) | yes | **no**: up to 3600 s + 30 s | none | F2 |
| **B.** Stateless, 600-s expiry | yes | **no**: up to 600 s + 30 s | none | Useful as an extra layer |
| **C.** Database session check on every financial route (with B) | yes | **yes**, within §2.4 | one indexed lookup on the route's own connection | Reads Supabase-internal `auth.sessions` through one function |
| **D.** Auth API check (`GET /auth/v1/user`) on every financial route (with B) | yes | **yes**, within §2.4 | one HTTPS call to Supabase Auth | Auth server in the hot path; endpoint limits undocumented |
| **E.** C for mutations only | yes | **no** for reads | lower | — |

### 2.4 The exact revocation guarantee (C and D)

> Once a revoking action (sign-out, password change, recovery) has **committed** in Supabase Auth, every financial request whose session check reads a database snapshot taken **after** that commit is rejected with `401 session revoked`. A request that already passed its check may still complete.

- This limit comes from PostgreSQL snapshot semantics. Running the check and the data read in one transaction does **not** remove the race between them.
- The probe never caches a positive result (`alive = true`). Every request runs the check.
- Proof uses the **same unexpired token**: 200 before the revocation, the revoking call succeeds, 401 on the first request after it, with `seconds_until_exp` recorded above 120 s. This keeps natural expiry from being counted as revocation (§5.2, D12–D13).

### 2.5 Recommendation

**If D0 is accepted, choose C, with B as an extra layer. Fallback: D.**

Why C:
- R-REVOKE covers reads, so B alone and E are out.
- One owner means a handful of requests; the cost is one query on a connection the route needs anyway.
- It keeps the Auth server out of the request path [D].
- It fails closed (§3, unit 1).

Why D only as fallback: it adds an HTTPS call to Auth on every request and ties the API's availability to Auth's. Use D if the S1 privilege checks fail, or if C proves unreliable in §5.3.

If D0 is **not** accepted, B alone meets R-MFA, and A5 reduces to choosing the token lifetime.

### 2.6 Session function and its privileges (C)

Migration `m5_auth_probe`, applied in **one transaction**:

```sql
begin;
create role pft_m5_authprobe login nosuperuser nocreatedb nocreaterole noreplication nobypassrls
  connection limit 4;                                  -- no password; the owner sets it (S2)
alter role pft_m5_authprobe set default_transaction_read_only = on;
grant usage on schema pft_m5_probe to pft_m5_authprobe;
grant select on pft_m5_probe.identity to pft_m5_authprobe;
create function pft_m5_probe.owner_session_alive(p_session uuid, p_owner uuid)
returns boolean language sql stable security definer set search_path = ''
as $$ select exists (select 1 from auth.sessions s
                     where s.id = p_session and s.user_id = p_owner and s.aal = 'aal2'
                       and (s.not_after is null or s.not_after > now())) $$;
revoke all on function pft_m5_probe.owner_session_alive(uuid, uuid)
  from public, anon, authenticated, service_role;
grant execute on function pft_m5_probe.owner_session_alive(uuid, uuid) to pft_m5_authprobe;
commit;
```

**S1 acceptance — read-only SQL right after the migration. Any failure means roll back and switch to the D fallback:**
- `has_function_privilege(<role>, 'pft_m5_probe.owner_session_alive(uuid,uuid)', 'EXECUTE')` is **true** only for `pft_m5_authprobe`, the owner role, and platform superuser roles (such as `supabase_admin`), which bypass privilege checks by definition. It is **false** for:
  - `anon`, `authenticated`, `service_role`;
  - `pft_m5_reader`, `pft_m5_jobs`, `pft_backup`;
  - a role holding only the `PUBLIC` grants.
- `pft_m5_authprobe` has no `SELECT` on `auth.sessions` and no `USAGE` on schema `auth`.
- The function is `SECURITY DEFINER`, its `proconfig` contains `search_path=""`, and its owner is the migration role. The owner's ability to read `auth.sessions` is proven by one call: as the probe role, with a random UUID, it returns `false` without an error.
- The security advisor shows no 0028/0029 finding for the function.

The local PostgreSQL integration test (§7) proves the same privilege rules before anything touches the cloud. Mocks cannot prove privileges.

## 3. Probe architecture

```
Owner browser ──HTTPS (Vercel login gate)──▶ auth-web preview (Next.js 15.5.24 + @supabase/ssr)
 │  /login: password → TOTP challenge/verify → aal2 cookies   middleware.ts: getClaims(); cookies → request+response
 │  /probe: server component getClaims(); not aal2 → /login   /api/pft/probe/whoami: same-origin route handler
 └──▶ Supabase Auth (synthetic)                                       │ Bearer <access token> + bypass header
                                                                      ▼
                                   auth-api preview (FastAPI, Python 3.12), mode db | auth
                                   owner_request context: JWT → session_id → connection → session check
                                   GET /probe/whoami → identity read on the same connection
```

Units:

1. **`experiments/m5_cloud/auth_api_probe.py`** — FastAPI app, staged as `main.py`.
   - **Settings:** pinned project ref, owner `sub`, Vercel project name, database host and role, and the mode (`M5_SESSION_CHECK=db|auth`, set per deployment). Startup refuses Plaid, Fernet or Supabase secret-key variables.
   - **`owner_request` dependency.** An async context dependency that owns the connection; every exit path releases it.
     1. Verify the JWT with `OwnerTokenVerifier`.
        - Signature or claim failure: 401/403, **no connection opened**.
        - JWKS fetch failure: **503** `auth keys unavailable`.
     2. Require `session_id` to be present and a canonical UUID; otherwise 401 `session id required`. The verifier does not check this today (`auth_probe.py` requires only `exp/iat/iss/aud/sub`).
     3. Open a connection.
        - `db` mode: SQLAlchemy `NullPool` engine, connect timeout 5 s, `statement_timeout` 2 s, set per transaction.
        - `auth` mode: `GET /auth/v1/user` with a 3-s timeout.
     4. Run the session check. `false` or Auth `403 session_not_found` returns **401** `session revoked`. A database or Auth error or timeout returns **503** `session check unavailable`, and no data is returned. The other mode is never tried as a fallback (K3).
     5. Yield `{claims, connection, request_id}` to the route. The route reads data on that connection. The connection is closed on success, error and cancellation alike.
     - Session results are never cached.
   - **Routes:**
     - `GET /probe/whoami`: identity read plus non-secret fields: `aal`, `iat`, `exp`, `seconds_until_exp`, and a timing breakdown (connection acquire, session check, data query, total).
     - `GET /probe/ping`: no auth, constant body.
     - No docs or OpenAPI routes. Everything is `Cache-Control: private, no-store`.
   - **Per-request diagnostics** on every response, including rejections (no secrets): `x-probe-request-id`, `x-probe-instance`, `x-probe-db-connections`, `x-probe-session-checks`, `x-probe-data-queries`. Per-instance totals are not used, because scaling would mix them.
2. **`experiments/m5_cloud/auth_web_probe/`** — minimal Next.js app with its own `package.json` and lockfile.
   - Pinned versions: `next` 15.5.24 and `react` 19.2.8; exact `@supabase/ssr` and `@supabase/supabase-js` pins chosen at plan time from official docs.
   - **`middleware.ts`** follows the official `updateSession` pattern:
     - `getClaims()` immediately after creating the client;
     - cookies written to both request and response;
     - `setAll` cache headers applied to the response;
     - a matcher that excludes static files.
     - It adds a non-secret `x-probe-mw-refresh: 1` response header **only when `setAll` wrote Auth cookies**, which is the evidence of a server-side refresh.
   - **`app/api/pft/probe/whoami/route.ts`**:
     - calls `getClaims()`; with no valid `aal2` claims it returns 401/403 **without calling upstream**;
     - takes the Bearer from the validated session and delegates to `forward.mjs`.
   - **`forward.mjs` (pure, tested with `node:test`):**
     - pinned HTTPS upstream; no redirects; browser cookies never forwarded; upstream `Set-Cookie` and redirects never passed back; timeout;
     - status mapping: **200 → body passed through**, **401/403 → passed through with the reason**, **503 → 503**, anything else or a network error → **502**;
     - copies `x-probe-request-id` so proxy and API records can be matched;
     - `private, no-store` on every response.
   - Only the public project URL and the publishable key appear under `NEXT_PUBLIC_`. The page is a throwaway test screen: no product UI change, so product responsive QA does not apply.
3. **`experiments/m5_cloud/auth_api_matrix.py`** — owner-run TTY script for the deployed tier (§5.2) and the A5 samples (§5.3).
   - Subcommands `matrix`, `samples` and `cleanup`.
   - It refuses an existing `--out` file. Evidence holds statuses, reasons, request IDs and timings only.
4. **`scripts/pft_m5_stage_auth_probe.py`** — stages the upload directories.
   - Writes `SHA256SUMS`, which records the hash of the deployed `auth_probe.py` so it can be compared with the tested file.
   - Never copies env or secret files. Follows the pattern of `pft_m5_stage_cron_bundle.py`.
5. **Migrations** `m5_auth_probe` (§2.6) and `m5_auth_probe_teardown` (§6).

**New Vercel projects:** `pft-m5-auth-web-20261009` and `pft-m5-auth-api-20261009`. The API project gets three preview deployments:
- `db` mode;
- `auth` mode;
- `db` mode with a deliberately wrong owner `sub`, for D16.

The mode and the wrong `sub` are non-secret runtime variables set at deploy time.

## 4. Secrets and who handles them

| Secret | Created by | Stored | Seen by the agent? |
| --- | --- | --- | --- |
| Owner password, TOTP | owner | owner's password manager and authenticator | no |
| `pft_m5_authprobe` password | owner | role, via SQL editor; API project preview env, via `vercel env add` from stdin | no |
| API automation-bypass value | owner, in Vercel project settings | web project server-only env; typed into the matrix script with `read -rs` | no |
| `sb_secret` key (temporary non-owner user, D10) | already exists | typed into the matrix script with `read -rs` only | no |
| Access and refresh tokens | Supabase Auth | browser cookies; matrix-script memory | no; evidence holds statuses only |

The agent may stage files and run `vercel deploy` of a staged directory as a **preview**, after approval. It never reads environment values. Production deployments stay denied by the user-level rules.

## 5. Acceptance criteria and measurements

### 5.1 A2 — browser path (owner; 300-s tokens from S2)

| # | Step | Expected evidence |
| --- | --- | --- |
| B1 | Open `/probe` without a session | redirect to `/login`. A direct request to the route returns 401; no upstream request ID appears |
| B2 | Password sign-in | `aal1`; TOTP screen; no data request |
| B3 | TOTP verify | `aal2`; `/probe`; whoami 200 with a request ID |
| B4 | **Browser auto-refresh:** keep the tab open across at least one expiry and fetch periodically | whoami stays 200; `iat` changes. Counted as evidence of the browser client's proactive refresh only, **not** of middleware |
| B5 | **Middleware refresh:** close every probe tab, so no browser client can refresh; wait at least 6 minutes, which is longer than one 300-s token lifetime; open `/probe` directly | response has `x-probe-mw-refresh: 1`; the server-rendered claims show a new `iat`; whoami 200. No browser client was running, so the refresh happened in middleware |
| B6 | Second request after B5 | 200 with no `x-probe-mw-refresh` header: the browser stored the new cookie |
| B7 | **Concurrent refresh:** after another expiry with tabs closed, open two probe tabs at the same moment | both 200. A third request afterwards is 200, so the session was not ended. The documented 10-s reuse interval [D] is the expected reason |
| B8 | Global sign-out | Cookies cleared and `/probe` → `/login`. **Back** may show a page restored from the browser's back-forward cache, but nothing new is fetched (its whoami returns 401). **Reload** → `/login`. The route returns 401 |

### 5.2 A3 — negative coverage at two evidence tiers

**Tier L — local, trusted test key.** These are unit tests with an injected test JWKS. They prove **each rule individually**, and the deployed verifier has **no test-key input**:
- missing header, non-Bearer, malformed;
- `alg` none, HS256, RS256; unknown `kid`, including the 60-s refetch limit; bad signature;
- wrong `iss`, wrong `aud`; expired beyond the 30-s leeway; `nbf` in the future; missing `iat`;
- `sub` other than the owner; `is_anonymous` true or missing; `aal1`; missing or malformed `session_id`;
- JWKS fetch failure → 503;
- session check `false` → 401; session-check error or timeout → 503;
- no connection opened before the JWT passes.

**Tier D — deployed, real trust boundary.** Direct requests to the API use the bypass header.

| # | Request | Expected | What it proves |
| --- | --- | --- | --- |
| D1 | no `Authorization` | 401 | |
| D2 | non-Bearer scheme | 401 | |
| D3 | malformed JWT | 401 | |
| D4 | `alg: none` | 401 | algorithm allowlist deployed |
| D5 | HS256 token | 401 | algorithm allowlist deployed |
| D6 | ES256 from a local key, unknown `kid` | 401 | keys come only from the pinned JWKS |
| D7 | real `kid`, forged signature | 401 | signature check against the real key |
| D8 | real token, tampered payload | 401 | **signature check only**; not evidence for any claim rule |
| D9 | real owner `aal1` | 403 `aal2 required` | `aal` rule with a real token |
| D10 | real non-owner token (temporary user) | 403 `not the owner` | `sub` rule with a real token |
| D11 | real owner `aal2` | 200 | |
| D12 | **same** unexpired token: 200 → global sign-out 204 → first request | 401 `session revoked` | R-REVOKE after sign-out (§2.4); `seconds_until_exp` above 120 recorded |
| D13 | **same** procedure across an admin password change | 401 `session revoked` | R-REVOKE after recovery |
| D14 | separate token held past `exp` + 30 s | 401 expired | natural expiry, kept apart from D12–D13 |
| D15 | unknown path | 404 | `x-probe-db-connections: 0` |
| D16 | real owner `aal2` against the **wrong-owner** deployment | 403 `not the owner` | the deployed verifier enforces the configured owner (plan §13: "changed owner setting") |

Through the proxy:

| # | Request | Expected |
| --- | --- | --- |
| P1 | no cookie | 401, no upstream request ID |
| P2 | forged cookie | 401 |
| P3 | `aal1` session (password only) | 403 from the route itself, no upstream request ID (an upstream `aal1` rejection is covered by D9) |
| P4 | owner `aal2` | 200 |
| P5 | after logout | 401 |

**Database counters, read per request from the diagnostics headers:**
- D1–D10, D14–D16, P1–P3, P5: `x-probe-db-connections: 0` at the API, or no API request at all.
- D12–D13: one session check and **no data query**.

**Evidence tiers in the record.** `iss`, `aud`, `nbf` and missing `iat` are proven at Tier L only. The deployed run shows two things:
1. the deployed `auth_probe.py` is byte-identical to the tested file (`SHA256SUMS`);
2. the real trust boundary works (D4–D16).

The acceptance record will label every rule with its tier.

### 5.3 A5 — strategy measurements

- **Separate runs per mode.** The `db` and `auth` deployments are sampled separately: at least 30 warm requests each, plus every cold request that occurs.
- **Timings per request:** connection acquire, session check (database query or Auth call), data query, total, and client wall time.
- **Reporting:** p50, p95 and maximum with n. A p95 from about 30 samples is a **sample statistic**, not a stable tail estimate, and will be labelled so.
- **Limits:** database connect 5 s, `statement_timeout` 2 s, Auth call 3 s.
- **Criteria:**
  - 0 timeouts, 0 5xx responses and 0 responses with status 429 across all samples;
  - D12–D13 pass in `db` mode, and repeated in `auth` mode.

## 6. Cloud steps and failure paths, each step approved separately

| Step | Kind | Who | What |
| --- | --- | --- | --- |
| S0 | read-only | agent and owner | Refresh limits; confirm Hobby/Free plans and project count. The owner reads whether the access-token expiry is editable, and its current value |
| S1 | state | agent, via Supabase MCP | Migration `m5_auth_probe` (§2.6), then the S1 privilege checks. On failure, roll back and switch to D |
| S2 | state | owner | Set the role password in the SQL editor. Set the access-token expiry to 300 s and note the previous value |
| S3 | state | owner, with agent preparing commands | Create the two Hobby projects. Set env from stdin; create the API automation bypass |
| S4 | state | agent | Deploy web plus the three API previews from the staged directories; record `SHA256SUMS` |
| S5 | measurement | owner | B1–B8, the D/P matrix and the A5 samples. Evidence to `docs/evidence/m5-YYYY-MM-DD/auth-probe/`, dated by the day S5 runs |
| S6 | state | owner | Set the access-token expiry to the D5 value; one more B4/B5 check |
| S7 | state | owner and agent | Teardown, below |

**Failure and cleanup paths:**
- **Temporary non-owner user:**
  - created with an `m5-nonowner-<uuid>@example.invalid` address and deleted in the script's `finally`;
  - if the script is interrupted, `auth_api_matrix.py cleanup` lists users through the admin API and deletes every address with that prefix;
  - S7 confirms `count(*) = 1` in `auth.users` (read-only SQL count).
- **Access-token expiry:** S2 records the previous value. If S5 or S6 does not finish, S7 sets the expiry to the D5 value. The final value is recorded either way.
- **Teardown migration `m5_auth_probe_teardown`:**
  1. revoke `EXECUTE`, schema `USAGE` and table `SELECT` from `pft_m5_authprobe`;
  2. terminate the role's open connections;
  3. drop the function, then the role;
  4. verify that neither the role nor the function exists and that no grants remain.
- **Vercel:** the owner removes the deployments, projects, env and bypass. The agent confirms the listing is empty.
- **Stop rule:** if any S-step fails midway, stop, record the state, and run only the cleanup items for what was created.

## 7. Testing before anything is deployed

- **Python unit tests** (offline) for `auth_api_probe`:
  - all Tier L rules;
  - the 503-vs-401 split;
  - connection release on success, error and cancellation;
  - `no-store` and diagnostics headers;
  - startup refusals.
  They reuse the ES256 helpers from `tests/test_m5_auth_probe.py`.
- **Local PostgreSQL integration test** (new opt-in `PFT_M5_AUTH_SYNTHETIC_TEST`, disposable PG16 on 55439):
  - Fixture: roles `anon`, `authenticated`, `service_role`, `pft_m5_authprobe` and an unrelated role; a minimal `auth.sessions` table with `id`, `user_id`, `aal`, `not_after`; then the **same** migration SQL file.
  - Assertions:
    - the probe role gets the correct boolean for each case: alive `aal2`, `aal1`, other user, `not_after` in the past, missing row, and a row deleted between two calls;
    - the probe role gets *permission denied* on a direct `SELECT` from `auth.sessions`;
    - every other role gets *permission denied* on `EXECUTE`.
  - **Connection release (K1):** the real FastAPI app runs in-process against the same cluster. After each scenario, `pg_stat_activity` must show **no** remaining connection for the probe role. Scenarios:
    - success;
    - JWT rejected (no connection opened at all);
    - session revoked;
    - session-check timeout, forced by a test-only function body that sleeps longer than `statement_timeout`;
    - an exception in the route after the check;
    - client cancellation mid-request.
  - **No caching (K1):** the same token is accepted, then rejected right after its session row is deleted, within one app instance.
  - The new opt-in must be added to `scripts/ci_backend_tests.py`, otherwise the CI runner rejects the inventory.
- **`node:test`** for `forward.mjs`: status mapping including 200, host pinning, no redirects, header hygiene, request-ID copy.
- **Local `next build`** of the probe app with dummy public env, and no secrets.
- **Offline dry run** of `auth_api_matrix.py` against a local uvicorn instance with a test JWKS and a fake session check. This is for the script's flow only; it does not replace Tier D.
- **`git diff --check`** and a secret-pattern scan, as before.

## 8. Decisions (owner, 2026-10-09)

| # | Decision | Outcome |
| --- | --- | --- |
| **D0** | Adopt **R-REVOKE** | **Adopted**, with the authoritative wording in §2.1 |
| D1 | A5 strategy | **C**, with B as an extra layer. D is the fallback |
| D2 | Vercel projects | **Two new projects.** The 2026-10-01 projects go to the R21 teardown |
| D3 | How the API is reached | **Protected previews.** Server-to-server and the matrix use the automation bypass. Testing the exposed production target moves to M7, like the P2-3 deviation for cron |
| D4 | Non-owner case D10 | **Temporary second user**, created and deleted by the script; cleanup command as backup. Sign-ups stay off |
| D5 | Final access-token expiry | **600 s.** 300 s only during the probe |

### 8.1 Implementation constraints (owner, 2026-10-09)

- **K1:** C never caches a "session alive" result. Function privileges **and connection release** are covered by integration tests against a real local PostgreSQL. Mocks are not enough (§7).
- **K2:** the 600-s lifetime is extra protection only. It never replaces the per-request revocation check.
- **K3:** D is a fallback, not a runtime path.
  - If C fails validation, the reason is recorded, and switching to D is a separate owner decision.
  - The API never downgrades silently at runtime: a failed or unavailable database check returns 503. It never retries through the Auth API.
  - The mode is fixed per deployment (`M5_SESSION_CHECK`).

## 9. Out of scope

- A4 key-rotation drill; A6 Data API off, RLS backstop and product roles; A7 route-capability registry, reader mode and Origin/CSRF.
- Integrating the check into `api/main.py` and the product Next.js app (M6). M6 also needs an integration test that fails if Supabase changes `auth.sessions`.
- Production, Plaid, and any public production-target exposure.

## 10. Unknowns and risks

- 未核实: whether the access-token expiry is editable on Free (S0). If it is not, Next.js page rendering keeps trusting tokens for up to 3600 s; the API window is still closed by C.
- 未核实: whether the migration role can own a `SECURITY DEFINER` function that reads `auth.sessions`. S1 checks this before anything else; on failure, D.
- `auth.sessions` is Supabase-internal. A schema change makes C fail closed with 503, not open.
- Next.js 15 `middleware.ts` vs. the docs' Next.js 16 `proxy.ts`: same `updateSession` logic. Versions and the exact pattern are fixed at plan time from official docs.
- B7 depends on the 10-s refresh-token reuse interval [D]. Tabs opened more than 10 s apart are not a concurrency test.
- Per-IP refresh limits: the Next.js server refreshes from Vercel egress IPs. Volume for one owner is tiny [E]; any 429 is recorded.
- Vercel login gate in the owner's browser: expected to work because the owner is signed in to Vercel [E].
