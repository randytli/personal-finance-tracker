import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.models import Base
from api.migrations import migrate_multi_institution

DATABASE_URL = os.environ["DATABASE_URL"]   # postgresql+asyncpg://supabase:...

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await migrate_multi_institution(connection)


async def verify_database_name():
    """Fail before schema initialization if Production points at the wrong DB."""
    if os.environ.get("PLAID_ENV", "").lower() != "production":
        return

    expected = os.environ["EXPECTED_DATABASE_NAME"]
    async with engine.connect() as connection:
        actual = await connection.scalar(text("select current_database()"))
    if actual != expected:
        raise RuntimeError(
            "Production database safety check failed: connected database does not "
            "match EXPECTED_DATABASE_NAME"
        )
