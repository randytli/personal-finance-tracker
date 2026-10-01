"""Undeployed M5 one-shot lifecycle draft; Windows jobs remains unchanged.

The eventual HTTP adapter must implement real capability and immutable identity
checks. Injected callbacks here are a design seam, not authentication evidence.
Each call owns its engine; never pass the global API engine via engine_factory.
Backup remains an injected experiment, not an approved remote backup adapter.
"""
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.jobs import tick


async def run_scheduler_once(user_id, *, verify_capability, engine_factory,
                             verify_identity, sync, backup_fn, now=None):
    await verify_capability()
    engine = engine_factory()
    try:
        await verify_identity(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        return await tick(user_id, now=now, engine=engine, session_factory=sessions,
                          sync=sync, backup_fn=backup_fn)
    finally:
        await engine.dispose()
