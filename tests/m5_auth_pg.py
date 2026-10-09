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
    try:
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
    except BaseException:
        # The roles are cluster-wide: a leaked database that holds the migration's grants would
        # make DROP ROLE fail at the start of every later create_fixture(). Also on cancellation.
        await drop_fixture(name)
        raise
    return name


async def drop_fixture(name):
    """Safe to call again, and for a database that was never created."""
    admin = await admin_connect()
    try:
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = $1 AND pid <> pg_backend_pid()", name)
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await _drop_roles(admin)
    finally:
        await admin.close()
