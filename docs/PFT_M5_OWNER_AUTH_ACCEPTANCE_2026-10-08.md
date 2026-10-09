# M5 owner-auth acceptance on the synthetic project — 2026-10-08

**Status: G6 is NOT passed. SERVERLESS_GO remains withheld.** Provider-level owner authentication on Supabase Free is now measured: sign-ups and anonymous sign-ins refused, password plus TOTP reaching `aal2`, refresh, global sign-out, and email-free admin recovery. Two gaps keep G6 open:

1. **Recovery is not yet safe.** Deleting the TOTP factor through the admin API did **not** end an existing session (finding F1).
2. **No application-integrated auth path has been measured.** That path is Next.js session → server route → FastAPI verification on Vercel.

Real path: owner's interactive terminal → Supabase Auth REST API of the synthetic project. Tokens were checked by the P3-2 verifier prototype (`experiments/m5_cloud/auth_probe.py`). Nothing was deployed. **No Production access, no Plaid call, no Vercel change.**

Legend: **[M]** measured in this run; **[E]** estimate or inference; **[D]** official documentation (checked 2026-10-08 unless stated).

All times are UTC (EDT + 4 h).

## 1. Setup

| Item | Value |
| --- | --- |
| Supabase project | `acyghoemtdrilsdszolq` (`pft-m5-synthetic-20261001`, Free) |
| Auth settings | Changed by the owner in the dashboard: sign-ups off, manual linking off, anonymous sign-ins off, TOTP enabled. At 21:52:24 and 21:52:54 the public `/auth/v1/settings` still returned `disable_signup: false`, with `cf-cache-status: DYNAMIC`, so not a cached value. After the owner saved the setting again, the negatives run at 21:54:36 recorded `disable_signup: true` [M]. Only the `email` provider is enabled [M]. |
| Owner user | One user, created by the owner in the dashboard. Before the run: email confirmed, password set, `email` identity only, not anonymous, 0 MFA factors, 0 sessions [M]. Source: read-only SQL **counts** through the Supabase MCP. No email, IP or token column was read. |
| JWKS | One key: `EC` / `P-256` / `ES256` / `sig`. No symmetric key published [M] (`auth_probe jwks`; same `kid` as the 2026-10-02 evidence). |
| Runner | `experiments/m5_cloud/auth_owner_flow.py`, run by the owner in their own TTY. The script refuses non-TTY stdin and writes the TOTP secret only to `/dev/tty`. Run from the isolated venv `~/code/pft-m5-remaining/.venv` (gitignored): Python 3.12.3, `PyJWT[crypto]==2.10.1` (`scripts/ci_requirements.txt`), `cryptography==41.0.7` (`api/requirements.txt`). `pip check` clean; `tests.test_m5_auth_probe` 10/10. |
| Verifier | `OwnerTokenVerifier`: ES256 only, keys only from the configured JWKS URL, `iss`, `aud=authenticated`, `exp`/`iat` required, `sub` must equal the owner, `aal2` required, `is_anonymous` must be false. The owner `sub` is taken from the sign-in response. |
| Admin capability (recover only) | The synthetic project's `sb_secret_…` key. The owner entered it with `read -rs` into a subshell, so it lived only in that process. |
| Secret handling | The agent never saw the password, the TOTP secret or codes, or the secret key. Evidence holds only status codes, error labels, claim names and booleans. All four files were scanned for JWT, `sb_secret`, e-mail, `otpauth`/`secret=` and token-field patterns: none found. |
| Script change before flow-2 | (1) The TOTP code is read **before** any challenge is created; attempt 1 below expired a challenge while the authenticator was being set up. (2) Added a wrong-code check on a fresh challenge. Checked by an offline dry run against a fake Auth API. |

## 2. Results

Evidence directory: [`evidence/m5-2026-10-08/owner-auth/`](evidence/m5-2026-10-08/owner-auth/). It is a new directory on purpose: `evidence/m5-2026-10-02/cloud/auth-negatives.json` is the **Cron S1 HMAC** evidence, and the earlier handoff command would have overwritten it.

### 2.1 negatives — 21:54:36 [M]

Evidence: [negatives.json](evidence/m5-2026-10-08/owner-auth/negatives.json).

| Check | Result |
| --- | --- |
| Settings | `disable_signup: true`, `anonymous_users: false` |
| Wrong password | `400 invalid_credentials` |
| Admin API (`GET /admin/users`) with the publishable key | `401 no_authorization` |
| Sign-up of a new address | `422 signup_disabled` |
| Anonymous sign-in | `422 anonymous_provider_disabled` |

Afterwards: still 1 user, 0 users created since the run, 0 anonymous, 0 sessions [M, SQL counts].

### 2.2 flow-1 — TOTP enrolment [M]

**Attempt 1 (21:57:36)** — results:

| Step | Result |
| --- | --- |
| Password sign-in | 200 |
| `aal1` token | refused, 403 `aal2 required` |
| Enrol | 200 |
| Challenge | 200 |
| Verify | `422 mfa_challenge_expired` |

What happened: the challenge was created before the code prompt, and the owner was still adding the secret to the authenticator.

- **Expired challenges are refused.**
- The evidence file was **overwritten by attempt 2**, which used the same `--out`. The values above were read by the agent at about 22:06, before the overwrite. The original file is not preserved.
- The unverified factor from attempt 1 no longer existed after attempt 2 verified its own factor: one factor, `verified`, created 22:07:32 [M]. That the platform removed it is an inference [E].

**Attempt 2 (22:07:20)** — evidence: [flow-1.json](evidence/m5-2026-10-08/owner-auth/flow-1.json).

| Check | Result |
| --- | --- |
| Password sign-in | 200 |
| `aal1` token through the verifier | refused, 403 `aal2 required` |
| TOTP enrol / challenge / verify | 200 / 200 / 200 (`totp_factors_before: 1`, the leftover from attempt 1) |
| `aal2` token through the verifier | accepted. `aal2`, lifetime 3600 s. Claims include `session_id` and `is_anonymous` (false, as the verifier requires) |
| Verified challenge reused with another code | `422 mfa_ip_address_mismatch` (see F4) |
| Refresh | 200. The refreshed token is still `aal2` and is accepted |
| Rotated refresh token reused at once | 200 (see F3) |
| Global sign-out | 204 |
| Refresh after sign-out | `400 refresh_token_not_found` |
| `GET /auth/v1/user` with the old access token | `403 session_not_found` |
| Stateless verification of the old access token | **still accepted** (see F2) |

### 2.3 recover — 22:11:48 [M]

Evidence: [recover.json](evidence/m5-2026-10-08/owner-auth/recover.json). This is the P3-3 recovery path: trusted machine, admin API, no e-mail.

| Check | Result |
| --- | --- |
| Sign-in with the current password (`aal1` session S) | 200 |
| Verified TOTP factor present | true |
| Admin `DELETE /admin/users/{id}/factors/{factor}` | 200 |
| **Refresh of session S after the factor deletion** | **200: S survived** (F1) |
| Admin `PUT /admin/users/{id}` with a new password | 200 |
| Old password | 400 |
| New password | 200 |
| Verified TOTP factor afterwards | false |

No e-mail or SMTP was involved. The script ended with a global sign-out; afterwards 0 factors and 0 sessions remained [M, SQL counts].

### 2.4 flow-2 — re-enrolment after recovery, 22:15:48 [M]

Evidence: [flow-2.json](evidence/m5-2026-10-08/owner-auth/flow-2.json).

- Same results as flow-1 attempt 2, using the **new** password: sign-in 200, `aal1` refused, enrol / challenge / verify 200, `aal2` accepted, refresh 200 and still `aal2`, sign-out 204, refresh after sign-out 400, `/user` 403, stateless check still accepted.
- **A wrong code on a fresh challenge: `422 mfa_verification_failed`.**
- Rotated refresh token reused at once: 200.
- Verified challenge reused: `422 mfa_ip_address_mismatch`.

### 2.5 Final state — about 22:18 [M]

- 1 user, with **1 verified TOTP factor** created 22:16:05.
- 2 challenges: the wrong-code one and the real one.
- 0 sessions, 0 live refresh tokens.
- Sign-ups disabled.

The owner's authenticator holds only the flow-2 entry; earlier entries are void.

## 3. Findings

**F1 — Admin factor deletion did not end an existing session. Security; blocks the P3-3 recovery procedure.**

- Observed: session S, a password-only `aal1` session, refreshed successfully **after** the verified factor was deleted [M, n = 1].
- The JavaScript reference for `auth.admin.mfa.deleteFactor` says: "This will log the user out of all active sessions if the deleted factor was verified" [D, [reference](https://supabase.com/docs/reference/javascript/auth-admin-deletefactor)]. The measurement contradicts this, at least for an `aal1` session.
- Not measured: whether the admin password change ends existing sessions. The script's final global sign-out removed everything before that could be checked.

Consequence in a compromise scenario:
1. An attacker who phished the password holds an `aal1` session.
2. The owner runs the current recovery (delete the factor, then reset the password).
3. The attacker's session survives. With no verified factor left, it can enrol the attacker's own TOTP and reach `aal2` [E].

An attacker who already held an `aal2` session keeps it until revoked. Its access tokens stay valid until `exp` (F2).

**Proposed recovery order** (to be measured, not yet adopted):
1. Set a new password with the admin API.
2. Sign in with the new password, then call `POST /logout?scope=global`. This revokes every session's refresh tokens. The admin `signOut` needs the user's own JWT; there is no revoke-by-user-id call [D, [admin signOut](https://supabase.com/docs/reference/javascript/auth-admin-signout)].
3. List **all** factors, verified and unverified, and delete each one. The current script deletes only the first verified factor, so a factor enrolled by an attacker could remain.
4. Sign in again and re-enrol TOTP (`flow`).

Proposed measurement "recover-v2":
- Keep a second "attacker" session A alive.
- Record whether A can still refresh after each step (password change, global sign-out, factor deletion).
- Confirm that A cannot enrol a factor afterwards.

**F2 — Issued access tokens outlive sign-out until `exp` (3600 s on this project).**

- [M]: stateless verification still accepted the old token after sign-out. [D]: "Access Tokens of revoked sessions remain valid until their expiry time" ([signing out](https://supabase.com/docs/guides/auth/signout)).
- `GET /auth/v1/user` did reject the same token (`403 session_not_found`) [M], so an online session check is available.
- Open decision for M6: shorten the JWT lifetime (design proposal 10–15 min; whether it can be set on Free is 未核实), add an online check, or both. An online check could cover mutations only or every financial route; its cost and rate limits are 未核实.
- F1 adds weight to this decision: after a recovery, a surviving `aal2` access token remains usable against a stateless FastAPI check for up to the JWT lifetime [E].

**F3 — Refresh-token reuse within the interval succeeds.** This is documented behaviour: "A refresh token can be used more than once within a defined reuse interval. By default this is 10 seconds" [D, [sessions](https://supabase.com/docs/guides/auth/sessions)]. Reuse outside that interval terminates the session [D]. Not a defect, but the application must not rely on refresh tokens being single-use within 10 s.

**F4 — Reusing a verified challenge returns `mfa_ip_address_mismatch`.**

- The documented meaning of that code is "The enrollment process for MFA factors must begin and end with the same IP address" [D, Auth error codes].
- Here the challenge was already verified, and only one client IP was recorded [M, `count(distinct ip_address) = 1`]. So the platform apparently uses this code for an already-verified challenge as well [E].
- The property that holds: a verified challenge cannot be reused. A wrong code is covered separately by flow-2 (`mfa_verification_failed`).

## 4. G6 assessment

**Proven at provider level, on Supabase Free, with features included on Free (no SMTP, no paid add-on)** [M]:
- Single owner: sign-ups and anonymous sign-ins refused; only the e-mail provider.
- Password sign-in yields `aal1`. TOTP enrolment, challenge and verification yield `aal2`. Wrong and expired codes are refused.
- Real project tokens pass the P3-2 verifier rules: ES256 key from the configured JWKS, `iss`, `aud`, `sub` pin, `aal2`, `is_anonymous`. An `aal1` token is refused with 403.
- Refresh keeps `aal2`. Global sign-out revokes refresh tokens; `/auth/v1/user` rejects the old access token.
- Without e-mail, the admin API can reset the password and remove the TOTP factor; the owner can then re-enrol.
- The publishable key cannot use the admin API.

**Not proven — G6 stays open:**

| # | Gap | Needed |
| --- | --- | --- |
| A1 | Recovery leaves sessions alive (F1); admin password change vs sessions unmeasured | Revise the recovery order; run recover-v2 on this project; update design §4 and the runbook |
| A2 | No app-integrated path: Next.js `@supabase/ssr` session with `getClaims()` refresh on a Vercel preview, a same-origin server route forwarding `Authorization: Bearer` to a pinned FastAPI upstream, and the verifier mounted as a FastAPI dependency | The M5 "minimal routing/Auth probe" (plan §12): measured login, refresh and logout **through the app** |
| A3 | Negative matrix against a **deployed** FastAPI (no, malformed, expired or not-yet-valid token; wrong `iss`/`aud`/`alg`; unknown `kid`; non-owner; `aal1`), direct and through the proxy. Today only the 10 unit tests with injected JWKS exist | Run on the probe deployment (plan §13 tests) |
| A4 | Key rotation / unknown-`kid` refetch against the real project | Rotation drill on the synthetic project |
| A5 | JWT lifetime and online session check (F2) | Owner decision; measure on the probe |
| A6 | Data API off, RLS backstop, revokes for `anon`/`authenticated`, reader/writer/jobs roles (design §7) | Synthetic-project configuration and checks |
| A7 | Route-capability registry, reader mode, Origin/CSRF, CSP, `private, no-store`, logout state clearing | M6 implementation and tests (plan §13.2–13.3) |

A1–A3 are needed before G6 can count as viable owner authentication. A4–A7 can follow in M6/M7 as the plan places them, unless the owner decides otherwise.

## 5. Boundaries

- The owner did the dashboard changes and ran all Auth API calls from their own terminal.
- The agent prepared the venv, ran offline tests and a dry run, and made public read-only `GET` requests (`/settings`, JWKS) with the publishable key.
- The agent also ran read-only SQL **counts** on `auth.*` through the MCP. No e-mail, IP, token or factor-secret column was read.
- No Production access, no Plaid call, no Vercel or Supabase configuration change by the agent.
- SERVERLESS_GO is not asserted. G5, G7 and G8 also remain open ([inventory](PFT_M5_REMAINING_INVENTORY_2026-10-02.md)).
