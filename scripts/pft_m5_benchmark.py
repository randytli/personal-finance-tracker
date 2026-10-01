"""Local-only M5 measurements of the real sync service; never loads env files.

Run with .venv/bin/python -m scripts.pft_m5_benchmark --output PATH.
Requires a separately created empty pft_m5_synthetic DB on loopback:55439.
All SDK responses are synthetic. A unique schema is removed in finally.
"""
import argparse
import asyncio
from collections import defaultdict
from contextlib import ExitStack
import json
import os
from pathlib import Path
import resource
import statistics
import time
import uuid
from unittest.mock import patch

from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

URL = "postgresql+asyncpg://pft_m5@127.0.0.1:55439/pft_m5_synthetic"
USER = "synthetic-user"


async def run(samples):
    if os.environ.get("PLAID_ENV", "").lower() == "production":
        raise RuntimeError("Refusing Production environment")
    # Overwrite any inherited DB endpoint before importing the test fixtures/routes.
    os.environ["DATABASE_URL"] = URL
    os.environ["PLAID_ENV"] = "sandbox"
    from api.models import Account, Base, Item, RawTransaction, SyncRun, Transaction
    from api.services import sync_all as service
    from api.jobs import tick
    from tests.test_sync_all import Client, page, plaid_error, tx
    from urllib3.exceptions import ReadTimeoutError

    schema = "m5_" + uuid.uuid4().hex
    admin = create_async_engine(URL)
    engine = create_async_engine(URL, pool_size=4, max_overflow=0, connect_args={
        "server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    measurements = []
    stats = defaultdict(float)
    checked_out = 0
    serial = 0

    @event.listens_for(engine.sync_engine, "checkout")
    def checkout(*_):
        nonlocal checked_out
        checked_out += 1
        stats["connection_peak"] = max(stats["connection_peak"], checked_out)

    @event.listens_for(engine.sync_engine, "checkin")
    def checkin(*_):
        nonlocal checked_out
        checked_out -= 1

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(connection, *_):
        connection.info["m5_query_start"] = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(connection, *_):
        stats["sql_s"] += time.perf_counter() - connection.info["m5_query_start"]
        stats["sql_queries"] += 1

    def timed(name, original):
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                stats[name + "_s"] += time.perf_counter() - start
        return wrapper

    class DelayedClient(Client):
        def __init__(self, pages, delay=0):
            super().__init__(pages)
            self.delay = delay
            self.bytes = 0

        def transactions_sync(self, *args, **kwargs):
            time.sleep(self.delay)
            value = super().transactions_sync(*args, **kwargs)
            self.bytes += len(json.dumps(value.to_dict(), default=str).encode())
            return value

    def response(rows=0, pages=1, delay=0, failure=False, retry=False):
        nonlocal serial
        serial += 1
        values = {}
        for i in range(5):
            transactions = [tx(f"m5-{serial}-{i}-{j}", f"account-{i}-0", 10 + j % 20)
                            for j in range(rows)]
            chunk = max(1, (rows + pages - 1) // pages)
            values[f"token-{i}"] = [page(f"c-{serial}-{i}-{p}",
                added=transactions[p*chunk:(p+1)*chunk], more=p < pages-1) for p in range(pages)]
        if failure:
            values["token-4"] = [plaid_error("ITEM_LOGIN_REQUIRED")]
        if retry:
            values["token-0"].insert(0, ReadTimeoutError(None, "/synthetic", "synthetic"))
            values["token-1"].insert(1, plaid_error("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"))
            # Mutation discards the prefix; replay the entire original page sequence.
            values["token-1"] = values["token-1"][:2] + values["token-1"][:1] + values["token-1"][2:]
        return DelayedClient(values, delay)

    async def measure(name, client, *, scheduler=False, cancel=False, expected="success", **kwargs):
        stats.clear()
        initial_connections = checked_out
        start, cpu = time.perf_counter(), time.process_time()
        result = None
        with ExitStack() as stack:
            for fn in ("_fetch_item", "_publish_item", "classify_active_transactions",
                       "_assert_lock_owner", "acquire_session_lock", "_finalize_failure"):
                stack.enter_context(patch.object(service, fn, timed(fn, getattr(service, fn))))
            async def sync(*args, **options):
                return await service.sync_all(*args, client=client, **options)
            coroutine = (tick(USER, engine=engine, session_factory=sessions, sync=sync)
                         if scheduler else sync(USER, engine=engine, session_factory=sessions, **kwargs))
            if cancel:
                task = asyncio.create_task(coroutine)
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    result = {"status": "cancelled"}
            else:
                result = await coroutine
        elapsed = time.perf_counter() - start
        assert result["status"] == expected, (name, result)
        assert checked_out == initial_connections, (name, "connection leaked", checked_out)
        measurements.append(dict(scenario=name, wall_s=elapsed, cpu_s=time.process_time()-cpu,
            rss_high_water_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            response_bytes=client.bytes, sdk_calls=len(client.sync_requests),
            status=result["status"], **stats))
        return result

    try:
        async with admin.begin() as connection:
            assert await connection.scalar(text("select current_database()")) == "pft_m5_synthetic"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions.begin() as db:
            for i in range(5):
                db.add(Item(item_id=f"item-{i}", user_id=USER, institution_id=f"ins-{i}",
                    institution_name="Synthetic", status="active", access_token=f"token-{i}",
                    transactions_cursor="start"))
                await db.flush()
                for j in range(3 if i < 3 else 2):
                    db.add(Account(account_id=f"account-{i}-{j}", item_id=f"item-{i}",
                        name="Synthetic", type="credit" if j == 0 else "depository",
                        consumer_transactions_enabled=not (i < 4 and j == 1)))
        await measure("seed_2610", response(522, 3))
        for _ in range(samples):
            await measure("normal", response(1))
            await measure("noop_fetch", response())
            await measure("idle_tick", response(), scheduler=True, expected="idle")
        await measure("multi_page", response(300, 3))
        await measure("delayed", response(1, delay=0.2))
        await measure("partial_failure", response(1, failure=True), expected="partial")
        await measure("retry_mutation", response(40, 2, retry=True))
        async with engine.connect() as owner:
            await owner.scalar(text("select pg_advisory_lock(hashtextextended(:key, 0))"),
                               {"key": "pft-sync:" + USER})
            await owner.commit()
            await measure("contention", response(), expected="busy")
            await owner.scalar(text("select pg_advisory_unlock(hashtextextended(:key, 0))"),
                               {"key": "pft-sync:" + USER})
            await owner.commit()
        await measure("contention_retry", response())
        async with sessions() as db:
            before_count = await db.scalar(select(func.count()).select_from(RawTransaction))
            before_cursors = list((await db.execute(select(Item.transactions_cursor).order_by(Item.item_id))).scalars())
        await measure("interrupted_fetch", response(1, delay=0.3), cancel=True, expected="cancelled")
        # to_thread cancellation cannot kill the SDK thread. Wait for its known local delay.
        await asyncio.sleep(0.4)
        async with sessions() as db:
            assert before_count == await db.scalar(select(func.count()).select_from(RawTransaction))
            assert before_cursors == list((await db.execute(select(Item.transactions_cursor).order_by(Item.item_id))).scalars())
        await measure("interrupted_idle_reconcile", response(), scheduler=True, expected="idle")
        async with sessions() as db:
            assert not await db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.status == "running"))
        async with sessions.begin() as db:
            await db.execute(update(Item).values(last_sync_success_at=None, next_sync_retry_at=None))
        await measure("catch_up_5000", response(1000, 5), scheduler=True)
        await measure("growth_26100", response(5220, 11))
        for _ in range(samples):
            await measure("grown_normal", response(1))
            await measure("grown_noop", response())
        async with sessions() as db:
            size = await db.scalar(text("select sum(pg_total_relation_size(quote_ident(schemaname)||'.'||quote_ident(tablename))) from pg_tables where schemaname=:schema"), {"schema": schema})
            counts = {"raw": await db.scalar(select(func.count()).select_from(RawTransaction)),
                      "normalized": await db.scalar(select(func.count()).select_from(Transaction))}
        groups = {}
        for name in sorted({m["scenario"] for m in measurements}):
            values = sorted(m["wall_s"] for m in measurements if m["scenario"] == name)
            groups[name] = {"n": len(values), "min_s": min(values), "median_s": statistics.median(values),
                            "p95_nearest_rank_s": values[max(0, __import__('math').ceil(.95*len(values))-1)],
                            "max_s": max(values)}
        return {"kind": "local_synthetic_not_serverless", "samples": measurements,
                "summary": groups, "retained_counts": counts, "relations_bytes": int(size),
                "schema_for_backup": schema if os.environ.get("PFT_M5_KEEP_SCHEMA") == "1" else None,
                "notes": "Stages overlap; SQL sums exclude failed queries/commit. RSS is process high-water, not per-invocation. No real SDK network, TLS, cloud, cold-start or bank latency."}
    finally:
        await engine.dispose()
        if os.environ.get("PFT_M5_KEEP_SCHEMA") != "1":
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("At least two samples required")
    result = asyncio.run(run(args.samples))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"summary": result["summary"], "retained_counts": result["retained_counts"],
                      "relations_bytes": result["relations_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
