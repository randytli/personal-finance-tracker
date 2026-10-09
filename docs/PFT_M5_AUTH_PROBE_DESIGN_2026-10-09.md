# M5 owner-auth probe and A5 session-revocation design — DRAFT 2026-10-09

**Status: draft for owner review.** This is design only. No code has been written, no cloud resource created, nothing deployed. Approving this draft permits writing the implementation plan; it does **not** permit any deployment. Every cloud step in §6 needs its own approval. SERVERLESS_GO stays withheld.

Inputs:
- [owner-auth acceptance](PFT_M5_OWNER_AUTH_ACCEPTANCE_2026-10-08.md) §3–§4, gaps A2, A3 and A5;
- [Auth design](PFT_M5_AUTH_DESIGN_2026-10-02.md), decisions P3-1 to P3-4;
- earlier M5 probes: [cloud run](PFT_M5_CLOUD_RUN_2026-10-01.md), [compatibility](PFT_M5_CLOUD_COMPATIBILITY_2026-10-01.md), `experiments/m5_cloud/runtime_probe.py`, `web_probe_handler.mjs`.

Legend: **[M]** measured earlier in M5; **[D]** official documentation, checked 2026-10-09; **[E]** inference; **未核实** not verified.

## 1. Purpose, constraints, success

**Given (from the owner and the record):**
- Close G6 gaps A2 (app-integrated path), A3 (negatives against a deployed FastAPI) and A5 (window for already-issued tokens).
- Synthetic project `acyghoemtdrilsdszolq` only. No Production, no Plaid, $0.
- The owner enters every secret in their own browser or terminal. The agent never sees passwords, TOTP material, the `sb_secret` key, DB passwords, Vercel bypass values or tokens.
- Each cloud change is approved on its own.

**Assumed — please correct if wrong:**
- The probe is disposable experiment code under `experiments/`, like the earlier M5 probes. The product app (`app/`, `api/main.py`) does not change; that integration is M6.
- One owner, using a desktop browser for the browser part.

**Success** means evidence for:
- **A2:** browser login → `aal2` → same-origin server route → FastAPI owner verification → a refresh across token expiry → logout.
- **A3:** the deployed negative matrix (§5.2) returns the expected 401/403 codes, and rejected requests never reach financial-like data.
- **A5:** a chosen strategy rejects a revoked session's token on the first request after revocation, at a measured, acceptable cost.

## 2. A5 — closing the issued-token window

### 2.1 Facts

- [M] An issued access token still passes stateless verification after a global sign-out, and after the whole revised recovery: 3578 s were left before `exp` (recover-v2).
- [M] `GET /auth/v1/user` rejects the same token with `403 session_not_found`.
- [M] `auth.sessions` holds one row per session, with an `aal` column (read-only SQL during the acceptance runs).
- [D] [Sessions guide](https://supabase.com/docs/guides/auth/sessions):
  - every access token has a `session_id` claim that is the primary key of `auth.sessions`;
  - to make sure a token cannot be used after sign-out, "check that the `session_id` claim in the JWT corresponds to a row in the `auth.sessions` table";
  - but "Most applications rarely need such strong guarantees. Consider adjusting the JWT expiry time … use this validation logic only for the most sensitive actions";
  - "We do not recommend going below 5 minutes for the JWT expiration time"; access tokens are "usually between 5 minutes and 1 hour";
  - a session ends when "the user changes their password or performs a security sensitive action". This matches revocation-b U1.
  - Session time-boxes and inactivity timeouts are **Pro only**.
- [D] [Signing keys](https://supabase.com/docs/guides/auth/signing-keys): asymmetric keys let JWT validation be "local and fast and does not involve Auth server". Keeping the Auth server out of the hot path helps performance and reliability.
- [D] [Rate limits](https://supabase.com/docs/guides/auth/rate-limits):
  - token refresh (`/auth/v1/token`) and MFA challenge/verify are limited per IP, using a token bucket with bursts of 30;
  - the exact per-hour numbers are rendered from config, so they are 未核实 for this project (visible in the dashboard);
  - `GET /auth/v1/user` is listed only for e-mail updates.
- 未核实: whether the access-token expiry is editable on this Free project. The owner reads it in the dashboard in step S0.

### 2.2 Options

| Option | Window after revocation | Per-request cost | New dependency | Assessment |
| --- | --- | --- | --- | --- |
| **A.** Stateless, 1 h (today) | up to 3600 s + 30 s leeway | none | none | Rejected: this is F2 |
| **B.** Stateless, short expiry (600 s) | up to 600 s + 30 s | none. One refresh per open tab every 10 min | none | The docs' first suggestion. A 10-minute window remains |
| **C.** B + **database session check** on every financial route | **0**: the next request after revocation fails | one indexed lookup on the connection the route already opens [E, to measure] | one `SECURITY DEFINER` function reading Supabase's internal `auth.sessions`; fails closed if that schema changes | Documented technique; negligible volume for one owner |
| **D.** B + **Auth API check** (`GET /auth/v1/user`) on every financial route | 0 | one extra HTTPS call to Supabase Auth per request [E, to measure] | Auth server in the hot path: availability coupling; limits for this endpoint not documented | Uses only the public API |
| **E.** B + C for mutations only | reads: up to 600 s | lower | as C | Conflicts with P3-4, which requires `aal2` on reads because reads are the sensitive part |

### 2.3 Recommendation: C (600-s tokens plus the database session check on every financial route)

Why C:
- P3-4 treats reads as sensitive, so the window must close for reads too. That rules out B alone and E.
- One owner means a handful of requests; the cost is one query on a connection the route needs anyway.
- It keeps the Auth server out of the request path [D], unlike D.
- It fails closed: if the function errors or the schema changes, the route returns an error rather than data.

Why keep B underneath: it limits the damage if a route ever misses the check, and it bounds what Next.js `getClaims()` trusts when rendering pages (stateless by design).

**Fallback: D**, if the migration role cannot create a function that reads `auth.sessions`, or if the probe shows C to be unreliable.

Check definition (probe version; the M6 version would live in the product schema):

```sql
-- Owned by the migration role, search_path pinned, EXECUTE granted only to the probe role.
create function pft_m5_probe.owner_session_alive(p_session uuid, p_owner uuid)
returns boolean language sql stable security definer set search_path = ''
as $$ select exists (select 1 from auth.sessions s
                     where s.id = p_session and s.user_id = p_owner and s.aal = 'aal2'
                       and (s.not_after is null or s.not_after > now())) $$;
```

FastAPI order of checks:
1. Verify the JWT with the P3-2 rules (signature from the pinned JWKS, `iss`, `aud`, `exp`, `sub == owner`, `aal2`, `is_anonymous`). A failure returns 401/403 **without opening a database connection**.
2. Only then call the function with `session_id` and the pinned owner `sub`, on the same connection and transaction as the route's read. A `false` result returns `401 session revoked`.

## 3. Probe architecture

```
Owner browser ──HTTPS (Vercel login gate)──▶ auth-web preview (Next.js 15.5.24 + @supabase/ssr)
 │  /login: password → TOTP challenge/verify → aal2 cookies    middleware.ts: getClaims() refreshes cookies
 │  /probe: server component, getClaims(); not aal2 → /login   /api/pft/probe/[op]: same-origin route handler
 └──▶ Supabase Auth (synthetic project)                                │ Bearer <access token> + bypass header
                                                                       ▼
                                   auth-api preview (FastAPI, Python 3.12)
                                   require_owner: P3-2 verifier → C session check
                                   GET /probe/whoami → reads pft_m5_probe.identity as pft_m5_authprobe
```

Units. Each one has one job and can be tested on its own:

1. **`experiments/m5_cloud/auth_api_probe.py`** — FastAPI app, staged as `main.py`.
   - Settings are pinned: project ref, owner `sub`, Vercel project name, database host and role. Startup refuses Plaid, Fernet or Supabase secret-key variables. Session-check mode is `db`.
   - Dependency `require_owner`: the existing `OwnerTokenVerifier`, then the session check. It returns the claims.
   - Routes:
     - `GET /probe/whoami`: reads the identity row and returns only non-secret fields: `aal`, `iat`, `exp`, session-check result and server timings. For measurement only, it also times an Auth-API check (option D) without enforcing it.
     - `GET /probe/ping`: no auth, constant body, for cold-start samples.
   - No docs or OpenAPI routes. Every response carries `Cache-Control: private, no-store`.
2. **`experiments/m5_cloud/auth_web_probe/`** — a minimal Next.js app with its own `package.json` and lockfile, so the repo root does not change.
   - Pinned versions: `next` 15.5.24 and `react` 19.2.8 (same as the product app); exact pins for `@supabase/ssr` and `@supabase/supabase-js`, chosen at plan time from official docs.
   - Files: `lib/supabase/{browser,server}.ts`, `middleware.ts`, `app/login/page.tsx`, `app/probe/page.tsx`, and `app/api/pft/probe/[op]/route.ts`. The route delegates to a pure `forward.mjs`.
   - Forwarding rules:
     - operation allowlist: `whoami` only;
     - pinned upstream host, HTTPS only, no redirects followed;
     - Bearer taken from the session that `getClaims()` has validated, plus the bypass header from server-only env;
     - browser cookies are never forwarded, and upstream cookies or redirects are never passed back;
     - upstream 401/403 pass through unchanged; anything else becomes 502;
     - responses carry `private, no-store`.
   - Only the public project URL and the publishable key appear under `NEXT_PUBLIC_`.
   - The page is a throwaway test screen. No product UI changes, so product responsive QA does not apply.
3. **`experiments/m5_cloud/auth_api_matrix.py`** — an owner-run TTY script, like `auth_owner_flow.py`, for A3 and the A5 timings. It refuses an existing `--out` file. Evidence holds only statuses, reasons and timings.
4. **`scripts/pft_m5_stage_auth_probe.py`** — stages the two upload directories with `SHA256SUMS` and never copies env or secret files. It follows the pattern of `pft_m5_stage_cron_bundle.py`.
5. **Synthetic migration `m5_auth_probe`**:
   - role `pft_m5_authprobe`: `LOGIN`, no password, read-only by default, connection limit 4;
   - `USAGE` on `pft_m5_probe` and `SELECT` on its identity table;
   - the §2.3 function, with `EXECUTE` for this role only.

   The owner sets the role password in the SQL editor, as was done for `pft_backup`.

**New Vercel projects (D2):** `pft-m5-auth-web-20261009` and `pft-m5-auth-api-20261009`. The 2026-10-01 reader and web projects carry service-capability gates and old environment variables. Reusing them would make it unclear which gate rejected a request.

## 4. Secrets and who handles them

| Secret | Created by | Stored | Seen by the agent? |
| --- | --- | --- | --- |
| Owner password, TOTP | owner | owner's password manager and authenticator | no |
| `pft_m5_authprobe` password | owner | role, via SQL editor; API project preview env, via `vercel env add` from stdin | no |
| API automation-bypass value | owner, in Vercel project settings | web project server-only env; typed into the matrix script with `read -rs` | no |
| `sb_secret` key (temporary non-owner user, §5.2 case 10) | already exists | typed into the matrix script with `read -rs` only | no |
| Access and refresh tokens | Supabase Auth | browser cookies; matrix-script memory | no; evidence holds statuses only |

The agent may stage files and run `vercel deploy` of a staged directory as a **preview**, after approval. It never reads environment values. Production deployments stay denied by the user-level rules.

## 5. Acceptance criteria and measurements

### 5.1 A2 — browser path (owner)

| Step | Expected |
| --- | --- |
| Open `/probe` without a session | redirect to `/login`; no request reaches the route handler or the API |
| Password sign-in | `aal1`; the page asks for TOTP and loads no data |
| TOTP verify | `aal2`; redirect to `/probe` |
| "Fetch whoami" | 200 through the same-origin route; shows `aal2`, `session_check: alive` and timings, no tokens |
| Leave the tab open past `exp` (300-s tokens in S2), then fetch again | `middleware.ts` refreshes the cookies; 200; `iat` has changed |
| Sign out (global) | cookies cleared; `/probe` redirects to `/login`; a direct call to the route returns 401 |

### 5.2 A3 — deployed negative matrix (owner-run script, direct to the API with the bypass header)

| # | Request | Expected |
| --- | --- | --- |
| 1 | no `Authorization` | 401 |
| 2 | non-Bearer scheme | 401 |
| 3 | malformed JWT | 401 |
| 4 | `alg: none` | 401 |
| 5 | HS256 token | 401 |
| 6 | ES256 signed by a local key, unknown `kid` | 401 |
| 7 | real `kid`, forged signature | 401 |
| 8 | real token, tampered payload | 401 |
| 9 | real owner `aal1` token | 403 `aal2 required` |
| 10 | real non-owner token (temporary user created and deleted by the script with the admin API; sign-ups stay off) | 403 `not the owner` |
| 11 | real owner `aal2` token | 200 |
| 12 | owner `aal2` token replayed after a global sign-out | 401 `session revoked` (C). Baseline: stateless verification alone accepts it |
| 13 | owner `aal2` token replayed after an admin password change | 401 `session revoked` |
| 14 | owner token held past `exp` + 30 s (300-s tokens) | 401 expired |
| 15 | unknown path or operation | 404, no database access |

Through the proxy:

| # | Request | Expected |
| --- | --- | --- |
| 16 | `curl` without a session cookie | 401, no upstream call |
| 17 | forged session cookie | 401 |
| 18 | after logout | 401 |
| 19 | owner logged in | 200 |

**"No database access before authorization"** is proven by unit tests on the code structure: the connection is opened inside `require_owner`, only after the JWT passes. In the deployed run, the API reports per-instance counters:
- **database connections opened by requests rejected at JWT verification** (cases 1–10, 14, 15): must be 0;
- **session-revoked rejections** (cases 12–13): exactly one session-check query each and **no data query**.

### 5.3 A5 — strategy measurements

- **Revocation:** cases 12 and 13 fail on the first request after the revoking action.
- **Cost:** server-side timing for C and for D (measured, not enforced). At least 30 warm samples per mode, plus the cold samples that occur. Report p50, p95 and maximum.
- **Rate limits:** 0 responses with status 429 during the whole run.
- **Refresh:** at least one refresh is observed with 300-s tokens. Then the owner sets the D5 value and one more refresh is checked.

## 6. Cloud steps, each approved separately

| Step | Kind | Who | What |
| --- | --- | --- | --- |
| S0 | read-only | agent and owner | Refresh Vercel and Supabase limits. Confirm the Hobby/Free plans and project count. The owner reads whether the access-token expiry is editable |
| S1 | state | agent, via Supabase MCP | Migration `m5_auth_probe` on the synthetic project. Verify the function can read `auth.sessions`; if it cannot, stop and switch to the D fallback |
| S2 | state | owner | Set the role password in the SQL editor; set the access-token expiry to 300 s |
| S3 | state | owner, with agent preparing commands | Create the two Hobby projects. Owner sets env from stdin and creates the API automation bypass |
| S4 | state | agent | Deploy both previews from the staged directories |
| S5 | measurement | owner | A2 browser run; A3/A5 matrix run; evidence to `docs/evidence/m5-YYYY-MM-DD/auth-probe/`, dated by the day S5 runs |
| S6 | state | owner | Set the access-token expiry to the D5 value; one more refresh check |
| S7 | state | owner and agent | Teardown: owner removes previews, projects, env and bypass; agent applies a migration that drops the function and role. The temporary user is already deleted by the script |

## 7. Testing before anything is deployed

- **Python unit tests** for `auth_api_probe`, using fake JWKS and a fake session check. They cover matrix cases 1–15, the rule that nothing touches the database before a valid JWT, the startup refusals, and the `no-store` header. They reuse the ES256 helpers from `tests/test_m5_auth_probe.py`, are offline, and do not change the CI opt-in inventory.
- **`node:test`** for `forward.mjs`: allowlist, host pinning, no redirects, header hygiene, status mapping.
- **Local `next build`** of the probe app with dummy public env, and no secrets.
- **Offline dry run** of the matrix script against a local uvicorn instance with fake JWKS.
- **`git diff --check`** and a secret-pattern scan, as before.

## 8. Decisions for the owner

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | A5 strategy | **C**: 600-s tokens plus the database session check on every financial route. Fallback D |
| D2 | Vercel projects | **Two new projects** (§3). The 2026-10-01 projects go to the R21 teardown |
| D3 | How the API is reached | **Protected previews.** Server-to-server and the matrix use the automation bypass. Testing the exposed production target moves to M7, like the P2-3 deviation for cron |
| D4 | Non-owner case 10 | **Temporary second user** created and deleted by the matrix script with the admin API. Sign-ups stay off |
| D5 | Final access-token expiry | **600 s.** 300 s only during the probe |

## 9. Out of scope

- A4 key-rotation drill; A6 Data API off, RLS backstop and product roles; A7 route-capability registry, reader mode and Origin/CSRF.
- Integrating the check into `api/main.py` and the product Next.js app (M6).
- Production, Plaid, and any public production-target exposure.

## 10. Unknowns and risks

- 未核实: whether the access-token expiry is editable on Free (S0). If it is not, B and C keep a 3600-s stateless window for Next.js pages, but C still closes the API window.
- 未核实: whether the migration role can own a `SECURITY DEFINER` function that reads `auth.sessions`. MCP SQL can read the table, but the role it runs as was not recorded. S1 checks this before anything else.
- `auth.sessions` is Supabase-internal. A schema change would make C fail closed (requests rejected), not fail open. M6 needs an integration test for this.
- The current `@supabase/ssr` guidance for Next.js 15 middleware and `getClaims()` is to be re-read from official docs at plan time, with versions pinned then.
- Per-IP limits on token refresh: the Next.js server refreshes from Vercel egress IPs. Volume for one owner is tiny [E]; S5 records any 429.
- Vercel login gate in the owner's browser: expected to work because the owner is signed in to Vercel [E].
