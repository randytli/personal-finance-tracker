# M5 owner authentication (Supabase Auth replacing Tailscale) — design only (2026-10-02)

**Status: design only; no code.** This does not close SERVERLESS_GO criterion G6. The plan requires measured login, refresh and logout plus negative tests on the synthetic project (plan §13.1–13.3). Nothing was configured on any provider. Doc facts were looked up on 2026-10-02.

Legend: **[D]** official documentation quote; **[E]** inference; **未核实** not verified; **[R]** repository fact.

## 1. Today's boundary (Tailscale, Phase 2 Core)

- **Reachability is the control.** The app is only reachable through `tailscale serve` from tailnet devices the owner admits. Funnel, router forwarding and public DB/API ports are forbidden (plan §8).
- **The app has no user authentication.** Financial routes use the configured `PLAID_PILOT_USER_ID` [R, `api/routes/*.py`].
- **`local_request_boundary`** (`api/main.py`) enforces exact `Host` values and an exact write `Origin`. It is defense in depth; the plan states "A Host/Origin check is not user authentication".
- **Secrets stay on the PC.** DB, Plaid secrets, Fernet key and backups never leave it. The DB has no published port.

## 2. Target boundary

```
Browser ──HTTPS──▶ Vercel Next.js (pages + server route handlers) ──Bearer JWT──▶ Vercel FastAPI (reader / writer)
   │                         │ getClaims() on every request                         │ verifies JWT via JWKS, sub == owner
   └──▶ Supabase Auth (login, refresh, TOTP MFA)                                     └──▶ Supabase Postgres via Supavisor (role-specific)
Supabase Cron ──signed HMAC──▶ Vercel jobs (no owner JWT; service capability, see cron design)
```

Rules:
- The browser never reaches financial SQL. Supabase JS is used **only for Auth**.
- The Supabase **Data API is turned off**: "With the Data API disabled, none of the auto-generated REST endpoints respond, regardless of grants or RLS" [D, [securing your API](https://supabase.com/docs/guides/api/securing-your-api)].
- FastAPI authorises every financial route itself. Next.js checks are for UX and refresh, not the security boundary (plan §13.1).

## 3. Threat model

| Asset | Where it lives in the cloud design |
| --- | --- |
| Financial history, overrides, statement evidence | Supabase Postgres |
| Plaid access tokens | Supabase, Fernet ciphertext. Fernet key in the Vercel **jobs** env only |
| Plaid client secret | Vercel jobs env only |
| Owner session (access + refresh token) | Browser cookies (§5) |
| DB role passwords | Vercel env (reader / writer / jobs), GitHub secret (backup role) |
| Backup private key | Offline, with the owner only (backup design §5) |
| Trigger HMAC key | Supabase Vault + Vercel jobs env |

| Adversary / entry point | Control |
| --- | --- |
| Anyone on the internet hitting the web app or **FastAPI directly** | JWT verification on every financial route, `sub == PFT_OWNER_AUTH_SUB`, deny-by-default route registry (plan §13.2). Direct-API negative tests are a release gate. |
| Attacker creating an account | Signups off, anonymous sign-ins off, no OAuth providers (§4). Even a stray account fails the `sub` pin. |
| Credential stuffing / phishing of the owner password | TOTP MFA required (`aal2`). "Basic Multi-Factor Auth" is Included on Free [D, [pricing](https://supabase.com/pricing)]. Phone MFA is a paid add-on [D] and not used. "Leaked password protection" is **not included** on Free [D], so use a long unique password. |
| XSS or compromised npm dependency in the web app | Can act as the owner while the page is open in either session model. With SDK cookies it can also **steal** the refresh token (§5). Mitigations: strict CSP, no `dangerouslySetInnerHTML`, lockfile review, `private, no-store`. |
| CSRF against cookie-authenticated Next.js handlers | `SameSite=Lax` cookies, an exact `Origin` check on every mutation (reuse `_origin` parsing from `local_request_boundary`), and a custom request header. No wildcard preview origins. |
| Stolen JWT | Valid until `exp`. "Non-expired access tokens will remain to be accepted" even after key rotation [D, [signing keys](https://supabase.com/docs/guides/auth/signing-keys)]. Default lifetime 1 h (§6). Sign-out removes the session rows, but issued access tokens stay valid until `exp` unless the server checks `session_id` (§6). |
| Forged JWT / algorithm confusion | Asymmetric project key, `alg` allowlist `ES256` only, keys only from the **configured** JWKS URL, never from token headers (`jku`/`x5u` ignored) (§6). |
| Supavisor endpoint (public internet, password auth) | Long random per-role passwords, `CERT_REQUIRED` + hostname verification [M5 compatibility pass], least-privilege roles (§7). Network restrictions "apply to all connection routes, whether pooled or direct" [D, [network restrictions](https://supabase.com/docs/guides/platform/network-restrictions)], but Free availability is 未核实, and Vercel has no static egress on Hobby [E]. Optional only. |
| Data API accidentally re-enabled | RLS on every app table with policies only for server roles. `anon` / `authenticated` have no grants or default privileges (§7). |
| Provider insider or provider compromise | Accepted risk of the cloud design. Tokens stay Fernet-encrypted and backups are encrypted to an offline key. |
| Leaked Vercel env / preview misconfiguration | Separate projects and roles. Reader has no Plaid secret or Fernet key (plan §13.3). Previews get synthetic credentials only. |
| Lost phone | TOTP on that phone. Recovery path in §4. Supabase dashboard can revoke sessions (未核实 for single-session revoke). |

## 4. Single-user account: no registration

**Dashboard settings**, quoted from [general configuration](https://supabase.com/docs/guides/auth/general-configuration) [D]:
- **Allow new users to sign up: off.** "If this config is disabled, only existing users can sign in."
- **Allow anonymous sign-ins: off** ("Allow anonymous users to be created").
- **Allow manual linking: off.** No social providers.
- **Confirm email: on.**
- Exact Site URL and redirect allowlist (production origin only, no wildcards). Previews never get production redirects.

**Owner provisioning:**
1. Create the single owner user once, from the dashboard, before signups are closed or via an admin invite.
2. Enrol TOTP.
3. Record its UUID as `PFT_OWNER_AUTH_SUB`.
4. FastAPI maps that subject to the **existing** `PLAID_PILOT_USER_ID` for queries and lock keys (plan §13.1). Existing Items and history keep their user ID.

**Defense in depth:** the `sub` pin means a second account cannot read data, even after a misconfiguration.

**Recovery without paid SMTP:**
- Default SMTP will "refuse to deliver messages to addresses that are not part of the project's team", sends "2 messages per hour", and is "best-effort only and intended for … non-production use cases" [D, [SMTP](https://supabase.com/docs/guides/auth/auth-smtp)].
- The owner *is* a team member, so reset mail to the owner address should deliver, but only best-effort [E].
- "Custom SMTP server" is Included on Free [D]. It needs a free SMTP sender, which is 未核实 and an owner choice.
- **Proposed primary recovery: no email at all.** The owner signs in to the Supabase dashboard (its own MFA), then from a trusted machine calls `auth.admin.updateUserById(<owner uuid>, { password })` with the project's secret/service-role key held only in that process. The docs show exactly this `password` example and state it "should only be called on a server. Never expose your `service_role` key in the browser" [D, [updateUserById](https://supabase.com/docs/reference/javascript/auth-admin-updateuserbyid), 2026-10-02]. Removing a lost TOTP factor through the admin API is 未核实.
- If the Auth user is recreated, update `PFT_OWNER_AUTH_SUB`. `PLAID_PILOT_USER_ID` stays unchanged (plan §16.1).
- **Decision P3-3.**

## 5. Next.js session validation

From [Supabase SSR for Next.js](https://supabase.com/docs/guides/auth/server-side/nextjs) [D]:
- "Use `getClaims` to protect pages and user data."
- "Never trust `supabase.auth.getSession()` inside server code such as Proxy. It reads the session out of the cookie without revalidating it."
- "The Proxy is responsible for: 1. Refreshing the Auth token by calling `supabase.auth.getClaims()`".

**Proposed model: SDK cookie session plus a same-origin server proxy.**
1. `@supabase/ssr` stores the session in cookies. The Next.js proxy/middleware calls `getClaims()` on each request to refresh, and returns the refreshed cookies.
2. Pages and server route handlers call `getClaims()`. An unauthenticated request is redirected to `/login` before any financial fetch. No protected request fires before the session is ready (plan §13.3 tests).
3. The four existing `/api/pft` rewrite families in `next.config.js` become **server route handlers**:
   - forward only allowlisted paths to a pinned FastAPI upstream;
   - attach `Authorization: Bearer <access token>`;
   - never forward arbitrary hosts, cookies or redirects. This is the pattern already proven by the M5 web probe.
4. Responses: `Cache-Control: private, no-store`. On logout or terminal auth failure, clear React state, edits and polling.

**Why not the full BFF** (opaque HttpOnly cookie, server-side encrypted refresh tokens in a session table), which the plan names as preferred candidate:
- It removes token theft by XSS, but **not** XSS acting as the owner.
- It adds a session table and role, an encryption key, CSRF tokens, serialised refresh, revocation and crash recovery. That is more security-critical code for one user.
- The plan explicitly allows the bearer/SDK model "if its XSS/token-exposure tradeoff is explicitly reviewed and accepted and FastAPI independently enforces owner authorization".
- **Decision P3-1.** Recommendation: the SDK cookie model with strict CSP, MFA and short JWT lifetime. Revisit the BFF if the app ever renders untrusted third-party content.

Note: Supabase's SSR cookies cannot simply be made HttpOnly while keeping browser refresh (feasibility pass, HttpOnly caveat).

## 6. FastAPI token verification

A new dependency is needed. Plan §13.1 says "Use a maintained Python JWT implementation". Proposal: **PyJWT** with its `PyJWKClient` (uses the already-pinned `cryptography`). Exact version to be pinned in M6; **decision P3-2**.

Verification rules, applied in one shared dependency on every financial route:

| Check | Rule |
| --- | --- |
| Key source | Only `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` from config [D, signing keys]. Ignore `jku`/`x5u`/`jwk` headers. |
| Key cache | In-process cache. On unknown `kid`, refetch at most once per 60 s, then fail closed. The provider edge caches JWKS "for 10 minutes" [D], so a revoked key can be accepted for up to ~10 min plus our cache [E]. |
| Algorithm | `ES256` only (asymmetric). Reject `HS256` and `none`. "Starting October 1, 2025, all *new projects* will use asymmetric JWTs by default" [official blog, [JWT signing keys](https://supabase.com/blog/jwt-signing-keys), 2026-10-02]; confirm the key type on the actual project. |
| `iss` | Exactly `https://<ref>.supabase.co/auth/v1` [D, [JWTs](https://supabase.com/docs/guides/auth/jwts)]. |
| `aud` | Exactly `authenticated` [D, [JWT fields](https://supabase.com/docs/guides/auth/jwt-fields)]. |
| `exp`, `iat` (`nbf` if present) | Required. Leeway ≤ 30 s. |
| `sub` | Must equal `PFT_OWNER_AUTH_SUB`. Never authorise by email, `role=authenticated` or a caller-supplied `user_id` (plan §13.1). |
| `aal` | Require `aal2` once TOTP is enrolled ("AAL2 … verified using at least one second factor" [D, [MFA](https://supabase.com/docs/guides/auth/auth-mfa)]). |
| `is_anonymous` | Must be false [D field]. |
| Lifetime | Default 1 h: "Most applications should use the default expiration time of 1 hour"; "Values below 5 minutes, and especially below 2 minutes, should not be used in most situations" [D, [sessions](https://supabase.com/docs/guides/auth/sessions), 2026-10-02]. Proposal: 10–15 min. Session time-boxes and inactivity timeouts are "only available on Pro Plans and up" [D], so not available here. |
| Online check | Sign-out removes sessions "from the database entirely" and validity can be checked by whether "the `session_id` claim in the JWT corresponds to a row in the `auth.sessions` table" [D, sessions]. Option: before mutations, check `session_id` in `auth.sessions` (needs a narrow SELECT grant; whether Supabase permits it for a custom role is 未核实) or call `GET /auth/v1/user`. Not proposed for reads. |

**Non-browser callers:**
- The scheduler uses the HMAC capability (cron design) and is a distinct service principal, not an owner JWT (plan §12.4).
- Reader mode rejects every mutation before domain code. Route-capability tests enumerate all registered routes (plan §13.2).

**Negative tests required by plan §13.3** (M6), each on direct FastAPI and through Next.js:
- no token, malformed token, expired, not yet valid;
- wrong `iss` / `aud` / `alg`, unknown `kid`;
- valid non-owner token;
- `aal1` when `aal2` is required;
- rotated key.

## 7. RLS and database roles

**RLS** is not the primary control: with the Data API off, no browser path reaches tables. It is still proposed as a backstop:
- Enable RLS on every app table.
- Add **role-scoped permissive policies only for server roles** (`TO pft_reader USING (true)` for SELECT, and so on).
- Revoke all from `anon` and `authenticated` on app schemas, sequences, functions and **default privileges**.
- If the Data API is ever re-enabled, those roles see nothing. Docs warn that exposed tables "without RLS can be accessed by any role with matching grants" [D].
- Server roles must not rely on BYPASSRLS. Whether Supabase lets `postgres` create BYPASSRLS roles is 未核实, so policies are the portable route.

| Role | Used by | Grants | Never |
| --- | --- | --- | --- |
| `pft_migrator` | Operator-run migration CLI only | Owns app objects; DDL | Runtime use; stored in Vercel |
| `pft_reader` | Vercel FastAPI, read-only mode | SELECT on app tables; **column grant on `items` excluding `access_token`** (plan §15.1); `default_transaction_read_only=on`; connection limit | Any write, TEMP, Plaid key |
| `pft_writer` | FastAPI read/write mode (M8d) | Reader grants, plus INSERT/UPDATE/DELETE on manual override/label/benefit tables and `sync_runtime_state` request fields (via a narrow function if needed) | Raw/normalized transaction writes, `access_token`, DDL |
| `pft_jobs` | Vercel jobs (one-shot tick) | Read/write on the financial tables that `sync_all` and `tick` touch, including `items.access_token`; INSERT/DELETE on `pft_ops.trigger_nonces`; advisory-lock functions | DDL, Auth schema |
| `pft_backup` | Backup runner | SELECT on all app tables including token ciphertext (the backup must be complete); **BYPASSRLS**, because pg_dump refuses RLS-protected tables otherwise and `--enable-row-security` could hide rows (backup design §7); INSERT on a `backup_runs` table; read-only default | Writes to financial tables, Plaid or Fernet key |
| `anon`, `authenticated` | Supabase Auth / Data API | Nothing on app schemas | — |
| `service_role` key | — | Not stored in any PFT project | — |

**Extra controls:**
- **Known issue, deferred by owner decision (2026-10-02) to Production configuration:** `REVOKE TEMP ON DATABASE postgres FROM PUBLIC`, plus explicit TEMP only where needed. This closes the recorded probe-role gap R16. Whether the managed `postgres` role can revoke it from PUBLIC is 未核实.
- Each role has its own password and connection limit, sized from the measured budget (feasibility: jobs peak 3 + observer).
- The existing DB-name, schema and identity sentinel checks still run for every writer (plan §15.1).

## 8. Security gained and lost versus Tailscale

| | Tailscale (today) | Supabase Auth on Vercel (proposed) |
| --- | --- | --- |
| Who can reach the app | Only enrolled owner devices on the tailnet; WireGuard device keys | Anyone on the internet can reach the login page, FastAPI, Auth endpoints and the Supavisor port |
| What an attacker needs | A device admitted to the tailnet (or the Tailscale account) | The owner's password **and** TOTP (or a live session) |
| Per-request user authentication | **None** (any tailnet device is the owner) | Every request carries a verified, owner-pinned JWT |
| MFA | Whatever protects the Tailscale account | TOTP in-app (`aal2`), plus MFA on Supabase, Vercel and GitHub accounts |
| Exposure to app bugs | A bug is reachable only from tailnet devices | **Any auth or route bug is internet-exposed**; direct-API tests become a release gate |
| XSS impact | Limited to tailnet sessions | Session theft usable from anywhere until the refresh token is revoked |
| Revocation | Remove device from tailnet: immediate | Refresh revoke is immediate; issued JWTs live until `exp` |
| Secrets location | Only the owner's PC | Spread across Vercel env, Supabase Vault and GitHub secrets: more accounts to protect |
| Least privilege in DB | One runtime DB role [E] | Separate reader / writer / jobs / backup roles; reader cannot see token ciphertext |
| Availability | PC must be on | Works with PC off; new dependency on Supabase Auth and Vercel availability |
| Audit trail | Local logs | Auth audit logs: "1 hour" retention on Free [D, pricing]; effectively none |
| Cost | $0 | $0 (Basic MFA and custom SMTP included on Free [D]) |

**Net [E]:** the cloud design is **safer against misuse by anyone who reaches the app**, because there is real authentication, MFA and least-privilege roles. It is **riskier in exposure**: public reachability, more secret holders, and every app-layer auth bug becomes internet-facing. The plan's rule stands: no public release until the direct-API negative tests and reader-capability tests pass (plan §13.3).

## 9. Decisions and approvals

**Status 2026-10-02: P3-1…P3-4 are pending the owner's review** (not approved). Options, recommendation, rationale and the cost of a wrong choice for each are in the [handoff decision list](M5_OVERNIGHT_HANDOFF_2026-10-02.md#决策清单p3-与-p4待-owner-审阅).

- **P3-1** Session model: SDK cookies + server proxy (recommended) or full BFF.
- **P3-2** Python JWT library: PyJWT (recommended), pinned in M6.
- **P3-3** Owner recovery path: dashboard admin reset as primary (recommended), or configure a free custom SMTP sender.
- **P3-4** Require `aal2` for all financial routes (recommended), or only for mutations.
- **Approval needed later** (synthetic project only): create the owner Auth user, disable signups, enrol TOTP, migrate to asymmetric keys, disable the Data API, create the roles above, and run the negative-test matrix.
