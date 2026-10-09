# M5 Owner-Auth Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the disposable owner-auth probe (FastAPI API, Next.js web, session-check SQL, owner-run matrix script, staging) and its local tests, so the gated cloud steps S0–S7 can produce the A2, A3 and A5 evidence for G6.

**Architecture:**
- **API** — FastAPI app `experiments/m5_cloud/auth_api_probe.py`. Each request runs the P3-2 verifier first, then checks `session_id`, then runs a per-request session check (the C function in Postgres, or the D Auth API, fixed per deployment), and only then reads the synthetic identity row on the same connection.
- **Web** — minimal Next.js 15.5.24 app written in JavaScript, with its own `package.json`. Its `middleware.js` refreshes the session; a same-origin route forwards a Bearer token to the pinned API preview.
- **Tests** — everything is proven locally before any cloud step: Tier L unit tests, real-PostgreSQL integration tests for privileges and connection release, `node:test` for forwarding, a local `next build`, and an offline end-to-end run of the owner script against fakes.

**Tech Stack:**
- Python 3.12, FastAPI 0.141.1, SQLAlchemy 2.0.52, asyncpg 0.31.0, PyJWT 2.10.1, httpx 0.28.1, cryptography 41.0.7, `unittest`.
- Node 22, Next.js 15.5.24, React 19.2.8, `@supabase/ssr` 0.12.7, `@supabase/supabase-js` 2.117.3, `node:test`.
- PostgreSQL 16 for the local tests; the cloud is Supabase Free (PG 17) and Vercel Hobby.

**Spec:** [`docs/PFT_M5_AUTH_PROBE_DESIGN_2026-10-09.md`](PFT_M5_AUTH_PROBE_DESIGN_2026-10-09.md) (r2, approved 2026-10-09: D0–D5, K1–K3). Read it before any task.

## Global Constraints

- **Scope:** synthetic Supabase project `acyghoemtdrilsdszolq` only. No Production, no Plaid. Vercel projects `pft-m5-auth-web-20261009` and `pft-m5-auth-api-20261009`, preview deployments only.
- **Branch:** work on `m5/g6-auth` in `~/code/pft-m5-remaining`. Never edit, switch or stash in another worktree (AGENTS.md).
- **Commits:** agents and subagents never run `git commit` or `git push`. Every "Checkpoint" step lists the files and a proposed message; the owner commits. The first push must be `git push -u origin m5/g6-auth`, because the branch currently tracks `origin/main`.
- **Secrets:** no password, TOTP material, `sb_secret_…` key, DB password, Vercel bypass value or token in the repository, logs, evidence or chat. Owner-run scripts read secrets with `getpass`.
- **Unchanged:** the product app — `app/`, `api/`, root `package.json`, root `tsconfig.json`, `next.config.js`.
- **Probe web app is JavaScript only (`.js`, `.mjs`).** The root `tsconfig.json` includes `**/*.ts` and `**/*.tsx`, and the root has no `@supabase/ssr`. TypeScript files in the probe would break root `tsc` and `next build` in CI.
- **Pins, exact:**
  - Python: `fastapi==0.141.1`, `SQLAlchemy==2.0.52`, `asyncpg==0.31.0`, `cryptography==41.0.7`, `PyJWT[crypto]==2.10.1`, `httpx==0.28.1`.
  - Node: `next` 15.5.24, `react` and `react-dom` 19.2.8, `@supabase/ssr` 0.12.7, `@supabase/supabase-js` 2.117.3.
- **R-REVOKE (D0):** "注销或账户恢复导致 session 撤销成功后，所有财务读写请求在新的授权检查中必须拒绝该 session 的旧 token，即使它尚未过期。已经通过检查的在途请求可能完成。检查失败或不可用时，不返回财务数据。"
- **K1:** never cache a "session alive" result. Privileges and connection release are covered by real-PostgreSQL integration tests.
- **K2:** the 600-s token lifetime never replaces the per-request check.
- **K3:** the D mode is a fallback fixed per deployment (`M5_SESSION_CHECK`). A failed or unavailable check returns 503 and never tries the other mode.
- **Status codes:**
  - 401: invalid token, missing or malformed `session_id`, revoked session;
  - 403: valid token but not the owner, anonymous, or `aal1`;
  - 503: JWKS fetch failure, session check unavailable, data unavailable.
- **Limits:** database connect timeout 5 s, `statement_timeout` 2 s, Auth API call 3 s, probe role connection limit 4. Token lifetime is 300 s during the probe and 600 s at the end (D5).
- **Gating:** each cloud step S0–S7 (Phase 2) needs its own owner approval at execution time. Production deployments and `vercel rm`/`env rm` are owner-only.

## Review Focus

These are the inputs most likely to bite that the spec only implies. Each has a test in the task that owns the code.

1. **Authorization header variants** — lowercase `bearer`, an oversized header, `Basic` → 401 with zero database connections (Task 3 `test_rejected_tokens_never_open_a_connection`; D2 in Task 7).
2. **The same token used concurrently, then revoked** — each request runs its own check; after the session row is deleted, the next request is 401 (Task 4 `test_same_token_concurrently_then_revoked`).
3. **Upstream answers 200 with a non-JSON body or a redirect** (for example, a Vercel login page) — the web route returns 502 and never passes HTML through (Task 5 `a 200 with a non-JSON body…`, `network errors, timeouts and redirects…`).
4. **Identifier format drift** — an uppercase owner UUID in config is rejected at startup; an uppercase or malformed `session_id` returns 401 (Task 3 `SettingsTests`, `test_rejected_tokens…`).
5. **Owner script rerun or interrupted** — an existing `--out` file is refused; the temporary non-owner user is always deleted, or can be removed with `cleanup`; `cleanup` never touches other users (Task 7 tests).

---

## Local verification environment (used by Tasks 1–9)

Run from the worktree root, `cd ~/code/pft-m5-remaining`.

Python environment, once (after Task 1 adds `httpx`):

```bash
.venv/bin/python -m pip install -r api/requirements.txt -r scripts/ci_requirements.txt
.venv/bin/python -m pip check
```

Disposable PostgreSQL 16 cluster on 55439, matching CI's SCRAM authentication and en-US collation:

```bash
T=${CLAUDE_JOB_DIR:-$(mktemp -d)}/tmp; mkdir -p "$T"; B=/usr/lib/postgresql/16/bin; D=$T/pg55439
echo synthetic > "$T/pw" && $B/initdb -D "$D" -U pft_ci --pwfile="$T/pw" -A scram-sha-256 \
  --locale-provider=icu --icu-locale=en-US --locale=C.UTF-8 >/dev/null && rm "$T/pw"
$B/pg_ctl -D "$D" -o "-p 55439 -k $D -c listen_addresses=127.0.0.1" -l "$D/log" start
PGPASSWORD=synthetic $B/createdb -h 127.0.0.1 -p 55439 -U pft_ci pft_ci_synthetic
export DATABASE_URL=postgresql+asyncpg://pft_ci:synthetic@127.0.0.1:55439/pft_ci_synthetic
export PFT_M5_AUTH_SYNTHETIC_TEST=1
```

Stop and remove the cluster at the end: `$B/pg_ctl -D "$D" stop -m fast && rm -rf "$D"`.

---

## Phase 1 — local code and tests (no cloud)

### Task 1: Test dependency and CI opt-in inventory

**Files:**
- Modify: `scripts/ci_requirements.txt`
- Modify: `scripts/ci_backend_tests.py` (the `OPT_INS` set)
- Modify: `tests/test_ci_backend_inventory.py` (`test_m5_inventory`)
- Modify: `docs/CI.md`, the two sentences named in Step 5

**Interfaces:**
- Produces: the flag `PFT_M5_AUTH_SYNTHETIC_TEST`, accepted by the CI inventory; `httpx==0.28.1` installed in CI and locally.

- [ ] **Step 1: Write the failing test.** In `tests/test_ci_backend_inventory.py`, replace `test_m5_inventory` with:

```python
    def test_m5_inventory(self):
        flags = REQUIRED_OPT_INS | {"PFT_" + name + "_SYNTHETIC_TEST"
                                    for name in ("M5_BACKUP", "M5_TRIGGER", "M5_AUTH")}
        self.assertEqual(self.discover(flags), flags)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_ci_backend_inventory -v`
Expected: `test_m5_inventory` ERROR, with `RuntimeError: Update CI opt-in inventory: {'PFT_M5_AUTH_SYNTHETIC_TEST'}`.

- [ ] **Step 3: Implement.** In `scripts/ci_backend_tests.py`, set:

```python
# M5 tests are present on integration branches before they reach main.
OPT_INS = REQUIRED_OPT_INS | {
    "PFT_M5_BACKUP_SYNTHETIC_TEST",
    "PFT_M5_TRIGGER_SYNTHETIC_TEST",
    "PFT_M5_AUTH_SYNTHETIC_TEST",
}
```

Replace `scripts/ci_requirements.txt` with:

```text
# CI-only dependency for the unmounted M5 owner-auth prototype tests.
PyJWT[crypto]==2.10.1
# CI-only ASGI/mock HTTP client for the M5 owner-auth probe tests; also staged into the probe bundle.
httpx==0.28.1
```

Then install: `.venv/bin/python -m pip install -r api/requirements.txt -r scripts/ci_requirements.txt && .venv/bin/python -m pip check`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_ci_backend_inventory -v`
Expected: 4 tests OK.

- [ ] **Step 5: Update `docs/CI.md`.**
  - Change "plus the two registered M5 switches when their tests are present" to "plus the three registered M5 switches when their tests are present".
  - Change "a CI-only pinned PyJWT dependency for the M5 backup/auth prototype tests" to "CI-only pinned PyJWT and httpx dependencies for the M5 backup/auth prototype and probe tests".

- [ ] **Step 6: Checkpoint (owner commits).** Files: the four above. Message: `Register the M5 owner-auth CI opt-in and pin httpx for probe tests`.

---

### Task 2: Session-check SQL, teardown SQL and PostgreSQL privilege tests

**Files:**
- Create: `experiments/m5_cloud/auth_session_probe.sql`
- Create: `experiments/m5_cloud/auth_session_probe_teardown.sql`
- Create: `tests/m5_auth_pg.py` (shared fixture; not a test module)
- Create: `tests/test_m5_auth_session_sql.py`

**Interfaces:**
- Produces:
  - SQL function `pft_m5_probe.owner_session_alive(p_session uuid, p_owner uuid) RETURNS boolean`;
  - role `pft_m5_authprobe`;
  - fixture `tests.m5_auth_pg`: `create_fixture() -> str` (database name), `drop_fixture(name)`, `admin_connect(database=None)`, `probe_connect(database)`, `probe_url(database) -> str`, plus the constants `MIGRATION`, `TEARDOWN`, `PROBE_ROLE`, `SUPABASE_ROLES`, `OTHER_ROLES`.

- [ ] **Step 1: Write the fixture** `tests/m5_auth_pg.py`:

```python
"""Disposable-PostgreSQL fixture for the M5 owner-auth session check (design §7, K1).

Used only by tests that opt in with the M5 owner-auth flag. Applies the real migration
file experiments/m5_cloud/auth_session_probe.sql to a fresh database on the loopback CI
cluster, next to a minimal stand-in for Supabase's auth.sessions table.
"""
import os
from pathlib import Path
import uuid

import asyncpg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "experiments" / "m5_cloud" / "auth_session_probe.sql"
TEARDOWN = ROOT / "experiments" / "m5_cloud" / "auth_session_probe_teardown.sql"
PROBE_ROLE = "pft_m5_authprobe"
PROBE_PASSWORD = "synthetic-probe"
SUPABASE_ROLES = ("anon", "authenticated", "service_role")
OTHER_ROLES = ("pft_m5_authtest_other",)
STAND_IN = """
CREATE SCHEMA auth;
CREATE TABLE auth.sessions (id uuid PRIMARY KEY, user_id uuid NOT NULL, aal text NOT NULL,
                            not_after timestamptz);
CREATE SCHEMA pft_m5_probe;
REVOKE ALL ON SCHEMA pft_m5_probe FROM PUBLIC;
CREATE TABLE pft_m5_probe.identity (singleton boolean PRIMARY KEY CHECK (singleton),
                                    project_ref text NOT NULL);
INSERT INTO pft_m5_probe.identity VALUES (true, 'acyghoemtdrilsdszolq');
REVOKE ALL ON pft_m5_probe.identity FROM PUBLIC;
"""


def _base():
    base = make_url(os.environ["DATABASE_URL"])
    if base.host not in {"127.0.0.1", "localhost"} or (base.port or 0) < 55000:
        raise RuntimeError("Requires the disposable loopback cluster")
    return base


async def admin_connect(database=None):
    base = _base()
    return await asyncpg.connect(user=base.username, password=base.password, host=base.host,
                                 port=base.port, database=database or base.database)


async def probe_connect(database):
    base = _base()
    return await asyncpg.connect(user=PROBE_ROLE, password=PROBE_PASSWORD, host=base.host,
                                 port=base.port, database=database)


def probe_url(database):
    return _base().set(drivername="postgresql+asyncpg", username=PROBE_ROLE,
                       password=PROBE_PASSWORD, database=database).render_as_string(hide_password=False)


async def _drop_roles(admin):
    for role in (PROBE_ROLE, *SUPABASE_ROLES, *OTHER_ROLES):
        await admin.execute(f"DROP ROLE IF EXISTS {role}")


async def create_fixture():
    name = "pft_m5_auth_" + uuid.uuid4().hex[:12]
    admin = await admin_connect()
    try:
        await _drop_roles(admin)
        await admin.execute(f'CREATE DATABASE "{name}"')
        for role in (*SUPABASE_ROLES, *OTHER_ROLES):
            await admin.execute(f"CREATE ROLE {role} NOLOGIN")
    finally:
        await admin.close()
    database = await admin_connect(name)
    try:
        await database.execute(STAND_IN)
        async with database.transaction():
            await database.execute(MIGRATION.read_text())
        await database.execute(f"ALTER ROLE {PROBE_ROLE} PASSWORD '{PROBE_PASSWORD}'")
    finally:
        await database.close()
    return name


async def drop_fixture(name):
    admin = await admin_connect()
    try:
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = $1 AND pid <> pg_backend_pid()", name)
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await _drop_roles(admin)
    finally:
        await admin.close()
```

- [ ] **Step 2: Write the failing tests** `tests/test_m5_auth_session_sql.py`:

```python
"""Privileges and semantics of pft_m5_probe.owner_session_alive (design §2.6, §7, K1).

Applies the real migration file to a fresh database on the disposable loopback cluster.
Needs PFT_M5_AUTH_SYNTHETIC_TEST=1.
"""
from datetime import datetime, timedelta, timezone
import os
import unittest
import uuid

OWNER = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"
SIGNATURE = "pft_m5_probe.owner_session_alive(uuid,uuid)"


@unittest.skipUnless(os.environ.get("PFT_M5_AUTH_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class SessionFunctionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests import m5_auth_pg
        self.pg = m5_auth_pg
        self.name = await m5_auth_pg.create_fixture()
        self.admin = await m5_auth_pg.admin_connect(self.name)
        self.probe = await m5_auth_pg.probe_connect(self.name)

    async def asyncTearDown(self):
        await self.probe.close()
        await self.admin.close()
        await self.pg.drop_fixture(self.name)

    async def add_session(self, *, user=OWNER, aal="aal2", not_after=None):
        session = uuid.uuid4()
        await self.admin.execute("INSERT INTO auth.sessions VALUES ($1, $2, $3, $4)",
                                 session, uuid.UUID(user), aal, not_after)
        return session

    async def alive(self, session, owner=OWNER):
        return await self.probe.fetchval("SELECT pft_m5_probe.owner_session_alive($1, $2)",
                                         session, uuid.UUID(owner))

    async def test_result_for_each_session_state(self):
        live = await self.add_session()
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        self.assertIs(await self.alive(live), True)
        self.assertIs(await self.alive(await self.add_session(not_after=future)), True)
        self.assertIs(await self.alive(await self.add_session(aal="aal1")), False)
        self.assertIs(await self.alive(await self.add_session(user=OTHER)), False)
        self.assertIs(await self.alive(await self.add_session(not_after=past)), False)
        self.assertIs(await self.alive(uuid.uuid4()), False)
        self.assertIs(await self.alive(live, owner=OTHER), False)

    async def test_deleted_row_is_seen_by_the_next_call(self):
        live = await self.add_session()
        self.assertIs(await self.alive(live), True)
        await self.admin.execute("DELETE FROM auth.sessions WHERE id = $1", live)
        self.assertIs(await self.alive(live), False)

    async def test_probe_role_cannot_read_sessions_directly(self):
        import asyncpg
        with self.assertRaises(asyncpg.InsufficientPrivilegeError):
            await self.probe.fetch("SELECT * FROM auth.sessions")
        self.assertFalse(await self.admin.fetchval(
            "SELECT has_schema_privilege('pft_m5_authprobe', 'auth', 'USAGE')"))

    async def test_only_the_probe_role_can_execute(self):
        import asyncpg
        self.assertTrue(await self.admin.fetchval(
            "SELECT has_function_privilege('pft_m5_authprobe', $1, 'EXECUTE')", SIGNATURE))
        for role in (*self.pg.SUPABASE_ROLES, *self.pg.OTHER_ROLES):
            with self.subTest(role):
                self.assertFalse(await self.admin.fetchval(
                    "SELECT has_function_privilege($1, $2, 'EXECUTE')", role, SIGNATURE))
                with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                    async with self.admin.transaction():
                        await self.admin.execute(f"SET LOCAL ROLE {role}")
                        await self.admin.fetchval("SELECT pft_m5_probe.owner_session_alive($1, $2)",
                                                  uuid.uuid4(), uuid.UUID(OWNER))

    async def test_function_and_role_are_pinned(self):
        function = await self.admin.fetchrow(
            "SELECT p.prosecdef, p.proconfig, p.provolatile FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'pft_m5_probe' AND p.proname = 'owner_session_alive'")
        self.assertEqual((function["prosecdef"], function["proconfig"], function["provolatile"]),
                         (True, ['search_path=""'], "s"))
        role = await self.admin.fetchrow(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolconnlimit "
            "FROM pg_roles WHERE rolname = 'pft_m5_authprobe'")
        self.assertEqual(tuple(role), (False, False, False, False, False, 4))
        self.assertEqual(await self.probe.fetchval("SHOW default_transaction_read_only"), "on")

    async def test_migration_refuses_to_run_twice(self):
        import asyncpg
        with self.assertRaisesRegex(asyncpg.RaiseError, "already exist"):
            async with self.admin.transaction():
                await self.admin.execute(self.pg.MIGRATION.read_text())

    async def test_failed_migration_leaves_nothing_behind(self):
        import asyncpg
        await self.probe.close()
        await self.admin.execute(self.pg.TEARDOWN.read_text())
        await self.admin.execute("DROP ROLE service_role")
        with self.assertRaises(asyncpg.UndefinedObjectError):
            async with self.admin.transaction():
                await self.admin.execute(self.pg.MIGRATION.read_text())
        self.assertFalse(await self.admin.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pft_m5_authprobe')"))
        self.assertIsNone(await self.admin.fetchval("SELECT to_regprocedure($1)", SIGNATURE))
        self.probe = await self.pg.admin_connect(self.name)

    async def test_teardown_removes_role_and_function(self):
        await self.probe.close()
        await self.admin.execute(self.pg.TEARDOWN.read_text())
        self.assertFalse(await self.admin.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pft_m5_authprobe')"))
        self.assertIsNone(await self.admin.fetchval("SELECT to_regprocedure($1)", SIGNATURE))
        self.probe = await self.pg.admin_connect(self.name)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run, with the local cluster up and the exports from the environment section: `.venv/bin/python -m unittest tests.test_m5_auth_session_sql -v`
Expected: every test ERRORs in `asyncSetUp` with `FileNotFoundError` for `auth_session_probe.sql`.

- [ ] **Step 4: Write the migration** `experiments/m5_cloud/auth_session_probe.sql`:

```sql
-- M5 owner-auth probe: probe role and session-check function (design §2.6, K1).
-- Synthetic project acyghoemtdrilsdszolq only. Apply as ONE migration (one transaction).
-- The role gets no password here; the owner sets it in the SQL editor (S2).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pft_m5_authprobe')
     OR to_regprocedure('pft_m5_probe.owner_session_alive(uuid,uuid)') IS NOT NULL THEN
    RAISE EXCEPTION 'm5_auth_probe objects already exist';
  END IF;
END $$;

CREATE ROLE pft_m5_authprobe LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 4;
ALTER ROLE pft_m5_authprobe SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA pft_m5_probe TO pft_m5_authprobe;
GRANT SELECT ON pft_m5_probe.identity TO pft_m5_authprobe;

CREATE FUNCTION pft_m5_probe.owner_session_alive(p_session uuid, p_owner uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
  SELECT EXISTS (SELECT 1 FROM auth.sessions s
                 WHERE s.id = p_session AND s.user_id = p_owner AND s.aal = 'aal2'
                   AND (s.not_after IS NULL OR s.not_after > now()))
$$;
REVOKE ALL ON FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid)
  FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid) TO pft_m5_authprobe;
```

Write the teardown `experiments/m5_cloud/auth_session_probe_teardown.sql`:

```sql
-- Teardown for auth_session_probe.sql (design §6, S7). Remove the Vercel deployments first.
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'pft_m5_authprobe';
REVOKE ALL ON FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid) FROM pft_m5_authprobe;
REVOKE ALL ON pft_m5_probe.identity FROM pft_m5_authprobe;
REVOKE ALL ON SCHEMA pft_m5_probe FROM pft_m5_authprobe;
DROP FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid);
DROP ROLE pft_m5_authprobe;
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_m5_auth_session_sql -v`
Expected: 8 tests OK, 0 skipped.

- [ ] **Step 6: Checkpoint (owner commits).** Files: the four above. Message: `Add the M5 auth probe session-check SQL with real-PostgreSQL privilege tests`.

---

### Task 3: API probe module with Tier L unit tests (db and auth modes)

**Files:**
- Create: `tests/m5_auth_support.py` (shared helpers; not a test module)
- Create: `experiments/m5_cloud/auth_api_probe.py`
- Create: `tests/test_m5_auth_api_probe.py`

**Interfaces:**
- Consumes: `experiments.m5_cloud.auth_probe.AuthConfig`, `AuthError`, `OwnerTokenVerifier` (unchanged), and the SQL function from Task 2.
- Produces:
  - `Settings(project_ref, owner_sub, database_url, session_check, publishable_key)` (frozen dataclass);
  - `load_settings(env=None) -> Settings`, which raises `RuntimeError`;
  - `create_app(settings, *, verifier=None, engine=None, http=None, instance=None) -> FastAPI`;
  - module constants `PROJECT_NAME`, `SESSION_SQL`, `IDENTITY_SQL`, `UUID_RE`, `CA_FILE`.
  - Routes `GET /probe/whoami` and `GET /probe/ping`. Every response carries the headers `x-probe-request-id`, `x-probe-instance`, `x-probe-db-connections`, `x-probe-session-checks`, `x-probe-data-queries` and `Cache-Control: private, no-store`.
  - Test helpers `tests.m5_auth_support`: `REF`, `OWNER`, `OTHER`, `ec_key()`, `public_jwk(private, kid)`, `mint(key, *, kid="kid-1", alg="ES256", headers=None, **claims) -> str`, `FakeEngine(session_result=True, data_result=REF, connect_error=None)`, `asgi_client(app)`.

- [ ] **Step 1: Write the shared helpers** `tests/m5_auth_support.py`:

```python
"""Shared helpers for the M5 owner-auth probe tests: keys, tokens, a fake engine, an ASGI client.

The fake engine stands in for SQLAlchemy's AsyncEngine in unit tests only; privileges and
connection release are proven against real PostgreSQL (tests/test_m5_auth_api_db.py, K1).
"""
import json
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

REF = "acyghoemtdrilsdszolq"
OWNER = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"
ISSUER = f"https://{REF}.supabase.co/auth/v1"


def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def public_jwk(private, kid):
    entry = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    return {**entry, "kid": kid, "alg": "ES256", "use": "sig"}


def mint(key, *, kid="kid-1", alg="ES256", headers=None, **claims):
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": "authenticated", "sub": OWNER, "iat": now, "exp": now + 600,
               "aal": "aal2", "is_anonymous": False, "role": "authenticated",
               "session_id": str(uuid.uuid4()), **claims}
    payload = {name: value for name, value in payload.items() if value is not None}
    return jwt.encode(payload, key, algorithm=alg, headers={"kid": kid, **(headers or {})})


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine
        self.statements = []

    def begin(self):
        return _Transaction(self)

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))

    async def scalar(self, statement, params=None):
        self.statements.append(str(statement))
        if "owner_session_alive" in str(statement):
            outcome = self.engine.next_session()
        else:
            outcome = self.engine.data_result
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def invalidate(self):
        self.engine.invalidated += 1

    async def close(self):
        self.engine.closed += 1


class FakeEngine:
    def __init__(self, session_result=True, data_result=REF, connect_error=None):
        self.session_result = session_result
        self.data_result = data_result
        self.connect_error = connect_error
        self.connections = []
        self.closed = 0
        self.invalidated = 0

    def next_session(self):
        if isinstance(self.session_result, list):
            return self.session_result.pop(0)
        return self.session_result

    def connect(self):
        return self._connect()

    async def _connect(self):
        if self.connect_error:
            raise self.connect_error
        connection = FakeConnection(self)
        self.connections.append(connection)
        return connection


def asgi_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe")
```

- [ ] **Step 2: Write the failing tests** `tests/test_m5_auth_api_probe.py`:

```python
"""Tier L unit tests for the M5 owner-auth API probe (design §5.2, §7). No network, no database.

Each claim rule is proven here with a trusted local test key; the deployed run (Tier D)
proves the real trust boundary. The deployed verifier has no test-key input.
"""
import base64
import json
import time
import unittest
import urllib.error
import uuid

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.exc import OperationalError

from experiments.m5_cloud.auth_api_probe import Settings, create_app, load_settings
from experiments.m5_cloud.auth_probe import AuthConfig, OwnerTokenVerifier
from tests.m5_auth_support import OTHER, OWNER, REF, FakeEngine, asgi_client, ec_key, mint, public_jwk

def unsigned(token):
    """The same claims under an `alg: none` header, with no signature."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "kid-1"}).encode()).rstrip(b"=").decode()
    return f"{header}.{token.split('.')[1]}."


VALID_URL = (f"postgresql+asyncpg://pft_m5_authprobe.{REF}:synthetic@"
             "aws-0-us-east-1.pooler.supabase.com:5432/postgres")
VALID_ENV = {
    "M5_VERCEL_PROJECT_NAME": "pft-m5-auth-api-20261009",
    "M5_SUPABASE_PROJECT_REF": REF,
    "M5_OWNER_AUTH_SUB": OWNER,
    "M5_SESSION_CHECK": "db",
    "M5_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
    "DATABASE_URL": VALID_URL,
}


class SettingsTests(unittest.TestCase):
    def test_valid_environment(self):
        settings = load_settings(dict(VALID_ENV))
        self.assertEqual((settings.project_ref, settings.owner_sub, settings.session_check),
                         (REF, OWNER, "db"))

    def test_rejections(self):
        cases = {
            "secret key variable": {"SUPABASE_SECRET_KEY": "x"},
            "sb_secret value anywhere": {"UNRELATED": "sb_secret_abc"},
            "plaid secret": {"PLAID_SECRET": "x"},
            "wrong project": {"M5_VERCEL_PROJECT_NAME": "pft-m5-reader-20261001"},
            "uppercase owner": {"M5_OWNER_AUTH_SUB": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"},
            "bad mode": {"M5_SESSION_CHECK": "none"},
            "missing publishable key": {"M5_SUPABASE_PUBLISHABLE_KEY": ""},
            "wrong database user": {"DATABASE_URL": VALID_URL.replace("pft_m5_authprobe", "pft_m5_reader")},
            "direct host": {"DATABASE_URL": VALID_URL.replace("aws-0-us-east-1.pooler.supabase.com",
                                                              f"db.{REF}.supabase.co")},
            "query override": {"DATABASE_URL": VALID_URL + "?ssl=disable"},
            "empty url": {"DATABASE_URL": ""},
        }
        for name, change in cases.items():
            with self.subTest(name):
                with self.assertRaises(RuntimeError):
                    load_settings({**VALID_ENV, **change})


class ProbeCase(unittest.IsolatedAsyncioTestCase):
    mode = "db"

    def setUp(self):
        self.key = ec_key()
        self.jwks = {"keys": [public_jwk(self.key, "kid-1")]}
        self.fetch_error = None
        self.engine = FakeEngine()
        self.auth_requests = []
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.auth_api))
        settings = Settings(REF, OWNER, "postgresql+asyncpg://unused", self.mode, "sb_publishable_test")
        verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=OWNER), fetch=self.fetch)
        self.app = create_app(settings, verifier=verifier, engine=self.engine, http=self.http,
                              instance="test-instance")

    async def asyncTearDown(self):
        await self.http.aclose()

    def fetch(self, url):
        if self.fetch_error:
            raise self.fetch_error
        return self.jwks

    def auth_api(self, request):
        raise AssertionError("db mode must never call the Auth API (K3)")

    async def call(self, authorization=None, path="/probe/whoami"):
        headers = {} if authorization is None else {"authorization": authorization}
        async with asgi_client(self.app) as client:
            return await client.get(path, headers=headers)

    def assert_counters(self, response, connections, checks, data):
        self.assertEqual(response.headers["x-probe-db-connections"], str(connections))
        self.assertEqual(response.headers["x-probe-session-checks"], str(checks))
        self.assertEqual(response.headers["x-probe-data-queries"], str(data))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-probe-instance"], "test-instance")
        self.assertRegex(response.headers["x-probe-request-id"], r"^[0-9a-f]{32}$")


class DbModeTests(ProbeCase):
    async def test_success_returns_identity_and_timings(self):
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["aal"], body["session_check"], body["identity_ok"]), ("aal2", "db", True))
        self.assertGreater(body["seconds_until_exp"], 500)
        self.assertEqual(set(body["timings_ms"]), {"connect", "session_check", "data", "total"})
        self.assert_counters(response, 1, 1, 1)
        self.assertEqual(self.engine.closed, 1)

    async def test_rejected_tokens_never_open_a_connection(self):
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_key = ec_key()
        now = int(time.time())
        cases = {
            "missing": (None, 401),
            "lowercase scheme": ("bearer " + mint(self.key), 401),
            "basic scheme": ("Basic b3duZXI6eA==", 401),
            "oversized": ("Bearer " + "a" * 9000, 401),
            "malformed": ("Bearer not-a-jwt", 401),
            "alg none": ("Bearer " + unsigned(mint(self.key)), 401),
            "HS256": ("Bearer " + mint(b"s" * 32, alg="HS256"), 401),
            "RS256": ("Bearer " + mint(rsa_key, alg="RS256"), 401),
            "unknown kid": ("Bearer " + mint(other_key, kid="kid-x"), 401),
            "bad signature": ("Bearer " + mint(other_key), 401),
            "wrong iss": ("Bearer " + mint(self.key, iss="https://other.supabase.co/auth/v1"), 401),
            "wrong aud": ("Bearer " + mint(self.key, aud="anon"), 401),
            "expired": ("Bearer " + mint(self.key, iat=now - 700, exp=now - 60), 401),
            "not yet valid": ("Bearer " + mint(self.key, nbf=now + 120), 401),
            "missing iat": ("Bearer " + mint(self.key, iat=None), 401),
            "non-owner": ("Bearer " + mint(self.key, sub=OTHER), 403),
            "anonymous": ("Bearer " + mint(self.key, is_anonymous=True), 403),
            "aal1": ("Bearer " + mint(self.key, aal="aal1"), 403),
            "missing session_id": ("Bearer " + mint(self.key, session_id=None), 401),
            "uppercase session_id": ("Bearer " + mint(self.key, session_id=str(uuid.uuid4()).upper()), 401),
            "malformed session_id": ("Bearer " + mint(self.key, session_id="not-a-uuid"), 401),
        }
        for name, (authorization, status) in cases.items():
            with self.subTest(name):
                response = await self.call(authorization)
                self.assertEqual(response.status_code, status, response.text)
                self.assert_counters(response, 0, 0, 0)
        self.assertEqual(self.engine.connections, [])

    async def test_jwks_unavailable_is_503_without_connection(self):
        self.fetch_error = urllib.error.URLError("down")
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()["error"]), (503, "auth keys unavailable"))
        self.assert_counters(response, 0, 0, 0)

    async def test_revoked_session_is_401_without_data_query(self):
        self.engine.session_result = False
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()["error"]), (401, "session revoked"))
        self.assert_counters(response, 1, 1, 0)
        self.assertEqual(self.engine.closed, 1)

    async def test_session_check_failure_is_503_and_closes(self):
        self.engine.session_result = OperationalError("SELECT", {}, Exception("statement timeout"))
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()["error"]), (503, "session check unavailable"))
        self.assert_counters(response, 1, 1, 0)
        self.assertEqual(self.engine.closed, 1)

    async def test_connect_failure_is_503(self):
        self.engine.connect_error = OSError("refused")
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()["error"]), (503, "session check unavailable"))
        self.assert_counters(response, 0, 0, 0)

    async def test_data_failure_is_503_and_closes(self):
        self.engine.data_result = OperationalError("SELECT", {}, Exception("permission denied"))
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()["error"]), (503, "data unavailable"))
        self.assert_counters(response, 1, 1, 0)
        self.assertEqual(self.engine.closed, 1)

    async def test_no_caching_between_requests(self):
        token = "Bearer " + mint(self.key)
        self.engine.session_result = [True, False]
        first = await self.call(token)
        second = await self.call(token)
        self.assertEqual((first.status_code, second.status_code), (200, 401))

    async def test_unknown_path_and_method_have_zero_counters(self):
        response = await self.call("Bearer " + mint(self.key), path="/probe/nope")
        self.assertEqual(response.status_code, 404)
        self.assert_counters(response, 0, 0, 0)
        async with asgi_client(self.app) as client:
            posted = await client.post("/probe/whoami")
        self.assertEqual(posted.status_code, 405)
        self.assert_counters(posted, 0, 0, 0)

    async def test_ping_needs_no_auth_and_no_database(self):
        response = await self.call(path="/probe/ping")
        self.assertEqual((response.status_code, response.json()["kind"]), (200, "m5_auth_ping"))
        self.assert_counters(response, 0, 0, 0)

    async def test_docs_are_not_served(self):
        for path in ("/docs", "/openapi.json", "/redoc"):
            with self.subTest(path):
                self.assertEqual((await self.call(path=path)).status_code, 404)


class AuthModeTests(ProbeCase):
    mode = "auth"

    def setUp(self):
        self.auth_status = 200
        self.auth_error = None
        super().setUp()

    def auth_api(self, request):
        self.auth_requests.append(request)
        if self.auth_error:
            raise self.auth_error
        body = {"id": OWNER} if self.auth_status == 200 else {"error_code": "session_not_found"}
        return httpx.Response(self.auth_status, json=body)

    async def test_alive_session_reads_data_without_the_db_function(self):
        token = "Bearer " + mint(self.key)
        response = await self.call(token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session_check"], "auth")
        self.assert_counters(response, 1, 1, 1)
        request = self.auth_requests[0]
        self.assertEqual(str(request.url), f"https://{REF}.supabase.co/auth/v1/user")
        self.assertEqual((request.headers["authorization"], request.headers["apikey"]),
                         (token, "sb_publishable_test"))
        statements = [s for connection in self.engine.connections for s in connection.statements]
        self.assertFalse(any("owner_session_alive" in s for s in statements))

    async def test_revoked_session_is_401_without_connection(self):
        self.auth_status = 403
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()["error"]), (401, "session revoked"))
        self.assert_counters(response, 0, 1, 0)

    async def test_auth_unavailable_is_503_and_never_falls_back(self):
        for failure in (httpx.ConnectError("down"), httpx.ReadTimeout("slow")):
            with self.subTest(type(failure).__name__):
                self.auth_error = failure
                response = await self.call("Bearer " + mint(self.key))
                self.assertEqual((response.status_code, response.json()["error"]),
                                 (503, "session check unavailable"))
                self.assert_counters(response, 0, 1, 0)
        self.auth_error, self.auth_status = None, 500
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.engine.connections, [])

    async def test_rejected_jwt_never_calls_auth_api(self):
        response = await self.call("Bearer not-a-jwt")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.auth_requests, [])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_m5_auth_api_probe -v`
Expected: import ERROR, `ModuleNotFoundError: No module named 'experiments.m5_cloud.auth_api_probe'`.

- [ ] **Step 4: Write the module** `experiments/m5_cloud/auth_api_probe.py`:

```python
"""Disposable M5 owner-auth API probe (docs/PFT_M5_AUTH_PROBE_DESIGN_2026-10-09.md §3).

Not the M6 integration and not mounted in api.main. GET /probe/whoami reads the synthetic
identity row only after the JWT, the session_id claim and the session check have passed.
The session-check mode is fixed per deployment (K3): a failed or unavailable check returns
503 and never falls back to the other mode. No result is cached (K1). The staged bundle's
main.py builds the app with create_app(load_settings()).
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import ssl
import time
import uuid

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from experiments.m5_cloud.auth_probe import AuthConfig, AuthError, OwnerTokenVerifier

PROJECT_NAME = "pft-m5-auth-api-20261009"
DB_ROLE = "pft_m5_authprobe"
MODES = ("db", "auth")
FORBIDDEN_ENV = ("PLAID_SECRET", "PLAID_CLIENT_ID", "PLAID_TOKEN_ENCRYPTION_KEY",
                 "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "PFT_M5_SECRET_KEY")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
POOLER_RE = re.compile(r"aws-\d+-[a-z0-9-]+\.pooler\.supabase\.com")
CA_FILE = Path(__file__).resolve().parents[2] / "supabase-ca.crt"  # bundle root, set by staging
CONNECT_TIMEOUT_S = 5
STATEMENT_TIMEOUT = "2s"
AUTH_TIMEOUT_S = 3.0
MAX_AUTHORIZATION_CHARS = 8192
NO_STORE = "private, no-store"
SET_TIMEOUT_SQL = text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
SESSION_SQL = text("SELECT pft_m5_probe.owner_session_alive(CAST(:session AS uuid), CAST(:owner AS uuid))")
IDENTITY_SQL = text("SELECT project_ref FROM pft_m5_probe.identity WHERE singleton")


@dataclass(frozen=True)
class Settings:
    project_ref: str
    owner_sub: str
    database_url: str
    session_check: str
    publishable_key: str


def load_settings(env=None):
    env = os.environ if env is None else env
    if any(env.get(name) for name in FORBIDDEN_ENV) or any(
            isinstance(value, str) and value.startswith("sb_secret_") for value in env.values()):
        raise RuntimeError("Secret credentials are forbidden in the auth probe")
    if env.get("M5_VERCEL_PROJECT_NAME") != PROJECT_NAME:
        raise RuntimeError("Wrong experiment project")
    ref = env.get("M5_SUPABASE_PROJECT_REF", "")
    if not re.fullmatch(r"[a-z]{20}", ref):
        raise RuntimeError("Missing synthetic project pin")
    owner = env.get("M5_OWNER_AUTH_SUB", "")
    if not UUID_RE.fullmatch(owner):
        raise RuntimeError("M5_OWNER_AUTH_SUB must be a lowercase canonical UUID")
    mode = env.get("M5_SESSION_CHECK", "")
    if mode not in MODES:
        raise RuntimeError("M5_SESSION_CHECK must be db or auth")
    key = env.get("M5_SUPABASE_PUBLISHABLE_KEY", "")
    if not key.startswith("sb_publishable_"):
        raise RuntimeError("M5_SUPABASE_PUBLISHABLE_KEY must be a publishable key")
    url = env.get("DATABASE_URL", "")
    try:
        parsed = make_url(url)
    except Exception:
        raise RuntimeError("DATABASE_URL is not a valid URL") from None
    if (parsed.drivername != "postgresql+asyncpg" or parsed.username != f"{DB_ROLE}.{ref}"
            or not POOLER_RE.fullmatch(parsed.host or "") or parsed.port not in (None, 5432)
            or parsed.database != "postgres" or not parsed.password or parsed.query):
        raise RuntimeError("DATABASE_URL must be the pinned session-pooler URL of the probe role")
    return Settings(ref, owner, url, mode, key)


def default_engine(settings):
    # verify-full against the pinned Supabase root CA only (copied next to main.py by staging).
    context = ssl.create_default_context(cafile=str(CA_FILE))
    return create_async_engine(settings.database_url, poolclass=NullPool,
                               connect_args={"ssl": context, "timeout": CONNECT_TIMEOUT_S,
                                             "command_timeout": 5})


@dataclass
class Diagnostics:
    instance: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    db_connections: int = 0
    session_checks: int = 0
    data_queries: int = 0
    timings_ms: dict = field(default_factory=dict)

    def timed(self, name, started):
        self.timings_ms[name] = round((time.perf_counter() - started) * 1000, 2)

    def respond(self, status, body):
        return JSONResponse(body, status_code=status, headers={
            "Cache-Control": NO_STORE, "x-probe-request-id": self.request_id,
            "x-probe-instance": self.instance, "x-probe-db-connections": str(self.db_connections),
            "x-probe-session-checks": str(self.session_checks),
            "x-probe-data-queries": str(self.data_queries)})


class ProbeError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass
class OwnerContext:
    claims: dict
    connection: object


def create_app(settings, *, verifier=None, engine=None, http=None, instance=None):
    verifier = verifier or OwnerTokenVerifier(AuthConfig(project_ref=settings.project_ref,
                                                         owner_sub=settings.owner_sub))
    engine = engine if engine is not None else default_engine(settings)
    http = http if http is not None else httpx.AsyncClient(timeout=AUTH_TIMEOUT_S)
    instance = instance or uuid.uuid4().hex
    user_url = f"https://{settings.project_ref}.supabase.co/auth/v1/user"
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def verified_claims(authorization):
        if not authorization or len(authorization) > MAX_AUTHORIZATION_CHARS:
            raise ProbeError(401, "bearer token required")
        try:
            claims = await asyncio.to_thread(verifier.verify, authorization)
        except AuthError as exc:
            raise ProbeError(exc.status, exc.reason) from None
        except (OSError, ValueError, jwt.PyJWTError):
            raise ProbeError(503, "auth keys unavailable") from None
        session_id = claims.get("session_id")
        if not isinstance(session_id, str) or not UUID_RE.fullmatch(session_id):
            raise ProbeError(401, "session id required")
        return claims

    async def auth_api_check(authorization, diag):
        diag.session_checks += 1
        started = time.perf_counter()
        try:
            response = await http.get(user_url, headers={"apikey": settings.publishable_key,
                                                          "Authorization": authorization})
        except httpx.HTTPError:
            raise ProbeError(503, "session check unavailable") from None
        finally:
            diag.timed("session_check", started)
        if response.status_code in (401, 403):
            raise ProbeError(401, "session revoked")
        if response.status_code != 200:
            raise ProbeError(503, "session check unavailable")

    @asynccontextmanager
    async def owner_request(request, diag):
        authorization = request.headers.get("authorization", "")
        claims = await verified_claims(authorization)     # no connection before this passes
        if settings.session_check == "auth":
            await auth_api_check(authorization, diag)     # K3: never falls back to the db check
        stage = "session check unavailable" if settings.session_check == "db" else "data unavailable"
        connection = None
        started = time.perf_counter()
        try:
            connection = await engine.connect()
            diag.db_connections += 1
            diag.timed("connect", started)
            async with connection.begin():
                await connection.execute(SET_TIMEOUT_SQL)
                if settings.session_check == "db":
                    diag.session_checks += 1
                    check_started = time.perf_counter()
                    alive = await connection.scalar(SESSION_SQL, {"session": claims["session_id"],
                                                                  "owner": settings.owner_sub})
                    diag.timed("session_check", check_started)
                    if alive is not True:
                        raise ProbeError(401, "session revoked")
                stage = "data unavailable"
                yield OwnerContext(claims, connection)
        except (OSError, SQLAlchemyError):
            raise ProbeError(503, stage) from None
        except asyncio.CancelledError:
            if connection is not None:
                await asyncio.shield(connection.invalidate())
                connection = None
            raise
        finally:
            if connection is not None:
                await asyncio.shield(connection.close())

    @app.get("/probe/ping")
    async def ping():
        return Diagnostics(instance).respond(200, {"kind": "m5_auth_ping"})

    @app.get("/probe/whoami")
    async def whoami(request: Request):
        diag = Diagnostics(instance)
        started = time.perf_counter()
        try:
            async with owner_request(request, diag) as owner:
                data_started = time.perf_counter()
                project_ref = await owner.connection.scalar(IDENTITY_SQL)
                diag.data_queries += 1
                diag.timed("data", data_started)
        except ProbeError as error:
            return diag.respond(error.status, {"error": error.reason})
        diag.timed("total", started)
        claims = owner.claims
        return diag.respond(200, {
            "kind": "m5_auth_whoami", "aal": claims.get("aal"), "iat": claims.get("iat"),
            "exp": claims.get("exp"), "seconds_until_exp": int(claims["exp"] - time.time()),
            "session_check": settings.session_check,
            "identity_ok": project_ref == settings.project_ref, "timings_ms": diag.timings_ms})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        reason = "not found" if exc.status_code == 404 else "rejected"
        return Diagnostics(instance).respond(exc.status_code, {"error": reason})

    return app
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_m5_auth_api_probe tests.test_m5_auth_probe -v`
Expected: all OK (the existing 10 verifier tests still pass).

- [ ] **Step 6: Checkpoint (owner commits).** Files: the three above. Message: `Add the M5 owner-auth API probe with Tier L tests for db and auth modes`.

---

### Task 4: Real-PostgreSQL connection release and no-caching tests

**Files:**
- Create: `tests/test_m5_auth_api_db.py`

**Interfaces:**
- Consumes: `tests.m5_auth_pg` (Task 2); `create_app` and `Settings` (Task 3); `tests.m5_auth_support` (Task 3).

- [ ] **Step 1: Write the tests** `tests/test_m5_auth_api_db.py`:

```python
"""Connection release and no-caching against real PostgreSQL (design §7, K1).

Runs the real FastAPI app in-process against a fresh database on the disposable
loopback cluster. Needs PFT_M5_AUTH_SYNTHETIC_TEST=1.
"""
import asyncio
import os
import time
import unittest
import uuid


def _no_auth_calls(request):
    raise AssertionError("db mode must never call the Auth API (K3)")


@unittest.skipUnless(os.environ.get("PFT_M5_AUTH_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class ConnectionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from experiments.m5_cloud.auth_api_probe import Settings, create_app
        from experiments.m5_cloud.auth_probe import AuthConfig, OwnerTokenVerifier
        from tests import m5_auth_pg
        from tests.m5_auth_support import OWNER, REF, ec_key, public_jwk
        self.pg = m5_auth_pg
        self.owner = OWNER
        self.name = await m5_auth_pg.create_fixture()
        self.admin = await m5_auth_pg.admin_connect(self.name)
        self.key = ec_key()
        jwks = {"keys": [public_jwk(self.key, "kid-1")]}
        verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=OWNER), fetch=lambda url: jwks)
        url = m5_auth_pg.probe_url(self.name)
        self.engine = create_async_engine(url, poolclass=NullPool,
                                          connect_args={"timeout": 5, "command_timeout": 5})
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(_no_auth_calls))
        self.app = create_app(Settings(REF, OWNER, url, "db", "sb_publishable_test"),
                              verifier=verifier, engine=self.engine, http=self.http, instance="pg-test")

    async def asyncTearDown(self):
        await self.http.aclose()
        await self.engine.dispose()
        await self.admin.close()
        await self.pg.drop_fixture(self.name)

    async def session(self):
        session = uuid.uuid4()
        await self.admin.execute("INSERT INTO auth.sessions VALUES ($1, $2, 'aal2', NULL)",
                                 session, uuid.UUID(self.owner))
        return session

    def token(self, session):
        from tests.m5_auth_support import mint
        return "Bearer " + mint(self.key, session_id=str(session))

    async def get(self, authorization):
        from tests.m5_auth_support import asgi_client
        async with asgi_client(self.app) as client:
            return await client.get("/probe/whoami", headers={"authorization": authorization})

    async def probe_backends(self):
        return await self.admin.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE usename = 'pft_m5_authprobe'")

    async def assert_released(self, timeout=6.0):
        deadline = time.monotonic() + timeout
        count = await self.probe_backends()
        while count and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            count = await self.probe_backends()
        self.assertEqual(count, 0, "a probe-role connection is still open")

    async def slow_function(self, seconds):
        await self.admin.execute(
            "CREATE OR REPLACE FUNCTION pft_m5_probe.owner_session_alive(p_session uuid, p_owner uuid) "
            "RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' "
            f"AS $$ SELECT true FROM pg_sleep({seconds}) $$")

    async def test_success_releases_connection(self):
        response = await self.get(self.token(await self.session()))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["identity_ok"])
        await self.assert_released()

    async def test_rejected_jwt_never_connects(self):
        response = await self.get("Bearer not-a-jwt")
        self.assertEqual((response.status_code, response.headers["x-probe-db-connections"]), (401, "0"))
        self.assertEqual(await self.probe_backends(), 0)

    async def test_revoked_session_releases_connection(self):
        session = await self.session()
        await self.admin.execute("DELETE FROM auth.sessions WHERE id = $1", session)
        response = await self.get(self.token(session))
        self.assertEqual((response.status_code, response.json()["error"]), (401, "session revoked"))
        self.assertEqual(response.headers["x-probe-data-queries"], "0")
        await self.assert_released()

    async def test_session_check_timeout_is_503_and_releases(self):
        await self.slow_function(3)
        response = await self.get(self.token(await self.session()))
        self.assertEqual((response.status_code, response.json()["error"]), (503, "session check unavailable"))
        await self.assert_released()

    async def test_route_failure_after_check_releases(self):
        await self.admin.execute("REVOKE SELECT ON pft_m5_probe.identity FROM pft_m5_authprobe")
        response = await self.get(self.token(await self.session()))
        self.assertEqual((response.status_code, response.json()["error"]), (503, "data unavailable"))
        self.assertEqual(response.headers["x-probe-session-checks"], "1")
        await self.assert_released()

    async def test_client_cancellation_releases(self):
        await self.slow_function(1.5)
        task = asyncio.create_task(self.get(self.token(await self.session())))
        await asyncio.sleep(0.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.assert_released()

    async def test_same_token_concurrently_then_revoked(self):
        session = await self.session()
        token = self.token(session)
        # Three at once: the probe role's connection limit is 4.
        responses = await asyncio.gather(*(self.get(token) for _ in range(3)))
        self.assertEqual([r.status_code for r in responses], [200, 200, 200])
        self.assertEqual([r.headers["x-probe-session-checks"] for r in responses], ["1", "1", "1"])
        await self.admin.execute("DELETE FROM auth.sessions WHERE id = $1", session)
        after = await self.get(token)
        self.assertEqual((after.status_code, after.json()["error"]), (401, "session revoked"))
        await self.assert_released()
```

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_m5_auth_api_db -v`
Expected: 7 tests OK. This task tests the Task 3 module against real PostgreSQL. A failure here is a real defect in `owner_request`: fix it there (for example, connection release on cancellation) and rerun Tasks 3 and 4. Do **not** weaken a test.

- [ ] **Step 3: Checkpoint (owner commits).** File: `tests/test_m5_auth_api_db.py`, plus any `auth_api_probe.py` fix. Message: `Prove M5 auth probe connection release and no caching against PostgreSQL`.

---

### Task 5: Web forwarding module with `node:test`

**Files:**
- Create: `experiments/m5_cloud/auth_web_probe/lib/forward.mjs`
- Create: `experiments/m5_cloud/auth_web_probe/lib/forward.test.mjs`

**Interfaces:**
- Produces: `OPERATIONS` (Set), `upstreamFrom(env) -> { url: URL, bypass: string }` (throws on any pin failure), and `forward({ operation, accessToken, env, fetcher = fetch, timeoutMs = 15000 }) -> Promise<Response>`.

- [ ] **Step 1: Write the failing tests** `experiments/m5_cloud/auth_web_probe/lib/forward.test.mjs`:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { forward, upstreamFrom } from './forward.mjs'

const HOST = 'pft-m5-auth-api-20261009-abc123-pft2.vercel.app'
const env = { M5_API_URL: `https://${HOST}/`, M5_API_HOST: HOST, M5_API_PROTECTION_BYPASS: 'b'.repeat(32) }

function fake(make, calls = []) {
  const fetcher = async (url, init) => { calls.push({ url: String(url), init }); return make() }
  return { fetcher, calls }
}

test('unknown operation and missing token never call upstream', async () => {
  const { fetcher, calls } = fake(() => new Response('{}'))
  for (const [operation, accessToken, status] of [['admin', 't', 404], ['whoami', '', 401]]) {
    const result = await forward({ operation, accessToken, env, fetcher })
    assert.equal(result.status, status)
    assert.equal(result.headers.get('cache-control'), 'private, no-store')
  }
  assert.equal(calls.length, 0)
})

test('pins reject every other upstream', async () => {
  const bad = [
    { M5_API_URL: `http://${HOST}/` },
    { M5_API_URL: `https://${HOST}:8443/` },
    { M5_API_URL: `https://${HOST}/x` },
    { M5_API_URL: `https://${HOST}/?a=1` },
    { M5_API_URL: 'https://evil.example/', M5_API_HOST: 'evil.example' },
    { M5_API_URL: 'https://pft-m5-reader-20261001-x.vercel.app/', M5_API_HOST: 'pft-m5-reader-20261001-x.vercel.app' },
    { M5_API_PROTECTION_BYPASS: 'short' },
    { M5_API_URL: undefined },
  ]
  for (const change of bad) {
    assert.throws(() => upstreamFrom({ ...env, ...change }))
    const { fetcher, calls } = fake(() => new Response('{}'))
    const result = await forward({ operation: 'whoami', accessToken: 't', env: { ...env, ...change }, fetcher })
    assert.equal(result.status, 503)
    assert.equal(calls.length, 0)
  }
})

test('success passes the body and probe headers only', async () => {
  const { fetcher, calls } = fake(() => new Response(JSON.stringify({ kind: 'm5_auth_whoami', aal: 'aal2' }), {
    status: 200,
    headers: { 'content-type': 'application/json', 'x-probe-request-id': 'r1', 'x-probe-db-connections': '1', 'set-cookie': 'a=b' },
  }))
  const result = await forward({ operation: 'whoami', accessToken: 'tok', env, fetcher })
  assert.equal(result.status, 200)
  assert.deepEqual(await result.json(), { kind: 'm5_auth_whoami', aal: 'aal2' })
  assert.equal(result.headers.get('x-probe-request-id'), 'r1')
  assert.equal(result.headers.get('x-probe-db-connections'), '1')
  assert.equal(result.headers.get('set-cookie'), null)
  assert.equal(result.headers.get('cache-control'), 'private, no-store')
  assert.equal(calls[0].url, `https://${HOST}/probe/whoami`)
  assert.deepEqual(Object.keys(calls[0].init.headers).sort(), ['authorization', 'x-vercel-protection-bypass'])
  assert.equal(calls[0].init.headers.authorization, 'Bearer tok')
  assert.equal(calls[0].init.redirect, 'error')
  assert.equal(calls[0].init.cache, 'no-store')
})

test('rejections pass through with their reason; other statuses become 502', async () => {
  for (const status of [401, 403, 503]) {
    const { fetcher } = fake(() => new Response(JSON.stringify({ error: 'session revoked' }), { status }))
    const result = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
    assert.equal(result.status, status)
    assert.deepEqual(await result.json(), { error: 'session revoked' })
  }
  const { fetcher } = fake(() => new Response('boom', { status: 500 }))
  const failed = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
  assert.equal(failed.status, 502)
  assert.equal((await failed.json()).upstream_status, 500)
})

test('a 200 with a non-JSON body is never passed through', async () => {
  const { fetcher } = fake(() => new Response('<html>Vercel login</html>', { status: 200 }))
  const result = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
  assert.equal(result.status, 502)
})

test('network errors, timeouts and redirects become 502', async () => {
  const fetcher = async () => { throw new TypeError('fetch failed: redirect mode is set to error') }
  const result = await forward({ operation: 'whoami', accessToken: 't', env, fetcher })
  assert.equal(result.status, 502)
  assert.equal(result.headers.get('cache-control'), 'private, no-store')
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test experiments/m5_cloud/auth_web_probe/lib/forward.test.mjs`
Expected: FAIL, `Cannot find module …/forward.mjs`.

- [ ] **Step 3: Implement** `experiments/m5_cloud/auth_web_probe/lib/forward.mjs`:

```js
// Disposable M5 owner-auth probe: forward one allowlisted operation to the pinned API preview
// (design §3 unit 2). Pure so node:test can cover it; the route handler supplies the access
// token only after getClaims() validated the session. Browser cookies are never forwarded.
export const OPERATIONS = new Set(['whoami'])
const API_PROJECT = 'pft-m5-auth-api-20261009'
const NO_STORE = { 'Cache-Control': 'private, no-store' }

export function upstreamFrom(env) {
  const url = new URL(env.M5_API_URL)
  if (url.protocol !== 'https:' || url.port || url.username || url.password || url.search ||
      url.hash || url.pathname !== '/' || url.hostname !== env.M5_API_HOST ||
      !url.hostname.endsWith('.vercel.app') || !url.hostname.startsWith(`${API_PROJECT}-`) ||
      (env.M5_API_PROTECTION_BYPASS || '').length < 32) {
    throw new Error('upstream pin rejected')
  }
  return { url, bypass: env.M5_API_PROTECTION_BYPASS }
}

function probeHeaders(result) {
  const headers = { ...NO_STORE }
  for (const [name, value] of result.headers) {
    if (name.startsWith('x-probe-')) headers[name] = value
  }
  return headers
}

export async function forward({ operation, accessToken, env, fetcher = fetch, timeoutMs = 15000 }) {
  if (!OPERATIONS.has(operation)) {
    return Response.json({ error: 'unknown operation' }, { status: 404, headers: NO_STORE })
  }
  if (typeof accessToken !== 'string' || accessToken.length === 0) {
    return Response.json({ error: 'not signed in' }, { status: 401, headers: NO_STORE })
  }
  let upstream
  try {
    upstream = upstreamFrom(env)
  } catch {
    return Response.json({ error: 'upstream rejected' }, { status: 503, headers: NO_STORE })
  }
  let result
  try {
    result = await fetcher(new URL(`/probe/${operation}`, upstream.url), {
      headers: { authorization: `Bearer ${accessToken}`, 'x-vercel-protection-bypass': upstream.bypass },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
    })
  } catch {
    return Response.json({ error: 'upstream unavailable' }, { status: 502, headers: NO_STORE })
  }
  const headers = probeHeaders(result)
  let body = null
  try {
    body = await result.json()
  } catch {
    body = null
  }
  if (result.status === 200 && body !== null && typeof body === 'object') {
    return Response.json(body, { status: 200, headers })
  }
  if ([401, 403, 503].includes(result.status)) {
    const reason = body && typeof body.error === 'string' ? body.error : 'rejected'
    return Response.json({ error: reason }, { status: result.status, headers })
  }
  return Response.json({ error: 'upstream failed', upstream_status: result.status }, { status: 502, headers })
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test experiments/m5_cloud/auth_web_probe/lib/forward.test.mjs`
Expected: 6 tests pass.

- [ ] **Step 5: Checkpoint (owner commits).** Files: the two above. Message: `Add the M5 auth web probe forwarding module with node:test coverage`.

---

### Task 6: Next.js probe app (JavaScript) and local build

**Files:**
- Create: `experiments/m5_cloud/auth_web_probe/package.json` and `package-lock.json` (generated)
- Create: `experiments/m5_cloud/auth_web_probe/next.config.mjs`
- Create: `experiments/m5_cloud/auth_web_probe/middleware.js`
- Create: `experiments/m5_cloud/auth_web_probe/lib/config.js`, `lib/supabase/browser.js`, `lib/supabase/server.js`, `lib/supabase/middleware.js`
- Create: `experiments/m5_cloud/auth_web_probe/app/layout.js`, `app/page.js`, `app/login/page.js`, `app/probe/page.js`, `app/probe/probe-client.js`, `app/api/pft/probe/[op]/route.js`

**Interfaces:**
- Consumes: `forward` from Task 5.
- Produces: the web app the owner uses in S5:
  - `/login` (password, then TOTP; an "aal1 route call" button for P3);
  - `/probe` (buttons: whoami, whoami ×2, copy evidence, sign out);
  - route `GET /api/pft/probe/whoami`;
  - the response header `x-probe-mw-refresh: 1` when middleware refreshed Auth cookies.

- [ ] **Step 1: Write the package and config files.**

`package.json`:

```json
{
  "name": "pft-m5-auth-web-probe",
  "version": "0.0.0",
  "private": true,
  "engines": { "node": "22.x" },
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "node --test lib/forward.test.mjs"
  },
  "dependencies": {
    "@supabase/ssr": "0.12.7",
    "@supabase/supabase-js": "2.117.3",
    "next": "15.5.24",
    "react": "19.2.8",
    "react-dom": "19.2.8"
  }
}
```

`next.config.mjs`:

```js
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // The repository root has its own lockfile; pin tracing to this probe directory.
  outputFileTracingRoot: dirname(fileURLToPath(import.meta.url)),
}

export default nextConfig
```

`lib/config.js`:

```js
export const PROJECT_REF = 'acyghoemtdrilsdszolq'

export function publicConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
  if (url !== `https://${PROJECT_REF}.supabase.co` || !key?.startsWith('sb_publishable_')) {
    throw new Error('Supabase public configuration rejected')
  }
  return { url, key }
}
```

- [ ] **Step 2: Write the Supabase clients and middleware** (the official `@supabase/ssr` pattern for Next.js; Next 15 uses `middleware.js`).

`lib/supabase/browser.js`:

```js
import { createBrowserClient } from '@supabase/ssr'
import { publicConfig } from '../config.js'

export function createClient() {
  const { url, key } = publicConfig()
  return createBrowserClient(url, key)
}
```

`lib/supabase/server.js`:

```js
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { publicConfig } from '../config.js'

export async function createClient() {
  const cookieStore = await cookies()
  const { url, key } = publicConfig()
  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
        } catch {
          // Called from a Server Component; middleware.js writes refreshed cookies.
        }
      },
    },
  })
}
```

`lib/supabase/middleware.js`:

```js
import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import { publicConfig } from '../config.js'

const NO_STORE = 'private, no-store'

export async function updateSession(request) {
  let response = NextResponse.next({ request })
  let refreshed = false
  const { url, key } = publicConfig()
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet, headers) {
        refreshed ||= cookiesToSet.some(({ name, value }) => name.includes('-auth-token') && value)
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value))
        response = NextResponse.next({ request })
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options))
        Object.entries(headers ?? {}).forEach(([name, value]) => response.headers.set(name, value))
      },
    },
  })
  // Do not run code between createServerClient and getClaims() (official guidance).
  const { data } = await supabase.auth.getClaims()
  if (!data?.claims && request.nextUrl.pathname.startsWith('/probe')) {
    const login = request.nextUrl.clone()
    login.pathname = '/login'
    const redirect = NextResponse.redirect(login)
    response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie))
    redirect.headers.set('Cache-Control', NO_STORE)
    return redirect
  }
  if (refreshed) response.headers.set('x-probe-mw-refresh', '1')
  response.headers.set('Cache-Control', NO_STORE)
  return response
}
```

`middleware.js`:

```js
import { updateSession } from './lib/supabase/middleware.js'

export async function middleware(request) {
  return updateSession(request)
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] }
```

- [ ] **Step 3: Write the pages and the route.**

`app/layout.js`:

```js
export const metadata = { title: 'PFT M5 auth probe', robots: { index: false, follow: false } }

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', margin: 24, maxWidth: 760 }}>{children}</body>
    </html>
  )
}
```

`app/page.js`:

```js
import { redirect } from 'next/navigation'

export default function Home() {
  redirect('/probe')
}
```

`app/login/page.js`:

```js
'use client'
import { useState } from 'react'
import { createClient } from '../../lib/supabase/browser.js'

export default function Login() {
  const supabase = createClient()
  const [step, setStep] = useState('password')
  const [status, setStatus] = useState('')
  const [factorId, setFactorId] = useState(null)

  async function signIn(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const { error } = await supabase.auth.signInWithPassword({
      email: String(form.get('email')), password: String(form.get('password')),
    })
    if (error) return setStatus(`sign-in failed: ${error.code ?? error.status}`)
    const { data, error: listError } = await supabase.auth.mfa.listFactors()
    const totp = data?.totp?.find((factor) => factor.status === 'verified')
    if (listError || !totp) return setStatus('no verified TOTP factor')
    setFactorId(totp.id)
    setStep('totp')
    setStatus('aal1 — enter the TOTP code')
  }

  async function verify(event) {
    event.preventDefault()
    const code = String(new FormData(event.currentTarget).get('code')).replace(/\s/g, '')
    const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId, code })
    if (error) return setStatus(`verify failed: ${error.code ?? error.status}`)
    window.location.assign('/probe')
  }

  async function routeCall() {
    const response = await fetch('/api/pft/probe/whoami', { cache: 'no-store' })
    setStatus(`route call: ${response.status}; upstream request id: ${response.headers.get('x-probe-request-id') ?? 'none'}`)
  }

  return (
    <main>
      <h1>M5 auth probe — sign in</h1>
      {step === 'password' ? (
        <form onSubmit={signIn}>
          <p><input name="email" type="email" autoComplete="username" placeholder="owner e-mail" required /></p>
          <p><input name="password" type="password" autoComplete="current-password" placeholder="password" required /></p>
          <button type="submit">Sign in</button>
        </form>
      ) : (
        <form onSubmit={verify}>
          <p><input name="code" inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" required /></p>
          <button type="submit">Verify TOTP</button>
        </form>
      )}
      <p><button type="button" onClick={routeCall}>Call the route now (P1/P3/P5 evidence)</button></p>
      <p role="status">{status}</p>
    </main>
  )
}
```

`app/probe/page.js`:

```js
import { redirect } from 'next/navigation'
import { createClient } from '../../lib/supabase/server.js'
import ProbeClient from './probe-client.js'

export const dynamic = 'force-dynamic'

export default async function Probe() {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()
  const claims = data?.claims
  if (!claims || claims.aal !== 'aal2') redirect('/login')
  return <ProbeClient rendered={{ aal: claims.aal, iat: claims.iat, exp: claims.exp }} />
}
```

`app/probe/probe-client.js`:

```js
'use client'
import { useState } from 'react'
import { createClient } from '../../lib/supabase/browser.js'

const PROBE_HEADERS = ['x-probe-request-id', 'x-probe-instance', 'x-probe-db-connections',
  'x-probe-session-checks', 'x-probe-data-queries']

// Evidence entries hold statuses, reasons, counters and claim times only — never tokens.
function entry(event, response, body) {
  const result = { at: new Date().toISOString(), event, status: response.status, error: body?.error ?? null }
  for (const name of ['aal', 'iat', 'exp', 'seconds_until_exp', 'session_check', 'identity_ok', 'timings_ms']) {
    if (body && name in body) result[name] = body[name]
  }
  for (const name of PROBE_HEADERS) result[name.slice(8).replaceAll('-', '_')] = response.headers.get(name)
  return result
}

export default function ProbeClient({ rendered }) {
  const supabase = createClient()
  const [log, setLog] = useState([{ at: new Date().toISOString(), event: 'server-rendered', ...rendered }])

  async function whoami(event) {
    const response = await fetch('/api/pft/probe/whoami', { cache: 'no-store' })
    let body = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    return entry(event, response, body)
  }

  async function once() {
    const result = await whoami('whoami')
    setLog((current) => [...current, result])
  }

  async function twice() {
    const results = await Promise.all([whoami('whoami-concurrent'), whoami('whoami-concurrent')])
    setLog((current) => [...current, ...results])
  }

  async function copy() {
    await navigator.clipboard.writeText(JSON.stringify(log, null, 2))
  }

  async function signOut() {
    await supabase.auth.signOut({ scope: 'global' })
    window.location.replace('/login') // full navigation discards client state
  }

  return (
    <main>
      <h1>M5 auth probe</h1>
      <p>
        <button type="button" onClick={once}>Fetch whoami</button>{' '}
        <button type="button" onClick={twice}>Fetch whoami ×2</button>{' '}
        <button type="button" onClick={copy}>Copy evidence JSON</button>{' '}
        <button type="button" onClick={signOut}>Sign out (global)</button>
      </p>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(log, null, 2)}</pre>
    </main>
  )
}
```

`app/api/pft/probe/[op]/route.js`:

```js
import { createClient } from '../../../../../lib/supabase/server.js'
import { forward } from '../../../../../lib/forward.mjs'

export const dynamic = 'force-dynamic'
const NO_STORE = { 'Cache-Control': 'private, no-store' }

export async function GET(request, { params }) {
  const { op } = await params
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()
  const claims = data?.claims
  if (!claims) return Response.json({ error: 'not signed in' }, { status: 401, headers: NO_STORE })
  if (claims.aal !== 'aal2') return Response.json({ error: 'aal2 required' }, { status: 403, headers: NO_STORE })
  // The token is only forwarded; FastAPI makes the authorization decision.
  const { data: sessionData } = await supabase.auth.getSession()
  return forward({ operation: op, accessToken: sessionData?.session?.access_token ?? '', env: process.env })
}
```

- [ ] **Step 4: Install, test and build locally** (public registry only; no secrets).

```bash
cd experiments/m5_cloud/auth_web_probe
npm install --no-audit --no-fund
npm test
NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SUPABASE_URL=https://acyghoemtdrilsdszolq.supabase.co \
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_cBTZ7SPZICiMJd1_YTRpkQ_qR7MwzPg npm run build
cd ../../..
```

Expected:
- `npm test`: 6 pass.
- `next build` succeeds and lists `/`, `/login`, `/probe`, `/api/pft/probe/[op]` and a `Middleware` entry.
- No `tsconfig.json` or `next-env.d.ts` is created in the probe directory (it is JavaScript only).

- [ ] **Step 5: Verify the product build is unaffected** (from the worktree root).

```bash
npm ci && npx --no-install tsc --noEmit && npm test -- --ci
git status --short   # must show no node_modules/ or .next/ under the probe
```

Expected: root `tsc` passes; root jest passes (it matches only `**/*.test.ts`); no build artefacts are tracked. If `tsconfig.tsbuildinfo` changes, restore it with `git restore tsconfig.tsbuildinfo`.

- [ ] **Step 6: Checkpoint (owner commits).** Files: everything under `experiments/m5_cloud/auth_web_probe/` except `node_modules` and `.next`, including `package-lock.json`. Message: `Add the M5 auth web probe (Next.js 15, JavaScript) with SSR session refresh`.

---

### Task 7: Owner-run matrix, samples and cleanup script

**Files:**
- Create: `experiments/m5_cloud/auth_api_matrix.py`
- Create: `tests/test_m5_auth_api_matrix.py`

**Interfaces:**
- Consumes: `tests.m5_auth_support` (Task 3), and `create_app`/`Settings` (Task 3) for the local forged-token run.
- Produces:
  - CLI `python -m experiments.m5_cloud.auth_api_matrix {matrix,samples,cleanup} --out FILE [--api-url URL] [--wrong-owner-url URL] [--auth-url URL]`;
  - `main(argv=None, io=None, client=None)`, `forged(real_token) -> dict[str, str]`, `record(response, started=None) -> dict`, `is_temporary(email) -> bool`, `summarize(runs) -> dict`.

- [ ] **Step 1: Write the failing tests** `tests/test_m5_auth_api_matrix.py`:

```python
"""Offline tests for the owner-run M5 auth probe script (design §5.2–§5.3, Review Focus 5).

The end-to-end test drives the real script against fakes of Supabase Auth and the probe API;
the evidence must hold no token, password or secret.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import uuid

import httpx
import jwt

from experiments.m5_cloud import auth_api_matrix as script
from experiments.m5_cloud.auth_api_probe import Settings, create_app
from experiments.m5_cloud.auth_probe import AuthConfig, AuthError, OwnerTokenVerifier
from tests.m5_auth_support import OWNER, REF, FakeEngine, asgi_client, ec_key, mint, public_jwk

API_HOST = "pft-m5-auth-api-20261009-db-pft2.vercel.app"
WRONG_HOST = "pft-m5-auth-api-20261009-wrong-pft2.vercel.app"
BYPASS = "b" * 32
SECRET = "sb_secret_fake"
OWNER_EMAIL = "owner@example.invalid"


class ForgedTokenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = ec_key()
        self.verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=OWNER),
                                           fetch=lambda url: {"keys": [public_jwk(self.key, "kid-1")]})
        self.real = mint(self.key)

    def test_each_forgery_fails_for_its_intended_reason(self):
        expected = {"D3_malformed": "malformed token", "D4_alg_none": "algorithm rejected",
                    "D5_hs256": "algorithm rejected", "D6_unknown_kid": "unknown signing key",
                    "D7_forged_signature": "InvalidSignatureError",
                    "D8_tampered_payload": "InvalidSignatureError"}
        forged = script.forged(self.real)
        self.assertEqual(set(forged), set(expected))
        for name, token in forged.items():
            with self.subTest(name):
                with self.assertRaises(AuthError) as caught:
                    self.verifier.verify("Bearer " + token)
                self.assertEqual((caught.exception.status, caught.exception.reason), (401, expected[name]))

    async def test_forgeries_against_the_local_app_never_reach_the_database(self):
        engine = FakeEngine()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
            app = create_app(Settings(REF, OWNER, "postgresql+asyncpg://unused", "db", "sb_publishable_test"),
                             verifier=self.verifier, engine=engine, http=http, instance="local")
            async with asgi_client(app) as client:
                for name, token in script.forged(self.real).items():
                    with self.subTest(name):
                        response = await client.get("/probe/whoami", headers={"authorization": "Bearer " + token})
                        self.assertEqual(response.status_code, 401)
        self.assertEqual(engine.connections, [])


class HelperTests(unittest.TestCase):
    def test_record_keeps_only_non_secret_fields(self):
        response = httpx.Response(200, json={"aal": "aal2", "access_token": "x" * 40, "seconds_until_exp": 200},
                                  headers={"x-probe-request-id": "r1", "set-cookie": "a=b"})
        entry = script.record(response)
        self.assertEqual(entry["status"], 200)
        self.assertEqual(entry["request_id"], "r1")
        self.assertNotIn("x" * 40, json.dumps(entry))

    def test_is_temporary_matches_only_script_users(self):
        self.assertTrue(script.is_temporary("m5-nonowner-0123456789ab@example.invalid"))
        for email in ("owner@example.invalid", "m5-nonowner-0123456789ab@example.com",
                      "m5-nonowner-short@example.invalid", None, "x-m5-nonowner-0123456789ab@example.invalid"):
            with self.subTest(email):
                self.assertFalse(script.is_temporary(email))

    def test_summarize_reports_sample_statistics(self):
        runs = [{"status": 200, "client_ms": float(i), "timings_ms": {"total": float(i), "connect": 1.0,
                 "session_check": 2.0, "data": 1.0}} for i in range(1, 31)]
        summary = script.summarize(runs + [{"status": 429}])
        self.assertEqual((summary["n"], summary["non_200"], summary["status_429"]), (31, 1, 1))
        self.assertEqual(summary["client_ms"]["p95"], 29.0)
        self.assertIn("sample statistic", summary["note"])


class FakeIO:
    def __init__(self, cloud):
        self.cloud = cloud
        self.lines = []

    def secret(self, prompt):
        for marker, value in (("bypass", BYPASS), ("sb_secret", SECRET),
                              ("NEW owner password", "new-password"), ("owner password", "old-password")):
            if marker in prompt:
                return value
        raise AssertionError(prompt)

    def ask(self, prompt):
        return OWNER_EMAIL

    def code(self, prompt=""):
        return "123456"

    def tty(self, text):
        self.lines.append(text)

    def sleep(self, seconds):
        self.cloud.offset += seconds


class FakeCloud:
    """Supabase Auth on the project host and the probe API on preview hosts, in memory."""

    def __init__(self):
        self.key = ec_key()
        self.offset = 0.0
        self.passwords = {OWNER_EMAIL: (OWNER, "old-password")}
        self.sessions, self.tokens, self.refresh_tokens = {}, {}, {}
        self.issued, self.deleted = [], []

    def issue(self, session_id):
        session = self.sessions[session_id]
        access = mint(self.key, sub=session["user"], aal=session["aal"], session_id=session_id,
                      exp=int(time.time()) + 300)
        refresh = uuid.uuid4().hex
        self.tokens[access] = self.refresh_tokens[refresh] = session_id
        self.issued += [access, refresh]
        return {"access_token": access, "refresh_token": refresh}

    def live(self, access):
        session_id = self.tokens.get(access)
        return session_id if session_id in self.sessions else None

    def handle(self, request):
        body = json.loads(request.content) if request.content else {}
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.host == f"{REF}.supabase.co":
            return self.auth(request, body, bearer)
        if request.headers.get("x-vercel-protection-bypass") != BYPASS:
            return httpx.Response(401)
        return self.api(request, bearer)

    def auth(self, request, body, bearer):
        path, grant = request.url.path.removeprefix("/auth/v1"), request.url.params.get("grant_type")
        admin = request.headers.get("apikey", "").startswith("sb_secret_")
        if path == "/token" and grant == "password":
            user = self.passwords.get(body["email"])
            if not user or user[1] != body["password"]:
                return httpx.Response(400, json={"error_code": "invalid_credentials"})
            session_id = str(uuid.uuid4())
            self.sessions[session_id] = {"user": user[0], "aal": "aal1"}
            return httpx.Response(200, json=self.issue(session_id))
        if path == "/token" and grant == "refresh_token":
            session_id = self.refresh_tokens.get(body["refresh_token"])
            if session_id not in self.sessions:
                return httpx.Response(400, json={"error_code": "refresh_token_not_found"})
            return httpx.Response(200, json=self.issue(session_id))
        if path == "/user":
            if not self.live(bearer):
                return httpx.Response(403)
            return httpx.Response(200, json={"id": OWNER, "factors": [
                {"id": "f1", "factor_type": "totp", "status": "verified"}]})
        if path == "/factors/f1/challenge":
            return httpx.Response(200, json={"id": "c1"})
        if path == "/factors/f1/verify":
            session_id = self.live(bearer)
            if not session_id or body.get("code") != "123456":
                return httpx.Response(422)
            self.sessions[session_id]["aal"] = "aal2"
            return httpx.Response(200, json=self.issue(session_id))
        if path == "/logout":
            session_id = self.live(bearer)
            if not session_id:
                return httpx.Response(403)
            user = self.sessions[session_id]["user"]
            self.sessions = {k: v for k, v in self.sessions.items() if v["user"] != user}
            return httpx.Response(204)
        if path == "/admin/users" and admin and request.method == "POST":
            user_id = str(uuid.uuid4())
            self.passwords[body["email"]] = (user_id, body["password"])
            return httpx.Response(200, json={"id": user_id, "email": body["email"]})
        if path.startswith("/admin/users/") and admin:
            target = path.rsplit("/", 1)[1]
            if request.method == "DELETE":
                self.deleted.append(target)
                return httpx.Response(200, json={})
            if request.method == "PUT":
                self.passwords[OWNER_EMAIL] = (OWNER, body["password"])
                self.sessions = {k: v for k, v in self.sessions.items() if v["user"] != target}
                return httpx.Response(200, json={})
        return httpx.Response(404)

    def api(self, request, bearer):
        headers = {"x-probe-request-id": uuid.uuid4().hex, "x-probe-db-connections": "0"}
        if request.url.path == "/probe/ping":
            return httpx.Response(200, json={"kind": "m5_auth_ping"}, headers=headers)
        if request.url.path != "/probe/whoami":
            return httpx.Response(404, json={"error": "not found"}, headers=headers)
        if not request.headers.get("authorization", "").startswith("Bearer ") or bearer not in self.tokens:
            return httpx.Response(401, json={"error": "rejected"}, headers=headers)
        claims = jwt.decode(bearer, options={"verify_signature": False})
        if claims["exp"] + 30 < time.time() + self.offset:
            return httpx.Response(401, json={"error": "ExpiredSignatureError"}, headers=headers)
        if request.url.host == WRONG_HOST or claims["sub"] != OWNER:
            return httpx.Response(403, json={"error": "not the owner"}, headers=headers)
        if claims["aal"] != "aal2":
            return httpx.Response(403, json={"error": "aal2 required"}, headers=headers)
        if not self.live(bearer):
            return httpx.Response(401, json={"error": "session revoked"}, headers=headers)
        return httpx.Response(200, headers=headers, json={
            "aal": "aal2", "session_check": "db", "identity_ok": True,
            "seconds_until_exp": int(claims["exp"] - time.time() - self.offset),
            "timings_ms": {"total": 1.0, "connect": 0.2, "session_check": 0.3, "data": 0.2}})


class ScriptFlowTests(unittest.TestCase):
    def run_script(self, argv, cloud):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)), \
                contextlib.redirect_stdout(io.StringIO()):
            out = Path(directory) / "evidence.json"
            script.main([*argv, "--out", str(out)], io=FakeIO(cloud),
                        client=httpx.Client(transport=httpx.MockTransport(cloud.handle)))
            return json.loads(out.read_text())

    def test_matrix_end_to_end_against_fakes(self):
        cloud = FakeCloud()
        evidence = self.run_script(["matrix", "--api-url", f"https://{API_HOST}/",
                                    "--wrong-owner-url", f"https://{WRONG_HOST}/"], cloud)
        cases = evidence["cases"]
        for name in ("D1_no_authorization", "D2_non_bearer", "D3_malformed", "D4_alg_none", "D5_hs256",
                     "D6_unknown_kid", "D7_forged_signature", "D8_tampered_payload", "D14_expired"):
            self.assertEqual(cases[name]["status"], 401, name)
        self.assertEqual(cases["D9_owner_aal1"]["status"], 403)
        self.assertEqual(cases["D10_non_owner"]["status"], 403)
        self.assertEqual(cases["D11_owner_aal2"]["status"], 200)
        self.assertEqual(cases["D15_unknown_path"]["status"], 404)
        self.assertEqual(cases["D16_wrong_owner_deployment"]["status"], 403)
        for name, action in (("D12_after_sign_out", "sign_out_status"),
                             ("D13_after_password_change", "password_change_status")):
            case = cases[name]
            self.assertEqual((case["before"]["status"], case["after"]["status"]), (200, 401), name)
            self.assertEqual(case["after"]["error"], "session revoked")
            self.assertTrue(case["valid_procedure"], name)
            self.assertIn(case[action], (200, 204))
        self.assertEqual(len(cloud.deleted), 1)
        self.assertEqual(evidence["final_sign_out_status"], 204)
        dumped = json.dumps(evidence)
        for value in cloud.issued + [BYPASS, SECRET, "old-password", "new-password", OWNER_EMAIL]:
            self.assertNotIn(value, dumped)

    def test_cleanup_deletes_only_temporary_users(self):
        cloud = FakeCloud()
        users = [{"id": "u1", "email": OWNER_EMAIL},
                 {"id": "u2", "email": "m5-nonowner-0123456789ab@example.invalid"},
                 {"id": "u3", "email": "m5-nonowner-0123456789ab@example.com"}]
        original = cloud.auth

        def auth(request, body, bearer):
            if request.url.path == "/auth/v1/admin/users" and request.method == "GET":
                return httpx.Response(200, json={"users": users})
            return original(request, body, bearer)

        cloud.auth = auth
        evidence = self.run_script(["cleanup"], cloud)
        self.assertEqual(cloud.deleted, ["u2"])
        self.assertEqual(evidence["remaining_users"], 2)

    def test_refuses_existing_output_and_non_tty(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "evidence.json"
            out.write_text("{}")
            with patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)):
                with self.assertRaisesRegex(SystemExit, "already exists"):
                    script.main(["cleanup", "--out", str(out)])
            with patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: False)):
                with self.assertRaisesRegex(SystemExit, "own terminal"):
                    script.main(["cleanup", "--out", str(Path(directory) / "new.json")])

    def test_rejects_non_probe_urls(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)):
            with self.assertRaisesRegex(SystemExit, "preview URL"):
                script.main(["samples", "--api-url", "https://evil.example/", "--auth-url",
                             f"https://{API_HOST}/", "--out", str(Path(directory) / "x.json")])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_m5_auth_api_matrix -v`
Expected: import ERROR, `cannot import name 'auth_api_matrix'`.

- [ ] **Step 3: Implement** `experiments/m5_cloud/auth_api_matrix.py`:

```python
"""M5 owner-auth probe: deployed negative matrix, A5 samples and cleanup (design §5.2–§5.3).

Run by the OWNER in their own terminal, never through an agent. Refuses non-TTY stdin and an
existing --out file. Secrets (Vercel bypass value, password, TOTP codes, the synthetic sb_secret
key) are read with getpass and stay in memory; the evidence records statuses, error labels,
request IDs, counters and timings, never tokens.

  python -m experiments.m5_cloud.auth_api_matrix matrix  --api-url URL --wrong-owner-url URL --out FILE
  python -m experiments.m5_cloud.auth_api_matrix samples --api-url URL --auth-url URL --out FILE
  python -m experiments.m5_cloud.auth_api_matrix cleanup --out FILE
"""
import argparse
import base64
import getpass
import json
import math
import os
import secrets
import statistics
import sys
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

REF = "acyghoemtdrilsdszolq"
AUTH = f"https://{REF}.supabase.co/auth/v1"
PUBLISHABLE = "sb_publishable_cBTZ7SPZICiMJd1_YTRpkQ_qR7MwzPg"  # Public by design.
API_HOST_PREFIX = "pft-m5-auth-api-20261009-"
NONOWNER_PREFIX, NONOWNER_DOMAIN = "m5-nonowner-", "@example.invalid"
PROBE_HEADERS = ("x-probe-request-id", "x-probe-instance", "x-probe-db-connections",
                 "x-probe-session-checks", "x-probe-data-queries")
BODY_FIELDS = ("aal", "session_check", "identity_ok", "seconds_until_exp", "timings_ms")


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def claims_of(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def forged(real_token):
    """Tokens that differ from a real one only in algorithm, key or signature (cases D3-D8)."""
    header, payload, signature = real_token.split(".")
    claims, kid = claims_of(real_token), jwt.get_unverified_header(real_token)["kid"]
    local = ec.generate_private_key(ec.SECP256R1())
    tampered = b64(json.dumps({**claims, "exp": claims["exp"] + 1}).encode())
    none_header = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": kid}).encode())
    return {
        "D3_malformed": "not-a-jwt",
        "D4_alg_none": f"{none_header}.{payload}.",
        "D5_hs256": jwt.encode(claims, secrets.token_bytes(32), algorithm="HS256", headers={"kid": kid}),
        "D6_unknown_kid": jwt.encode(claims, local, algorithm="ES256",
                                     headers={"kid": "m5-local-" + uuid.uuid4().hex}),
        "D7_forged_signature": jwt.encode(claims, local, algorithm="ES256", headers={"kid": kid}),
        "D8_tampered_payload": f"{header}.{tampered}.{signature}",
    }


def record(response, started=None):
    try:
        body = response.json()
    except ValueError:
        body = None
    body = body if isinstance(body, dict) else {}
    entry = {"status": response.status_code,
             "error": body.get("error") if isinstance(body.get("error"), str) else None}
    for name in PROBE_HEADERS:
        entry[name.removeprefix("x-probe-").replace("-", "_")] = response.headers.get(name)
    for name in BODY_FIELDS:
        if name in body:
            entry[name] = body[name]
    if started is not None:
        entry["client_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return entry


def is_temporary(email):
    return (isinstance(email, str) and email.startswith(NONOWNER_PREFIX) and email.endswith(NONOWNER_DOMAIN)
            and len(email) == len(NONOWNER_PREFIX) + 12 + len(NONOWNER_DOMAIN))


def _stats(values):
    values = sorted(values)
    if not values:
        return None
    return {"n": len(values), "p50": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1], "max": values[-1]}


def summarize(runs):
    ok = [run for run in runs if run["status"] == 200]
    return {"n": len(runs), "non_200": len(runs) - len(ok),
            "status_429": sum(run["status"] == 429 for run in runs),
            "client_ms": _stats([run["client_ms"] for run in ok]),
            **{f"{name}_ms": _stats([run["timings_ms"][name] for run in ok])
               for name in ("total", "connect", "session_check", "data")},
            "note": "p95 of about 30 samples is a sample statistic, not a stable tail estimate"}


class TerminalIO:
    def secret(self, prompt):
        return getpass.getpass(prompt)

    def ask(self, prompt):
        return input(prompt)

    def code(self, prompt="Current 6-digit TOTP code: "):
        return getpass.getpass(prompt).strip().replace(" ", "")

    def tty(self, text):
        with open("/dev/tty", "w") as stream:
            stream.write(text + "\n")

    def sleep(self, seconds):
        time.sleep(seconds)


class Supabase:
    def __init__(self, client):
        self.client = client

    def call(self, method, path, *, bearer=None, apikey=PUBLISHABLE, body=None):
        headers = {"apikey": apikey}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        response = self.client.request(method, AUTH + path, headers=headers, json=body)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data

    def sign_in(self, email, password):
        return self.call("POST", "/token?grant_type=password", body={"email": email, "password": password})

    def refresh(self, refresh_token):
        return self.call("POST", "/token?grant_type=refresh_token", body={"refresh_token": refresh_token})

    def logout(self, access):
        return self.call("POST", "/logout?scope=global", bearer=access, body={})[0]

    def owner_session(self, email, password, io):
        status, session = self.sign_in(email, password)
        if status != 200:
            raise SystemExit(f"owner sign-in failed: {status}")
        _, user = self.call("GET", "/user", bearer=session["access_token"])
        factor = next((f for f in user.get("factors") or []
                       if f.get("factor_type") == "totp" and f.get("status") == "verified"), None)
        if factor is None:
            raise SystemExit("no verified TOTP factor: run auth_owner_flow flow first")
        code = io.code()
        _, challenge = self.call("POST", f"/factors/{factor['id']}/challenge",
                                 bearer=session["access_token"], body={})
        status, upgraded = self.call("POST", f"/factors/{factor['id']}/verify", bearer=session["access_token"],
                                     body={"challenge_id": challenge.get("id"), "code": code})
        if status != 200:
            raise SystemExit(f"TOTP verify failed: {status}")
        return upgraded


class Api:
    def __init__(self, client, bypass):
        self.client, self.bypass = client, bypass

    def get(self, base, path="/probe/whoami", authorization=None):
        headers = {"x-vercel-protection-bypass": self.bypass}
        if authorization is not None:
            headers["authorization"] = authorization
        started = time.perf_counter()
        return record(self.client.get(base.rstrip("/") + path, headers=headers), started)


def _revocation(api, url, bearer, revoke):
    before = api.get(url, authorization=bearer)
    action = revoke()
    after = api.get(url, authorization=bearer)
    valid = before["status"] == 200 and (before.get("seconds_until_exp") or 0) > 120
    return {"before": before, "after": after, "valid_procedure": valid}, action


def matrix(evidence, args, io, client):
    bypass = io.secret("Vercel automation-bypass value for the API project: ")
    secret_key = io.secret("Synthetic project sb_secret key: ")
    if not secret_key.startswith("sb_secret_"):
        raise SystemExit("sb_secret key required")
    email = io.ask("Owner email (synthetic project): ").strip()
    password = io.secret("Current owner password: ")
    supabase, api = Supabase(client), Api(client, bypass)
    cases = evidence["cases"] = {}
    evidence["ping"] = {"api": api.get(args.api_url, "/probe/ping"),
                        "wrong_owner": api.get(args.wrong_owner_url, "/probe/ping")}
    # D9 first: an aal1 session is revoked as soon as another session completes MFA (F5).
    status, aal1 = supabase.sign_in(email, password)
    if status != 200:
        raise SystemExit(f"owner sign-in failed: {status}")
    cases["D9_owner_aal1"] = api.get(args.api_url, authorization="Bearer " + aal1["access_token"])
    nonowner, temp_password = NONOWNER_PREFIX + uuid.uuid4().hex[:12] + NONOWNER_DOMAIN, secrets.token_urlsafe(24)
    status, created = supabase.call("POST", "/admin/users", apikey=secret_key,
                                    body={"email": nonowner, "password": temp_password, "email_confirm": True})
    evidence["nonowner_create_status"] = status
    try:
        status, other = supabase.sign_in(nonowner, temp_password)
        cases["D10_non_owner"] = (api.get(args.api_url, authorization="Bearer " + other["access_token"])
                                  if status == 200 else {"status": None, "error": f"non-owner sign-in {status}"})
    finally:
        if isinstance(created, dict) and created.get("id"):
            evidence["nonowner_delete_status"] = supabase.call(
                "DELETE", f"/admin/users/{created['id']}", apikey=secret_key)[0]
    t2 = supabase.owner_session(email, password, io)
    bearer = "Bearer " + t2["access_token"]
    cases["D1_no_authorization"] = api.get(args.api_url)
    cases["D2_non_bearer"] = api.get(args.api_url, authorization="Basic " + b64(b"owner:x"))
    for name, token in forged(t2["access_token"]).items():
        cases[name] = api.get(args.api_url, authorization="Bearer " + token)
    cases["D15_unknown_path"] = api.get(args.api_url, "/probe/nope", authorization=bearer)
    cases["D11_owner_aal2"] = api.get(args.api_url, authorization=bearer)
    case, status = _revocation(api, args.api_url, bearer, lambda: supabase.logout(t2["access_token"]))
    cases["D12_after_sign_out"] = {**case, "sign_out_status": status}
    t3 = supabase.owner_session(email, password, io)
    new_password = io.secret("NEW owner password (long, unique; store it now): ")
    user_id = claims_of(t3["access_token"])["sub"]
    case, status = _revocation(api, args.api_url, "Bearer " + t3["access_token"], lambda: supabase.call(
        "PUT", f"/admin/users/{user_id}", apikey=secret_key, body={"password": new_password})[0])
    cases["D13_after_password_change"] = {**case, "password_change_status": status}
    t4 = supabase.owner_session(email, new_password, io)
    bearer4 = "Bearer " + t4["access_token"]
    cases["D16_wrong_owner_deployment"] = api.get(args.wrong_owner_url, authorization=bearer4)
    wait = claims_of(t4["access_token"])["exp"] + 35 - time.time()
    io.tty(f"Waiting {max(0, int(wait))} s for natural expiry (D14)...")
    io.sleep(max(0.0, wait))
    cases["D14_expired"] = api.get(args.api_url, authorization=bearer4)
    status, refreshed = supabase.refresh(t4["refresh_token"])
    evidence["final_sign_out_status"] = (supabase.logout(refreshed["access_token"]) if status == 200
                                         else f"refresh {status}")


def samples(evidence, args, io, client, count=30):
    bypass = io.secret("Vercel automation-bypass value for the API project: ")
    email = io.ask("Owner email (synthetic project): ").strip()
    password = io.secret("Current owner password: ")
    supabase, api = Supabase(client), Api(client, bypass)
    session = supabase.owner_session(email, password, io)
    bearer = "Bearer " + session["access_token"]
    for mode, url in (("db", args.api_url), ("auth", args.auth_url)):
        runs = [api.get(url, authorization=bearer) for _ in range(count + 1)]
        evidence[mode] = {"first": runs[0], "warm": runs[1:], "summary": summarize(runs[1:])}
    evidence["sign_out_status"] = supabase.logout(session["access_token"])


def cleanup(evidence, args, io, client):
    secret_key = io.secret("Synthetic project sb_secret key: ")
    if not secret_key.startswith("sb_secret_"):
        raise SystemExit("sb_secret key required")
    supabase = Supabase(client)
    status, listed = supabase.call("GET", "/admin/users?page=1&per_page=1000", apikey=secret_key)
    users = listed.get("users", []) if isinstance(listed, dict) else []
    doomed = [user for user in users if is_temporary(user.get("email"))]
    evidence["list_status"] = status
    evidence["deleted"] = [supabase.call("DELETE", f"/admin/users/{user['id']}", apikey=secret_key)[0]
                           for user in doomed]
    evidence["remaining_users"] = len(users) - len(doomed)


COMMANDS = {"matrix": (matrix, ("api_url", "wrong_owner_url")),
            "samples": (samples, ("api_url", "auth_url")),
            "cleanup": (cleanup, ())}


def main(argv=None, io=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--api-url")
    parser.add_argument("--wrong-owner-url")
    parser.add_argument("--auth-url")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        raise SystemExit("Run this in your own terminal, not through an agent.")
    if os.path.exists(args.out):
        raise SystemExit(f"{args.out} already exists; choose a new file name so earlier evidence is kept.")
    command, required = COMMANDS[args.command]
    for name in required:
        url = httpx.URL(getattr(args, name) or "")
        if url.scheme != "https" or not url.host.startswith(API_HOST_PREFIX):
            raise SystemExit(f"--{name.replace('_', '-')} must be an https preview URL of pft-m5-auth-api-20261009")
    evidence = {"kind": "m5_auth_probe_" + args.command, "project_ref": REF, "started_unix": int(time.time())}
    try:
        with (client or httpx.Client(timeout=20.0)) as http:
            command(evidence, args, io or TerminalIO(), http)
    finally:
        with open(args.out, "w") as stream:
            json.dump(evidence, stream, indent=2)
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_m5_auth_api_matrix -v`
Expected: all OK.

- [ ] **Step 5: Checkpoint (owner commits).** Files: the two above. Message: `Add the owner-run M5 auth probe matrix, samples and cleanup script`.

---

### Task 8: Staging script

**Files:**
- Create: `scripts/pft_m5_stage_auth_probe.py`
- Create: `tests/test_m5_stage_auth_probe.py`

**Interfaces:**
- Consumes: `deploy.backup_runner.stage_backup_repo.CA_SHA256`, `scripts.pft_m5_prepare_cloud_bundle.check_entrypoints`, and the files from Tasks 3 and 6.
- Produces: `stage(destination) -> {"api": [sum lines], "web": [sum lines]}` and the constants `MAIN_PY` and `WEB_SOURCE`. CLI: `python -m scripts.pft_m5_stage_auth_probe --destination DIR`.

- [ ] **Step 1: Write the failing tests** `tests/test_m5_stage_auth_probe.py`:

```python
"""Staging of the M5 owner-auth probe upload directories (design §3 unit 4). No cloud calls."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import pft_m5_stage_auth_probe as staging

ROOT = Path(__file__).resolve().parents[1]


def sums(path):
    return dict(reversed(line.split("  ", 1)) for line in path.read_text().splitlines())


class StageTests(unittest.TestCase):
    def test_layout_requirements_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "stage"
            staging.stage(target)
            api = target / "api"
            self.assertEqual((api / "main.py").read_text(), staging.MAIN_PY)
            for relative in staging.API_SOURCES:
                self.assertEqual((api / relative).read_bytes(), (ROOT / relative).read_bytes())
            self.assertEqual(sums(api / "SHA256SUMS")["experiments/m5_cloud/auth_probe.py"],
                             hashlib.sha256((ROOT / "experiments/m5_cloud/auth_probe.py").read_bytes()).hexdigest())
            requirements = (api / "requirements.txt").read_text().splitlines()
            self.assertEqual(requirements[-2:], ["PyJWT[crypto]==2.10.1", "httpx==0.28.1"])
            self.assertFalse(any(line.lower().startswith(("plaid", "uvicorn")) for line in requirements))
            self.assertIn("BEGIN CERTIFICATE", (api / "supabase-ca.crt").read_text())
            web = target / "web"
            self.assertTrue((web / "package.json").exists() and (web / "package-lock.json").exists())
            self.assertFalse([p for p in web.rglob("*") if {"node_modules", ".next"} & set(p.parts)])
            self.assertIn("lib/forward.mjs", sums(web / "SHA256SUMS"))

    def test_refuses_repository_or_existing_destination(self):
        with self.assertRaises(RuntimeError):
            staging.stage(ROOT / "tmp-stage")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                staging.stage(Path(directory))

    def test_rejects_env_files_in_the_web_source(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as directory:
            (Path(source) / "package.json").write_text("{}")
            (Path(source) / ".env.local").write_text("X=1")
            with patch.object(staging, "WEB_SOURCE", Path(source)):
                with self.assertRaisesRegex(RuntimeError, "Rejected web file"):
                    staging.stage(Path(directory) / "stage")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_m5_stage_auth_probe -v`
Expected: import ERROR, `cannot import name 'pft_m5_stage_auth_probe'`.

- [ ] **Step 3: Implement** `scripts/pft_m5_stage_auth_probe.py`:

```python
"""Stage the M5 owner-auth probe upload directories (design §3 unit 4); no cloud calls.

  python -m scripts.pft_m5_stage_auth_probe --destination DIR

DIR/api: main.py wrapper, experiments/m5_cloud/{auth_probe,auth_api_probe}.py, requirements.txt,
         .python-version, vercel.json, supabase-ca.crt (pinned fingerprint), SHA256SUMS.
DIR/web: experiments/m5_cloud/auth_web_probe without node_modules/.next/.vercel, SHA256SUMS.
The destination must be new and outside the repository; env files are never copied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import ssl

from deploy.backup_runner.stage_backup_repo import CA_SHA256
from scripts.pft_m5_prepare_cloud_bundle import check_entrypoints

ROOT = Path(__file__).resolve().parents[1]
API_SOURCES = ("experiments/m5_cloud/auth_probe.py", "experiments/m5_cloud/auth_api_probe.py")
WEB_SOURCE = ROOT / "experiments" / "m5_cloud" / "auth_web_probe"
WEB_EXCLUDED_DIRS = {"node_modules", ".next", ".vercel"}
PINNED = ("fastapi==", "SQLAlchemy==", "asyncpg==", "cryptography==")
EXTRA_REQUIREMENTS = ("PyJWT[crypto]==2.10.1", "httpx==0.28.1")
MAIN_PY = '''"""Vercel entrypoint for the M5 owner-auth API probe (generated by staging; do not edit)."""
from experiments.m5_cloud.auth_api_probe import create_app, load_settings

app = create_app(load_settings())
'''


def requirements():
    lines = [line for line in (ROOT / "api" / "requirements.txt").read_text().splitlines()
             if line.startswith(PINNED)]
    if len(lines) != len(PINNED):
        raise RuntimeError("api/requirements.txt pins changed; review the probe bundle")
    return "\n".join([*lines, *EXTRA_REQUIREMENTS]) + "\n"


def ca_pem():
    pem = (ROOT / "deploy" / "backup_runner" / "supabase-ca.crt").read_text()
    if "PRIVATE KEY" in pem or hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != CA_SHA256:
        raise RuntimeError("supabase-ca.crt does not match the pinned certificate fingerprint")
    return pem


def web_files():
    files = []
    for path in sorted(WEB_SOURCE.rglob("*")):
        relative = path.relative_to(WEB_SOURCE)
        if WEB_EXCLUDED_DIRS & set(relative.parts):
            continue
        if path.is_symlink() or path.name.startswith(".env"):
            raise RuntimeError(f"Rejected web file: {relative}")
        if path.is_file():
            files.append(path)
    return files


def write_sums(directory):
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(directory).as_posix()}"
             for path in sorted(directory.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return lines


def stage(destination):
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(ROOT):
        raise RuntimeError("Requires a fresh destination outside the repository")
    api_files = {relative: (ROOT / relative).read_text() for relative in API_SOURCES}
    check_entrypoints(["main.py", *API_SOURCES], {"main.py": MAIN_PY, **api_files})
    generated = {**api_files, "main.py": MAIN_PY, "requirements.txt": requirements(),
                 ".python-version": "3.12\n", "supabase-ca.crt": ca_pem(),
                 "vercel.json": json.dumps({"functions": {"main.py": {"maxDuration": 30}}}, indent=2) + "\n"}
    sources = web_files()
    api, web = destination / "api", destination / "web"
    for relative, content in generated.items():
        target = api / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text(content)
    for path in sources:
        target = web / path.relative_to(WEB_SOURCE)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return {"api": write_sums(api), "web": write_sums(web)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destination", type=Path, required=True)
    result = stage(parser.parse_args().destination)
    print(json.dumps({name: len(lines) for name, lines in result.items()}))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_m5_stage_auth_probe -v`
Expected: 3 tests OK.

- [ ] **Step 5: Checkpoint (owner commits).** Files: the two above. Message: `Add staging for the M5 owner-auth probe upload directories`.

---

### Task 9: Full local verification

**Files:** none new. This task runs the CI-equivalent checks over everything above.

- [ ] **Step 1: Backend, CI-equivalent.** Use the disposable cluster from the environment section, with the checksum-pinned age v1.3.2 on `PATH` (as in `.github/workflows/ci.yml`, so the backup tests do not skip):

```bash
A=${CLAUDE_JOB_DIR:-$(mktemp -d)}/tmp/age-v1.3.2; mkdir -p "$A"
curl -fsSL -o "$A/age.tgz" https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz
echo "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10  $A/age.tgz" | sha256sum -c -
tar -xzf "$A/age.tgz" -C "$A"
PATH="$A/age:$PATH" .venv/bin/python scripts/ci_backend_tests.py
```

Expected: `backend: executed=N, failures=0, errors=0, skipped=0`, where N includes the new modules `test_m5_auth_session_sql` (8), `test_m5_auth_api_probe`, `test_m5_auth_api_db` (7), `test_m5_auth_api_matrix` and `test_m5_stage_auth_probe` (3).

- [ ] **Step 2: Frontend, both apps.**

```bash
npm ci && npm test -- --ci && npx --no-install tsc --noEmit && NEXT_TELEMETRY_DISABLED=1 npm run build
(cd experiments/m5_cloud/auth_web_probe && npm ci && npm test)
git restore tsconfig.tsbuildinfo 2>/dev/null; true
```

Expected: the root jest, tsc and build pass unchanged; the probe's `node:test` passes.

- [ ] **Step 3: Hygiene.**

```bash
git diff --check
git status --short
git diff | grep -nEi 'eyJ[a-zA-Z0-9_-]{10,}|sb_secret_[A-Za-z0-9]|otpauth://' || echo clean
```

Expected:
- `git diff --check` is clean;
- only the planned files are listed, with no `node_modules` or `.next`;
- the secret scan prints `clean` (`sb_secret_fake` appears only in tests as a fake value; check every hit).

- [ ] **Step 4: Stop the disposable cluster** (environment section) and report results to the owner. Final checkpoint: the owner commits anything still uncommitted, then runs `git push -u origin m5/g6-auth`.

---

## Phase 2 — gated cloud steps (design §6). Do NOT start without the owner's approval for EACH step.

Commands run from a fresh staging directory **outside** the repository, `STAGE=$(mktemp -d)/stage`. The agent never sees secret values. Vercel `rm` and `env rm` are owner-only (user-level rules).

**Stop rule:** if any step fails or behaves unexpectedly, stop at once. Record the state in the evidence directory, run only the S7 cleanup items for what was already created, and wait for the owner. Never improvise a fix in the cloud.

| Step | Who | Exact action | Pass condition / stop rule |
| --- | --- | --- | --- |
| **S0** read-only | agent and owner | Agent: Supabase MCP `get_project` for `acyghoemtdrilsdszolq` (ACTIVE_HEALTHY, Free); refresh the Vercel Hobby and Supabase Free limits from the official docs. Owner: in the dashboard, find the access-token (JWT) expiry setting, record the current value, confirm it is editable on Free | Any paid prerequisite or a non-editable expiry: stop and record (design §10) |
| **S1** state | agent, via MCP | `apply_migration` name `m5_auth_probe` with the exact contents of `experiments/m5_cloud/auth_session_probe.sql`. Then `execute_sql` with the **S1 check SQL** below, and `get_advisors` (security) | Every check as expected and no 0028/0029 finding for the function. Otherwise apply `auth_session_probe_teardown.sql` as migration `m5_auth_probe_teardown`, record the reason, and stop. Switching to D is a separate owner decision (K3) |
| **S2** state | owner | SQL editor: `alter role pft_m5_authprobe password '<generated>';` (typed by the owner). Dashboard: access-token expiry → **300 s**; note the previous value | — |
| **S3** state | owner, agent prepares | Agent runs `.venv/bin/python -m scripts.pft_m5_stage_auth_probe --destination "$STAGE"` (STAGE outside the repo). Owner or agent: `vercel project add pft-m5-auth-api-20261009 --scope pft2` and `vercel project add pft-m5-auth-web-20261009 --scope pft2`; `(cd "$STAGE/api" && vercel link --yes --project pft-m5-auth-api-20261009 --scope pft2)` and `(cd "$STAGE/web" && vercel link --yes --project pft-m5-auth-web-20261009 --scope pft2)` | Non-secret preview env, API: `M5_VERCEL_PROJECT_NAME`, `M5_SUPABASE_PROJECT_REF`, `M5_OWNER_AUTH_SUB`, `M5_SUPABASE_PUBLISHABLE_KEY`. Owner sets secrets from stdin: `( read -rsp 'DATABASE_URL: ' V && echo && printf %s "$V" \| vercel env add DATABASE_URL preview --scope pft2 )`. Owner creates the API **automation bypass** in the dashboard and sets it on the web project as `M5_API_PROTECTION_BYPASS` the same way |
| **S4** state | agent | In `$STAGE/api`: `vercel deploy --yes --scope pft2 --env M5_SESSION_CHECK=db` → DB_URL; `… --env M5_SESSION_CHECK=auth` → AUTH_URL; `… --env M5_SESSION_CHECK=db --env M5_OWNER_AUTH_SUB=$(python3 -c 'import uuid; print(uuid.uuid4())')` → WRONG_URL. Set web env `M5_API_URL=DB_URL`, `M5_API_HOST`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`; then in `$STAGE/web`: `vercel deploy --yes --scope pft2` → WEB_URL. Record deployment IDs and `SHA256SUMS` | Previews only (no `--prod`). Whether `--env` overrides project env is 未核实: the matrix ping and D16 prove it; if D16 returns 200, stop |
| **S5** measurement | owner | Browser B1–B8 and P1–P5 on WEB_URL (procedure below the table); save the probe page's "Copy evidence JSON" output and screenshots of redirects. Then `python -m experiments.m5_cloud.auth_api_matrix matrix --api-url DB_URL --wrong-owner-url WRONG_URL --out docs/evidence/m5-YYYY-MM-DD/auth-probe/matrix-db.json`; the same with `--api-url AUTH_URL` → `matrix-auth.json`; then `samples --api-url DB_URL --auth-url AUTH_URL --out …/samples.json` | Design §5. Each matrix run changes the owner password once (D13); store it immediately |
| **S6** state | owner | Dashboard: access-token expiry → **600 s** (D5); repeat B4/B5 once | Record the final value |
| **S7** state | owner, then agent | Owner: remove the deployments and both projects, their env and the bypass. Agent: MCP `apply_migration` `m5_auth_probe_teardown` (teardown file); `execute_sql` checks below; if the matrix was interrupted, the owner runs `auth_api_matrix cleanup` | No role, function or temporary user left; `count(*) from auth.users = 1`; expiry = 600 s |

**S5 browser procedure:**
- **P1, P3 and P5:** use the login page's "Call the route now" button:
  - P1 before signing in;
  - P3 after the password step only;
  - P5 after the global sign-out.
- **P2:** edit the `sb-acyghoemtdrilsdszolq-auth-token` cookie (or its `.0`/`.1` chunks) in devtools, then call the route.
- **P4:** use "Fetch whoami" on `/probe`.
- **B8:** a page restored from the browser's back-forward cache may appear after **Back**. Record it. Its "Fetch whoami" must return 401, and a reload must land on `/login`.

**S1 check SQL** (read-only):

```sql
select r.rolname,
       has_function_privilege(r.oid, 'pft_m5_probe.owner_session_alive(uuid,uuid)', 'EXECUTE') as can_execute
from pg_roles r
where r.rolname in ('pft_m5_authprobe', 'anon', 'authenticated', 'service_role',
                    'pft_m5_reader', 'pft_m5_jobs', 'pft_backup', 'postgres')
order by 1;
select has_table_privilege('pft_m5_authprobe', 'auth.sessions', 'SELECT') as probe_reads_sessions,
       has_schema_privilege('pft_m5_authprobe', 'auth', 'USAGE') as probe_auth_usage;
select p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) as owner
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'pft_m5_probe' and p.proname = 'owner_session_alive';
select rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolconnlimit, rolconfig
from pg_roles where rolname = 'pft_m5_authprobe';
-- the owner role can read auth.sessions through the function (returns false, no error)
select pft_m5_probe.owner_session_alive(gen_random_uuid(), gen_random_uuid()) as alive_random;
```

Expected:
- `can_execute` is true only for `pft_m5_authprobe` and the owner role (`postgres`);
- both privilege flags are false;
- `prosecdef` is true and `proconfig` is `{search_path=""}`;
- the role row is `f,f,f,f,f,4` with `default_transaction_read_only=on`;
- `alive_random` is `false`.

**S7 check SQL** (read-only):

```sql
select (select count(*) from pg_roles where rolname = 'pft_m5_authprobe') as probe_roles,
       to_regprocedure('pft_m5_probe.owner_session_alive(uuid,uuid)') as function,
       (select count(*) from auth.users) as users;
```

Expected: `0 | NULL | 1`.

## Phase 3 — record (after S5–S7)

The agent reads the S5 evidence. It updates `docs/PFT_M5_OWNER_AUTH_ACCEPTANCE_2026-10-08.md` (A2, A3 and A5 with evidence tiers, D12–D13 procedure validity, and the A5 sample statistics with their caveat), the G6 row of `docs/PFT_M5_GATE_ACCEPTANCE_DRAFT_2026-10-09.md`, and the inventory. It does not assert SERVERLESS_GO. The owner commits.
