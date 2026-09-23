"""Single-owner jobs loop for daily backups and active-Item synchronization."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from api.models import Item
from api.services.sync_state import acquire_session_lock, acknowledge_request, due_items, locked_state

logger = logging.getLogger(__name__)
SYNC_INTERVAL = timedelta(hours=24)
POLL_SECONDS = 60


def utcnow():
    return datetime.now(timezone.utc)


async def _assert_owner(connection, backend_pid):
    try:
        current_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
    except Exception as exc:
        await connection.invalidate()
        raise RuntimeError("Jobs lock connection was lost") from exc
    if current_pid != backend_pid:
        await connection.invalidate()
        raise RuntimeError("Jobs lock connection was lost")


async def _state(db, user_id):
    return await locked_state(db, user_id)


async def request_sync(user_id, item_ids=None, *, session_factory=None):
    """Coalesce clicks before a run; a click during a run queues one more pass."""
    if session_factory is None:
        from api.db import SessionLocal
        session_factory = SessionLocal
    if item_ids is not None:
        if not item_ids or len(item_ids) != len(set(item_ids)):
            raise ValueError("Select distinct active Items")
    async with session_factory.begin() as db:
        if item_ids is not None:
            found = set((await db.execute(select(Item.item_id).where(
                Item.user_id == user_id, Item.status == "active",
                Item.item_id.in_(item_ids)))).scalars())
            if found != set(item_ids):
                raise ValueError("Selected Item is not active")
        state = await _state(db, user_id)
        pending = state.requested_sequence > max(state.handled_sequence, state.running_sequence or 0)
        if not pending:
            state.requested_sequence += 1
            state.requested_item_ids = sorted(item_ids) if item_ids is not None else None
        elif state.requested_item_ids is not None:
            state.requested_item_ids = (sorted(set(state.requested_item_ids) | set(item_ids))
                                        if item_ids is not None else None)
        return {"requested_sequence": state.requested_sequence, "queued": True}


async def tick(user_id, *, now=None, engine=None, session_factory=None, sync=None,
               backup_fn=None):
    """One clock-controlled poll. The advisory lock covers the entire jobs tick."""
    if engine is None or session_factory is None:
        from api.db import engine as default_engine, SessionLocal
        engine = engine or default_engine
        session_factory = session_factory or SessionLocal
    if sync is None:
        from api.services.sync_all import sync_all
        sync = sync_all
    now = now or utcnow()
    async with engine.connect() as owner:
        key = "pft-jobs:" + user_id
        acquired, backend_pid = await acquire_session_lock(owner, key)
        if not acquired:
            return {"status": "busy"}
        try:
            async with session_factory.begin() as db:
                state = await _state(db, user_id)
                state.jobs_heartbeat_at = now
                backup_due = state.last_backup_at is None or state.last_backup_at <= now - SYNC_INTERVAL
                if state.running_sequence is not None and state.running_sequence > state.handled_sequence:
                    sequence = state.running_sequence
                    requested_ids = state.running_item_ids
                elif state.requested_sequence > state.handled_sequence:
                    sequence = state.requested_sequence
                    requested_ids = state.requested_item_ids
                    state.running_sequence = sequence
                    state.running_item_ids = requested_ids
                    state.requested_item_ids = None
                else:
                    sequence = None
                    requested_ids = None
                eligible = select(Item.item_id).where(
                    Item.user_id == user_id, Item.status == "active", Item.sync_paused.is_(False))
                if sequence is not None:
                    if requested_ids is not None:
                        eligible = eligible.where(Item.item_id.in_(requested_ids))
                else:
                    eligible = eligible.where(due_items(now))
                item_ids = list((await db.execute(eligible.order_by(Item.item_id))).scalars())

            # Backup errors must not prevent a due sync. Backup state advances only on success.
            if backup_due and backup_fn is not None:
                try:
                    await asyncio.to_thread(backup_fn, "daily")
                except Exception as exc:
                    logger.error("Daily backup failed: %s", type(exc).__name__)
                else:
                    await _assert_owner(owner, backend_pid)
                    async with session_factory.begin() as db:
                        (await _state(db, user_id)).last_backup_at = now

            async def check_owner():
                await _assert_owner(owner, backend_pid)

            await check_owner()
            # Even idle ticks must reconcile interrupted runs under the sync lock.
            result = await sync(user_id, trigger_source="manual" if sequence is not None else "jobs",
                                item_ids=item_ids, engine=engine, session_factory=session_factory,
                                request_sequence=sequence, scheduled_at=now if sequence is None else None,
                                check_owner=check_owner)
            if result["status"] == "busy" and sequence is not None:
                await check_owner()
                async with session_factory.begin() as db:
                    state = await _state(db, user_id)
                    if state.running_sequence == sequence:
                        # No sync run started. Put the claim back with any later
                        # clicks so contention cannot turn them into extra runs.
                        scope = state.running_item_ids
                        if state.requested_sequence > sequence:
                            scope = (sorted(set(scope) | set(state.requested_item_ids))
                                     if scope is not None and state.requested_item_ids is not None else None)
                        state.requested_item_ids = scope
                        state.running_sequence = None
                        state.running_item_ids = None
            if result["status"] != "busy" and sequence is not None:
                await _assert_owner(owner, backend_pid)
                async with session_factory.begin() as db:
                    await acknowledge_request(db, user_id, sequence)
            return result
        finally:
            try:
                if await owner.scalar(text("SELECT pg_backend_pid()")) == backend_pid:
                    await owner.scalar(text(
                        "SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
                    await owner.commit()
                else:
                    await owner.invalidate()
            except asyncio.CancelledError:
                await owner.invalidate()
                raise
            except Exception:
                await owner.invalidate()


async def run_forever():
    from api.backup import backup, connection
    from api.db import engine, verify_database_name, verify_runtime_schema
    from api.routes.plaid import _user_id, validate_runtime_configuration

    validate_runtime_configuration()
    connection()
    await verify_database_name()
    await verify_runtime_schema()
    try:
        while True:
            try:
                await tick(_user_id(), backup_fn=backup)
            except Exception as exc:
                logger.error("Jobs tick failed: %s", type(exc).__name__)
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_forever())
