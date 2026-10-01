"""Local import/package and pool comparison. No real credentials or cloud calls."""
import argparse
import asyncio
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from scripts.pft_m5_benchmark import URL


async def pool_probe(null_pool):
    engine = create_async_engine(URL, **({"poolclass": NullPool} if null_pool else
                                        {"pool_size": 4, "max_overflow": 0}))
    values = []
    try:
        for _ in range(20):
            start = time.perf_counter()
            async with engine.connect() as connection:
                assert await connection.scalar(text("select current_database()")) == "pft_m5_synthetic"
                await connection.scalar(text("select pg_backend_pid()"))
            values.append(time.perf_counter() - start)
        async def read():
            async with engine.connect() as connection:
                return await connection.scalar(text("select current_database()"))
        assert await asyncio.gather(*(read() for _ in range(4))) == ["pft_m5_synthetic"] * 4
        return {"samples_s": values, "max_s": max(values), "mean_s": sum(values)/len(values),
                "four_concurrent_reads": "PASS"}
    finally:
        await engine.dispose()


def run():
    if os.environ.get("PLAID_ENV", "").lower() == "production":
        raise RuntimeError("Refusing Production environment")
    roots = ["fastapi", "uvicorn", "SQLAlchemy", "asyncpg", "plaid-python", "cryptography"]
    # Measurement tooling only: use pip's installed parser without adding a runtime dependency.
    from pip._vendor.packaging.requirements import Requirement
    queue, dependencies = list(roots), {}
    while queue:
        name = queue.pop()
        distribution = metadata.distribution(name)
        normalized = distribution.metadata["Name"].lower().replace("_", "-")
        if normalized in dependencies:
            continue
        paths = {distribution.locate_file(f) for f in distribution.files or []}
        dependencies[normalized] = {"version": distribution.version,
            "installed_file_bytes": sum(p.stat().st_size for p in paths if p.is_file())}
        for requirement in distribution.requires or []:
            parsed = Requirement(requirement)
            if parsed.marker is None or parsed.marker.evaluate({"extra": ""}):
                queue.append(parsed.name)
    imports = []
    for _ in range(5):
        env = {"PATH": "/usr/bin:/bin", "DATABASE_URL": URL, "PLAID_ENV": "sandbox"}
        code = "import time; t=time.perf_counter(); import api.main; print(time.perf_counter()-t)"
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                                text=True, check=True, timeout=30)
        imports.append(float(result.stdout))
    return {"kind": "local_not_vercel", "python": sys.version.split()[0],
            "dependencies": dependencies, "installed_closure_bytes": sum(
                d["installed_file_bytes"] for d in dependencies.values()),
            "fresh_process_import_s": imports, "pool4": asyncio.run(pool_probe(False)),
            "nullpool": asyncio.run(pool_probe(True)),
            "limitations": "Installed sizes are not a deploy artifact. Imports do not run lifespan. No TLS, remote latency, event-loop reuse, SDK transport or provider cold start."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(run(), indent=2) + "\n")
