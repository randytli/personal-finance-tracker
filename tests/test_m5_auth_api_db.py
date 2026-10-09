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


async def close_quietly(connection):
    """Close a connection during cleanup; one a test already closed, or the server dropped, is fine."""
    try:
        await connection.close()
    except Exception:
        connection.terminate()


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
        # Cleanups run last-in first-out and also when a later step of this setup fails, which
        # asyncTearDown would not: HTTP client, engine, admin connection, then database and roles.
        self.addAsyncCleanup(self.pg.drop_fixture, self.name)
        self.admin = await m5_auth_pg.admin_connect(self.name)
        self.addAsyncCleanup(close_quietly, self.admin)
        self.key = ec_key()
        jwks = {"keys": [public_jwk(self.key, "kid-1")]}
        verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=OWNER), fetch=lambda url: jwks)
        url = m5_auth_pg.probe_url(self.name)
        self.engine = create_async_engine(url, poolclass=NullPool,
                                          connect_args={"timeout": 5, "command_timeout": 5})
        self.addAsyncCleanup(self.engine.dispose)
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(_no_auth_calls))
        self.addAsyncCleanup(self.http.aclose)
        self.app = create_app(Settings(REF, OWNER, url, "db", "sb_publishable_test"),
                              verifier=verifier, engine=self.engine, http=self.http, instance="pg-test")

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

    async def wait_for_session_check(self, task, timeout=5.0):
        """Return once a probe-role backend is running the session check; fail otherwise.

        Cancelling before the probe holds a connection would pass without exercising release.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if task.done():
                await asyncio.gather(task, return_exceptions=True)
                self.fail("the request finished before its session check was observed")
            if await self.admin.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE usename = 'pft_m5_authprobe' "
                    "AND state = 'active' AND query LIKE '%owner_session_alive%'"):
                return
            await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.fail("the probe never reached its session check; cancellation would prove nothing")

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
        await self.wait_for_session_check(task)
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
