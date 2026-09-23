import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.models import Base
from api.migrations import (migrate_multi_institution, migrate_manual_categories,
                            migrate_consumer_scope, migrate_statement_imports,
                            migrate_transaction_labels, migrate_benefit_categories,
                            migrate_sync_runs)

DATABASE_URL = os.environ["DATABASE_URL"]   # postgresql+asyncpg://supabase:...

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await migrate_multi_institution(connection)
        await migrate_manual_categories(connection)
        await migrate_consumer_scope(connection)
        await migrate_statement_imports(connection)
        await migrate_transaction_labels(connection)
        await migrate_benefit_categories(connection)
        await migrate_sync_runs(connection)


async def verify_database_name():
    """Fail before startup/migration when a configured database identity differs."""
    expected = os.environ.get("EXPECTED_DATABASE_NAME")
    if not expected and os.environ.get("PLAID_ENV", "").lower() != "production":
        return
    if not expected:
        raise RuntimeError("EXPECTED_DATABASE_NAME is required in Production")
    async with engine.connect() as connection:
        actual = await connection.scalar(text("select current_database()"))
    if actual != expected:
        raise RuntimeError(
            "Database safety check failed: connected database does not "
            "match EXPECTED_DATABASE_NAME"
        )


async def verify_runtime_schema():
    """Runtime startup is read only; migrations require an explicit command."""
    missing = []
    async with engine.connect() as connection:
        # Resolve each relation through the same search_path the ORM uses. A
        # similarly named table in another schema must not satisfy this check.
        for table in Base.metadata.sorted_tables:
            columns = set((await connection.execute(text(
                "SELECT attname FROM pg_catalog.pg_attribute "
                "WHERE attrelid=to_regclass(:name) AND attnum>0 AND NOT attisdropped"
            ), {"name": table.name})).scalars())
            missing.extend(f"{table.name}.{column.name}" for column in table.columns
                           if column.name not in columns)
    if missing:
        raise RuntimeError("Runtime schema is incomplete; run explicit migration: " + ", ".join(missing))
