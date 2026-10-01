"""Disposable authenticated M5 probe. Does not expose api.main or Plaid routes.

Not a production adapter or an owner-Auth implementation. Service capability
tokens must be newly generated for these exact synthetic projects. No .env loads.
"""
import asyncio
from dataclasses import dataclass
import hmac
import importlib
import importlib.metadata
import os
import platform
import re
import shutil
import ssl
import sys
import tempfile
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

APP_INSTANCE = uuid.uuid4().hex
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Root-relative application imports to prove in the real runtime. Import only:
# nothing here is called, and api.main (financial routes, lifespan) is excluded.
SHARED_MODULES = ("api.models", "api.statement_semantics", "api.services.derivation",
                  "statement_imports", "statement_imports.persistence")
ROLE_MODULES = {
    "reader": ("api.routes.analytics", "api.routes.review"),
    "jobs": ("api.services.sync_all", "api.jobs", "api.backup", "api.backup_crypto"),
}


@dataclass(frozen=True)
class Settings:
    role: str
    url: str
    project_ref: str
    database_role: str
    dataset_id: str
    deployment_id: str


def settings(environ=None):
    env = os.environ if environ is None else environ
    if env.get("PLAID_ENV", "").lower() == "production":
        raise RuntimeError("Production forbidden")
    if any(env.get(name) for name in ("PLAID_SECRET", "PLAID_TOKEN_ENCRYPTION_KEY", "PLAID_CLIENT_ID")):
        raise RuntimeError("Plaid credentials forbidden in probe")
    role = env.get("M5_PROBE_ROLE")
    if role not in {"reader", "jobs"}:
        raise RuntimeError("Missing synthetic capability role")
    ref = env.get("M5_SUPABASE_PROJECT_REF", "")
    if not re.fullmatch(r"[a-z]{20}", ref):
        raise RuntimeError("Missing synthetic project pin")
    expected_project = f"pft-m5-{role}-20261001"
    if env.get("M5_VERCEL_PROJECT_NAME") != expected_project:
        raise RuntimeError("Wrong experiment project")
    url = env.get("DATABASE_URL", "")
    parsed = make_url(url)
    dbrole = "pft_m5_" + role
    direct = parsed.host == f"db.{ref}.supabase.co" and parsed.username == dbrole
    session = bool(re.fullmatch(r"aws-\d+-[a-z0-9-]+\.pooler\.supabase\.com", parsed.host or ""))
    session = session and parsed.username == f"{dbrole}.{ref}"
    if (parsed.drivername != "postgresql+asyncpg" or parsed.database != "postgres"
            or parsed.port not in {None, 5432} or not parsed.password or not (direct or session)
            or parsed.query):
        raise RuntimeError("Requires pinned synthetic direct/session URL without query overrides")
    identifiers = [env.get("M5_DATASET_ID", ""), env.get("M5_DEPLOYMENT_ID", "")]
    if not all(re.fullmatch(r"m5-[a-f0-9]{32}", value) for value in identifiers):
        raise RuntimeError("Missing synthetic identity")
    return Settings(role, url, ref, dbrole, *identifiers)


async def capability(request: Request):
    expected = os.environ.get("M5_PROBE_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    if len(expected) < 32 or not hmac.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(401, "Probe capability required")
    try:
        return settings()
    except Exception:
        raise HTTPException(503, "Probe configuration rejected") from None


def new_engine(config, pool):
    options = {"poolclass": NullPool} if pool == "null" else {"pool_size": 4, "max_overflow": 0}
    return create_async_engine(config.url, pool_pre_ping=True, pool_timeout=5,
        connect_args={"ssl": ssl.create_default_context(), "timeout": 10, "command_timeout": 15},
        **options) if pool != "null" else create_async_engine(config.url,
        connect_args={"ssl": ssl.create_default_context(), "timeout": 10, "command_timeout": 15},
        **options)


async def identity(connection, config):
    row = (await connection.execute(text(
        "select current_database(), current_user, pg_backend_pid(), "
        "(select ssl from pg_stat_ssl where pid=pg_backend_pid())"))).one()
    if row[0] != "postgres" or row[1] != config.database_role or row[3] is not True:
        raise RuntimeError("DB role/TLS identity rejected")
    sentinel = (await connection.execute(text(
        "select dataset_id, deployment_id, project_ref from pft_m5_probe.identity where singleton=true"))).one()
    if tuple(sentinel) != (config.dataset_id, config.deployment_id, config.project_ref):
        raise RuntimeError("Synthetic dataset/deployment/project identity rejected")
    return row[2]


@app.get("/probe/runtime")
async def runtime(config: Settings = Depends(capability)):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="pft-m5-") as directory:
        source = os.path.join(directory, "source")
        target = os.path.join(directory, "linked")
        with open(source, "xb") as stream:
            stream.write(b"synthetic-runtime-probe")
        os.chmod(source, 0o600)
        os.link(source, target)
        with open(target, "rb") as stream:
            assert stream.read() == b"synthetic-runtime-probe"
        available = shutil.disk_usage(directory).free
    return {"kind": "runtime_probe", "instance_id": APP_INSTANCE, "python": platform.python_version(),
        "role": config.role, "elapsed_s": time.perf_counter()-started,
        "temporary_free_bytes": available, "private_write_hardlink_cleanup": True,
        "pg_dump_present": shutil.which("pg_dump") is not None,
        "dependencies": {name: importlib.metadata.version(name) for name in
            ("fastapi", "SQLAlchemy", "asyncpg", "plaid-python", "cryptography")}}


@app.get("/probe/imports")
async def import_probe(config: Settings = Depends(capability)):
    results = []
    for name in SHARED_MODULES + ROLE_MODULES[config.role]:
        cached = name in sys.modules
        started = time.perf_counter()
        try:
            importlib.import_module(name)
            error = None
        except Exception as exc:
            # Type and missing module name only; messages may echo configuration.
            error = {"type": type(exc).__name__, "missing_module": getattr(exc, "name", None)}
        results.append({"module": name, "ok": error is None, "already_loaded": cached,
                        "import_s": time.perf_counter()-started, "error": error})
    # Importing api.db builds a module-level engine; record it, never use it.
    global_engine = getattr(sys.modules.get("api.db"), "engine", None)
    pool = global_engine.pool if global_engine is not None else None
    return {"kind": "import_probe", "instance_id": APP_INSTANCE, "role": config.role,
        "all_ok": all(result["ok"] for result in results), "modules": results,
        "api_main_loaded": "api.main" in sys.modules,
        "global_engine": None if pool is None else {"pool": type(pool).__name__,
            "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else None}}


@app.get("/probe/connection")
async def connection_probe(pool: str = "null", config: Settings = Depends(capability)):
    if pool not in {"null", "small"}:
        raise HTTPException(422, "Unknown pool")
    start = time.perf_counter()
    engine = new_engine(config, pool)
    try:
        async with engine.connect() as connection:
            pid = await identity(connection, config)
            await connection.commit()
            prepared = await connection.scalar(text("select cast(:value as integer) + 1"), {"value": 41})
            stable = pid == await connection.scalar(text("select pg_backend_pid()"))
        return {"kind": "connection_probe", "instance_id": APP_INSTANCE, "pool": pool,
            "wall_s": time.perf_counter()-start, "backend_pid": pid, "pid_stable_after_commit": stable,
            "prepared_query_result": prepared, "verified_tls_context": True}
    finally:
        await engine.dispose()


@app.post("/probe/locks")
async def lock_probe(config: Settings = Depends(capability)):
    if config.role != "jobs":
        raise HTTPException(403, "Jobs capability required")
    engine = new_engine(config, "small")
    key = "pft-m5-probe:" + config.dataset_id
    try:
        async with asyncio.timeout(25), engine.connect() as owner:
            pid = await identity(owner, config)
            await owner.commit()
            acquired = await owner.scalar(text("select pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key})
            await owner.commit()
            if not acquired:
                raise HTTPException(409, "Synthetic probe lock busy")
            try:
                async with engine.connect() as contender:
                    await identity(contender, config)
                    denied = not await contender.scalar(text(
                        "select pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key})
                    if not denied:
                        await contender.scalar(text(
                            "select pg_advisory_unlock(hashtextextended(:key,0))"), {"key": key})
                        raise RuntimeError("Session ownership did not exclude contender")
                stable = pid == await owner.scalar(text("select pg_backend_pid()"))
            finally:
                try:
                    await owner.scalar(text("select pg_advisory_unlock(hashtextextended(:key,0))"), {"key": key})
                    await owner.commit()
                except BaseException:
                    await owner.invalidate()
                    raise
        return {"kind": "session_lock_probe", "instance_id": APP_INSTANCE,
                "contender_denied": denied, "pid_stable": stable}
    finally:
        await engine.dispose()
