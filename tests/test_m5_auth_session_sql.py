"""Privileges and semantics of pft_m5_probe.owner_session_alive (design §2.6, §7, K1).

Applies the real migration file to a fresh database on the disposable loopback cluster.
Needs PFT_M5_AUTH_SYNTHETIC_TEST=1.
"""
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
import uuid

OWNER = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"
SIGNATURE = "pft_m5_probe.owner_session_alive(uuid,uuid)"


async def close_quietly(connection):
    """Close a connection during cleanup; one a test already closed, or the server dropped, is fine."""
    try:
        await connection.close()
    except Exception:
        connection.terminate()


@unittest.skipUnless(os.environ.get("PFT_M5_AUTH_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class SessionFunctionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests import m5_auth_pg
        self.pg = m5_auth_pg
        self.name = await m5_auth_pg.create_fixture()
        # Cleanups run last-in first-out and also when a later step of this setup fails, which
        # asyncTearDown would not: probe connection, admin connection, then database and roles.
        self.addAsyncCleanup(m5_auth_pg.drop_fixture, self.name)
        self.admin = await m5_auth_pg.admin_connect(self.name)
        self.addAsyncCleanup(self.close_admin)
        self.probe = await m5_auth_pg.probe_connect(self.name)
        self.addAsyncCleanup(self.close_probe)

    async def close_admin(self):
        await close_quietly(self.admin)

    async def close_probe(self):
        # Two tests close the probe connection and replace it: close whichever is current.
        await close_quietly(self.probe)

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
            "SELECT p.prosecdef, p.proconfig, p.provolatile::text FROM pg_proc p "
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


@unittest.skipUnless(os.environ.get("PFT_M5_AUTH_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class FixtureCleanupTests(unittest.IsolatedAsyncioTestCase):
    """The roles are cluster-wide. A database leaked by a failed create_fixture() that already holds
    the migration's grants makes DROP ROLE fail, and with it every later create_fixture()."""

    async def test_failed_create_fixture_leaves_no_database_or_roles(self):
        import asyncpg
        from tests import m5_auth_pg as pg
        admin = await pg.admin_connect()
        self.addAsyncCleanup(close_quietly, admin)

        async def leftovers():
            databases = {row["datname"] for row in await admin.fetch(
                "SELECT datname FROM pg_database WHERE datname LIKE 'pft_m5_auth\\_%'")}
            roles = {row["rolname"] for row in await admin.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname::text = ANY($1::text[])",
                [pg.PROBE_ROLE, *pg.SUPABASE_ROLES, *pg.OTHER_ROLES])}
            return databases, roles

        failures = {
            # Fails right after CREATE DATABASE, the roles and the stand-in tables exist.
            "migration file missing": (
                patch.object(pg, "MIGRATION", pg.MIGRATION.with_name("does_not_exist.sql")),
                FileNotFoundError),
            # Fails after the migration committed, so the probe role already holds grants in the new
            # database. The quote breaks the final ALTER ROLE ... PASSWORD statement.
            "password statement fails": (
                patch.object(pg, "PROBE_PASSWORD", "bad'password"),
                asyncpg.PostgresSyntaxError),
        }
        for label, (forced, error) in failures.items():
            with self.subTest(label):
                before, _ = await leftovers()
                with forced, self.assertRaises(error):
                    await pg.create_fixture()
                databases, roles = await leftovers()
                self.assertEqual(databases - before, set())
                self.assertEqual(roles, set())
