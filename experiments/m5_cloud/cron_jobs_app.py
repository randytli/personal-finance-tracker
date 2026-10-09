"""M5 cron acceptance: signed one-shot jobs endpoint on Vercel (synthetic only).

Deployed as ``main.py``. One route, ``POST /trigger``: HMAC verification and a
single-use nonce (api.trigger_auth), then exactly one ``api.jobs.tick`` with
``backup_fn=None`` against the private ``pft_m5_cron`` schema. The Plaid
client is the database-driven synthetic FixtureClient; no real SDK call, no
Plaid credentials, no backup, no financial route.

The application deadline is 210 s (0.70 of D = 300 s, the configured Vercel
maxDuration), leaving 90 s for failure finalization, lock release and response.

Every authenticated delivery writes a ``deliveries`` row when it starts and
updates it when it finishes. A delivery that the platform terminates keeps
``finished_at`` NULL: that row, not the HTTP response, is the evidence.
"""
import asyncio
import contextvars
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
import os
import re
import ssl
import time
import uuid

from fastapi import FastAPI, Request
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.responses import JSONResponse

from api import trigger_auth
from api.jobs import tick
from api.services import sync_all as service

try:  # Bundle layout: the fixture client sits next to main.py.
    from m5_cron_fixture import FixtureClient, Plan
except ImportError:  # Repository layout (tests).
    from experiments.m5_cloud.cron_fixture_client import FixtureClient, Plan

SCHEMA = "pft_m5_cron"
USER_ID = "synthetic-cron"
PROJECT_REF = "acyghoemtdrilsdszolq"
EXPECTED_PATH = "/trigger"
APPLICATION_DEADLINE = 210
DATABASE_SIZE_LIMIT = 200_000_000
INSTANCE_ID = uuid.uuid4().hex
INSTANCE = {"requests": 0, "inflight": 0, "inflight_peak": 0}
HANG = contextvars.ContextVar("m5_hang_publication_s", default=0)

service.MAX_RUN_SECONDS = APPLICATION_DEADLINE
_original_classify = service.classify_active_transactions


async def _classify(db, user_id):
    seconds = HANG.get()
    if seconds:
        # Deliberately blocks the event loop: no cancellation, timeout or finally
        # can run, so only the platform can end this delivery.
        time.sleep(seconds)
    return await _original_classify(db, user_id)


service.classify_active_transactions = _classify
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@dataclass(frozen=True)
class Settings:
    url: str
    keys: dict = field(repr=False)
    audience: str
    dataset_id: str
    database_role: str = "pft_m5_jobs"
    ca_pem: str | None = field(default=None, repr=False)
    require_backend_ssl: bool = True


def settings(environ=None):
    env = os.environ if environ is None else environ
    if env.get("M5_CRON_ENABLED") != "synthetic-20261002":
        raise RuntimeError("Synthetic cron acceptance not enabled")
    if env.get("PLAID_ENV", "").lower() == "production" or any(
            env.get(name) for name in ("PLAID_SECRET", "PLAID_CLIENT_ID", "PLAID_TOKEN_ENCRYPTION_KEY")):
        raise RuntimeError("Plaid configuration forbidden")
    url = env.get("M5_CRON_DATABASE_URL", "")
    parsed = make_url(url)
    if (parsed.drivername != "postgresql+asyncpg" or parsed.database != "postgres" or parsed.query
            or parsed.port != 5432 or not parsed.password or parsed.username != f"pft_m5_jobs.{PROJECT_REF}"
            or not re.fullmatch(r"aws-\d+-us-east-1\.pooler\.supabase\.com", parsed.host or "")):
        raise RuntimeError("Pinned synthetic session-pooler URL required")
    keys = {}
    for entry in env.get("M5_TRIGGER_KEYS", "").split(","):
        kid, _, secret = entry.partition("=")
        if re.fullmatch(r"[a-z0-9_-]{1,32}", kid) and secret:
            keys[kid] = secret.encode()
    dataset_id = env.get("M5_CRON_DATASET_ID", "")
    if not re.fullmatch(r"m5-[0-9a-f]{32}", dataset_id):
        raise RuntimeError("Synthetic dataset pin required")
    return Settings(url=url, keys=keys, audience=env.get("M5_TRIGGER_AUDIENCE", ""), dataset_id=dataset_id,
                    ca_pem=env.get("M5_SUPABASE_CA_PEM"))


def tls_context(config):
    context = ssl.create_default_context()
    if config.ca_pem:
        context.load_verify_locations(cadata=config.ca_pem)
    return context


def engine_for(config):
    # NullPool: a frozen or recycled instance keeps no idle sockets between deliveries.
    return create_async_engine(config.url, poolclass=NullPool, connect_args={
        "ssl": tls_context(config), "timeout": 10, "command_timeout": 60,
        "server_settings": {"search_path": SCHEMA}})


class _RawHeaders:
    """Keeps duplicate header lines so verify() can reject them."""

    def __init__(self, raw):
        self._pairs = [(name.decode("latin-1"), value.decode("latin-1")) for name, value in raw]

    def items(self):
        return self._pairs


async def _gate(connection, config):
    row = (await connection.execute(text(
        "SELECT current_user, (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), current_schema(), "
        "(SELECT project_ref FROM pft_m5_probe.identity WHERE singleton), "
        "(SELECT dataset_id FROM fixture_manifest WHERE singleton), "
        "(SELECT project_ref FROM fixture_manifest WHERE singleton), "
        "pg_database_size(current_database()), current_setting('idle_session_timeout')"))).one()
    if (row[0] != config.database_role or (config.require_backend_ssl and row[1] is not True)
            or row[2] != SCHEMA or row[3] != PROJECT_REF or row[4] != config.dataset_id or row[5] != PROJECT_REF):
        raise RuntimeError("Synthetic identity gate rejected")
    if row[6] > DATABASE_SIZE_LIMIT:
        raise RuntimeError("Synthetic database size budget reached")
    return row[7]


async def _plans(connection):
    rows = (await connection.execute(text(
        "SELECT i.access_token, p.item_id, p.mode, p.account_id, p.pages, p.rows_per_page, p.generation, "
        "p.failures, p.delay_s FROM fixture_plan p JOIN items i USING (item_id) ORDER BY p.item_id"))).all()
    return {row[0]: Plan(item_id=row[1], mode=row[2], account_id=row[3], pages=row[4], rows_per_page=row[5],
                         generation=row[6], failures=row[7], delay_s=float(row[8])) for row in rows}


async def run_delivery(engine, config, *, received_at, source):
    INSTANCE["requests"] += 1
    ordinal = INSTANCE["requests"]
    INSTANCE["inflight"] += 1
    INSTANCE["inflight_peak"] = max(INSTANCE["inflight_peak"], INSTANCE["inflight"])
    inflight = INSTANCE["inflight"]
    checkouts = {"open": 0, "peak": 0}

    def checkout(*_):
        checkouts["open"] += 1
        checkouts["peak"] = max(checkouts["peak"], checkouts["open"])

    def checkin(*_):
        checkouts["open"] -= 1

    event.listen(engine.sync_engine, "checkout", checkout)
    event.listen(engine.sync_engine, "checkin", checkin)
    started = time.perf_counter()
    delivery_id = uuid.uuid4()
    try:
        async with engine.begin() as connection:
            idle_timeout = await _gate(connection, config)
            plans = await _plans(connection)
            # One-shot: a hang request is consumed by the delivery that will hang.
            hang = await connection.scalar(text(
                "UPDATE fixture_manifest m SET hang_publication_s = 0 FROM (SELECT hang_publication_s AS old "
                "FROM fixture_manifest WHERE singleton FOR UPDATE) o WHERE m.singleton RETURNING o.old"))
            await connection.execute(text(
                "INSERT INTO deliveries (delivery_id, source, received_at, instance_id, instance_ordinal, "
                "inflight_at_start, hang_publication_s, idle_session_timeout) VALUES (:id, :source, :received, "
                ":instance, :ordinal, :inflight, :hang, :idle)"),
                {"id": delivery_id, "source": source, "received": received_at, "instance": INSTANCE_ID,
                 "ordinal": ordinal, "inflight": inflight, "hang": hang, "idle": idle_timeout})
        client = FixtureClient(plans)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        HANG.set(hang)
        outcome, run_id, error = None, None, None
        try:
            result = await tick(USER_ID, engine=engine, session_factory=sessions,
                                sync=partial(service.sync_all, client=client), backup_fn=None)
            outcome, run_id = result.get("status"), result.get("run_id")
            return {"status": outcome, "run_id": run_id, "delivery_id": str(delivery_id),
                    "instance_id": INSTANCE_ID, "instance_ordinal": ordinal, "inflight_at_start": inflight,
                    "synthetic_sdk_calls": client.calls, "synthetic_added_rows": client.added_rows,
                    "idle_session_timeout": idle_timeout}
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(
                    "UPDATE deliveries SET finished_at = clock_timestamp(), outcome = :outcome, run_id = :run, "
                    "error_type = :error, handler_ms = :ms, engine_checkout_peak = :peak "
                    "WHERE delivery_id = :id"),
                    {"outcome": outcome, "run": run_id, "error": error, "id": delivery_id,
                     "ms": round((time.perf_counter() - started) * 1000), "peak": checkouts["peak"]})
    finally:
        INSTANCE["inflight"] -= 1


@app.post(EXPECTED_PATH)
async def trigger(request: Request):
    received_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > trigger_auth.MAX_BODY):
        return JSONResponse({"error": "body too large"}, 413)
    body = await request.body()
    try:
        config = settings()
    except Exception:
        return JSONResponse({"error": "configuration rejected"}, 503)
    engine = engine_for(config)
    details = {}

    async def run_once():
        # The source header is an unauthenticated label used only to group evidence.
        source = (request.headers.get("x-pft-delivery-source") or "unknown")[:32]
        details.update(await run_delivery(engine, config, received_at=received_at, source=source))
        return details

    try:
        status, payload = await trigger_auth.handle_trigger(
            method=request.method, path=request.url.path, headers=_RawHeaders(request.headers.raw), body=body,
            keys=config.keys, audience=config.audience, expected_path=EXPECTED_PATH,
            nonce_store=trigger_auth.SqlNonceStore(engine, f"{SCHEMA}.trigger_nonces"), run_once=run_once)
    finally:
        await engine.dispose()
    if status == 200:
        payload.update(details)
    payload["handler_s"] = round(time.perf_counter() - started, 3)
    return JSONResponse(payload, status, headers={"Cache-Control": "private, no-store"})
