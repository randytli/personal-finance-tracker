from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import os

from api.models import Base

DATABASE_URL = os.environ["DATABASE_URL"]   # postgresql+asyncpg://supabase:...

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
