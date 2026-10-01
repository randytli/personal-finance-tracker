"""Small connection measurements only; no financial table reads or sync calls."""
import asyncio
import time

from fastapi import Depends, HTTPException


def register(app, capability, identity, new_engine):
    @app.get("/probe/pool")
    async def pool_probe(pool: str = "null", reads: int = 5, concurrency: int = 1,
                         config=Depends(capability)):
        if pool not in {"null", "small"} or not 1 <= reads <= 20 or not 1 <= concurrency <= 4:
            raise HTTPException(422, "Probe bounds rejected")
        engine = new_engine(config, pool)
        semaphore = asyncio.Semaphore(concurrency)
        timings = []
        peak = active = 0
        async def read(index):
            nonlocal peak, active
            async with semaphore:
                start = time.perf_counter()
                active += 1
                peak = max(peak, active)
                try:
                    async with engine.connect() as connection:
                        pid = await identity(connection, config)
                    timings.append({"index": index, "connection_identity_s": time.perf_counter()-start,
                                    "backend_pid": pid})
                finally:
                    active -= 1
        start = time.perf_counter()
        try:
            # TaskGroup cancels and joins every sibling before disposing the engine.
            async with asyncio.timeout(55), asyncio.TaskGroup() as tasks:
                for index in range(reads):
                    tasks.create_task(read(index))
            return {"kind": "small_pool_probe", "pool": pool, "concurrency": concurrency,
                    "request_tasks_peak": peak, "wall_s": time.perf_counter()-start,
                    "samples": sorted(timings, key=lambda sample: sample["index"])}
        finally:
            await engine.dispose()
