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
PROJECT_REF = "acyghoemtdrilsdszolq"  # the synthetic project; any other ref is refused at startup
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
    if ref != PROJECT_REF:
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
            diag.timed("total", started)
            claims = owner.claims
            body = {
                "kind": "m5_auth_whoami", "aal": claims.get("aal"), "iat": claims.get("iat"),
                "exp": claims.get("exp"), "seconds_until_exp": int(claims["exp"] - time.time()),
                "session_check": settings.session_check,
                "identity_ok": project_ref == settings.project_ref, "timings_ms": diag.timings_ms}
        except ProbeError as error:
            return diag.respond(error.status, {"error": error.reason})
        except Exception:
            # Last boundary: an unexpected failure still fails closed with no-store and this request's
            # counters, and echoes no detail. Cancellation is a BaseException and still propagates.
            return diag.respond(500, {"error": "internal error"})
        return diag.respond(200, body)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        reason = "not found" if exc.status_code == 404 else "rejected"
        return Diagnostics(instance).respond(exc.status_code, {"error": reason})

    return app
