"""Explicit schema migration, never called by normal service startup."""
import asyncio

from api.db import engine, init_db, verify_database_name
from api.routes.plaid import validate_runtime_configuration


async def main():
    validate_runtime_configuration()
    await verify_database_name()
    try:
        await init_db()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
