"""One retained synthetic-schema run with injected per-query latency.

This measures sensitivity, not actual Vercel/Supabase network performance.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import time
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSessionTransaction, async_sessionmaker, create_async_engine

from scripts.pft_m5_benchmark import URL, USER


async def run(schema, delay):
    if os.environ.get("PLAID_ENV", "").lower() == "production" or not re.fullmatch(r"m5_[a-f0-9]{32}", schema):
        raise RuntimeError("Requires retained local synthetic schema and non-Production environment")
    os.environ["DATABASE_URL"], os.environ["PLAID_ENV"] = URL, "sandbox"
    from api.services.sync_all import sync_all
    from tests.test_sync_all import Client, page
    engine = create_async_engine(URL, pool_size=4, max_overflow=0, connect_args={
        "server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queries, exits = 0, []
    original_exit = AsyncSessionTransaction.__aexit__
    async def timed_exit(self, *args):
        start = time.perf_counter()
        try:
            return await original_exit(self, *args)
        finally:
            exits.append(time.perf_counter()-start)
    try:
        start = time.perf_counter()
        async with engine.connect() as connection:
            assert await connection.scalar(text("select current_database()")) == "pft_m5_synthetic"
            assert await connection.scalar(text("select current_schema()")) == schema
        identity_s = time.perf_counter()-start
        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def before(*_):
            nonlocal queries
            queries += 1
            time.sleep(delay / 1000)
        client = Client({f"token-{i}": [page(f"latency-{i}")] for i in range(5)})
        start = time.perf_counter()
        with patch.object(AsyncSessionTransaction, "__aexit__", timed_exit):
            result = await sync_all(USER, engine=engine, session_factory=sessions, client=client)
        wall = time.perf_counter()-start
        assert result["status"] == "success"
        assert engine.pool.checkedout() == 0
        return {"kind": "injected_query_latency_not_cloud", "delay_ms_per_query": delay,
                "wall_s": wall, "queries": queries, "identity_connection_s": identity_s,
                "transaction_exit_samples_s": exits, "transaction_exit_total_s": sum(exits),
                "status": result["status"], "checked_out_after": 0}
    finally:
        start = time.perf_counter()
        await engine.dispose()
        print("engine_dispose_s", time.perf_counter()-start)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--delay-ms", type=float, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.delay_ms <= 5:
        parser.error("Local probe delay must be between 0 and 5 ms")
    args.output.write_text(json.dumps(asyncio.run(run(args.schema, args.delay_ms)), indent=2) + "\n")
