"""Explicit one-shot sync entry point. Scheduling and status HTTP belong to later milestones."""

import argparse
import asyncio
import json

from sqlalchemy import text


async def run_once(allow_production=False):
    from api.db import engine, verify_database_name
    from api.routes.plaid import _user_id, is_production, validate_runtime_configuration
    from api.services.sync_all import sync_all

    validate_runtime_configuration()
    if is_production() and not allow_production:
        raise RuntimeError("Production one-shot sync requires explicit --allow-production")
    await verify_database_name()
    async with engine.connect() as connection:
        tables = await connection.execute(text(
            "SELECT to_regclass('sync_runs'), to_regclass('sync_item_runs'), "
            "to_regclass('sync_runtime_state')"))
        if any(value is None for value in tables.one()):
            raise RuntimeError("M2 schema is missing; run the migration explicitly")
    return await sync_all(_user_id())


def main():
    parser = argparse.ArgumentParser(description="Run one active-Item sync")
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_once(allow_production=args.allow_production))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
