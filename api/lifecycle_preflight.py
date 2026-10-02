"""Read-only Production gate for the institution lifecycle migration.

Run before `python -m api.migrate_once`. It always applies the Production rule
(every Item must be active until the migration is applied), prints status
counts only, and exits 2 when the migration must not run.
"""
import asyncio
import json
import sys

from sqlalchemy import text

from api.db import engine, verify_database_name
from api.migrations import institution_lifecycle_preflight, lifecycle_preflight_errors


async def main():
    await verify_database_name()
    try:
        async with engine.connect() as connection:
            async with connection.begin() as transaction:
                await connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                report = await institution_lifecycle_preflight(connection)
                await transaction.rollback()
    finally:
        await engine.dispose()
    errors = lifecycle_preflight_errors(report, production=True)
    print(json.dumps({**report, "errors": errors, "migration_may_run": not errors}, indent=2, sort_keys=True))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
