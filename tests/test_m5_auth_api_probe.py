"""Tier L unit tests for the M5 owner-auth API probe (design §5.2, §7). No network, no database.

Each claim rule is proven here with a trusted local test key; the deployed run (Tier D)
proves the real trust boundary. The deployed verifier has no test-key input.
"""
import base64
import json
import time
import unittest
from unittest.mock import Mock
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
            "sb_secret value anywhere": {"UNRELATED": "sb_secret_fake"},
            "plaid secret": {"PLAID_SECRET": "x"},
            "wrong project": {"M5_VERCEL_PROJECT_NAME": "pft-m5-reader-20261001"},
            "other well-formed project ref": {"M5_SUPABASE_PROJECT_REF": "a" * 20,
                                              "DATABASE_URL": VALID_URL.replace(REF, "a" * 20)},
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
        self.verifier = verifier
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

    async def test_jwks_failure_stays_503_until_throttled_retry_recovers(self):
        now = [1000.0]
        self.verifier._clock = lambda: now[0]
        self.fetch_error = urllib.error.URLError("down")
        token = "Bearer " + mint(self.key)
        for index in range(3):
            if index == 2:
                self.fetch_error = None  # Recovery must not bypass the 60-second throttle.
            response = await self.call(token)
            self.assertEqual((response.status_code, response.json()["error"]),
                             (503, "auth keys unavailable"))
            self.assert_counters(response, 0, 0, 0)
        self.assertEqual(self.verifier.fetches, 1)
        self.assertEqual(self.engine.connections, [])
        now[0] += 60
        response = await self.call(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.verifier.fetches, 2)
        response = await self.call("Bearer " + mint(self.key, kid="missing"))
        self.assertEqual((response.status_code, response.json()["error"]),
                         (401, "unknown signing key"))
        self.assert_counters(response, 0, 0, 0)
        self.assertEqual(self.verifier.fetches, 2)

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

    async def test_unexpected_errors_are_generic_500_with_diagnostics(self):
        # The last boundary: every response keeps no-store and its counters, and no detail is echoed.
        self.engine.data_result = RuntimeError("detail-from-the-data-path")
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()), (500, {"error": "internal error"}))
        self.assertNotIn("detail-from", response.text)
        self.assert_counters(response, 1, 1, 0)
        self.assertEqual(self.engine.closed, 1)
        self.verifier.verify = Mock(side_effect=RuntimeError("detail-from-the-verifier"))
        response = await self.call("Bearer " + mint(self.key))
        self.assertEqual((response.status_code, response.json()), (500, {"error": "internal error"}))
        self.assertNotIn("detail-from", response.text)
        self.assert_counters(response, 0, 0, 0)
        self.assertEqual(len(self.engine.connections), 1)

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
