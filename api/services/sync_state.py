"""Shared persisted scheduling state; callers own the transaction."""

from datetime import timedelta

from sqlalchemy import and_, or_, text
from sqlalchemy.dialects.postgresql import insert

from api.models import Item, SyncRuntimeState


async def acquire_session_lock(connection, key):
    try:
        acquired = await connection.scalar(text(
            "SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
        backend_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
        await connection.commit()
        return acquired, backend_pid
    except BaseException:
        # Cancellation can happen after PostgreSQL took the session lock but
        # before acquisition was acknowledged. Never return that socket to the pool.
        await connection.invalidate()
        raise


def due_items(now):
    # A retry deadline replaces the daily deadline, including after a recent success.
    return or_(
        Item.next_sync_retry_at <= now,
        and_(Item.next_sync_retry_at.is_(None),
             or_(Item.last_sync_success_at.is_(None),
                 Item.last_sync_success_at <= now - timedelta(hours=24))),
    )


async def locked_state(db, user_id):
    # A row lock cannot serialize creation of a row that does not yet exist.
    await db.execute(insert(SyncRuntimeState).values(user_id=user_id)
                     .on_conflict_do_nothing(index_elements=[SyncRuntimeState.user_id]))
    return await db.get(SyncRuntimeState, user_id, with_for_update=True,
                        populate_existing=True)


async def acknowledge_request(db, user_id, sequence):
    if sequence is None:
        return
    state = await locked_state(db, user_id)
    if state.running_sequence == sequence:
        state.handled_sequence = max(state.handled_sequence, sequence)
        state.running_sequence = None
        state.running_item_ids = None
