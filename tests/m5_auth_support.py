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
