"""Shared persisted scheduling state; callers own the transaction."""

from datetime import timedelta

from sqlalchemy import and_, or_, text
from sqlalchemy.dialects.postgresql import insert

from api.models import Item, SyncRuntimeState


_HELD_BY_THIS_BACKEND = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted "
    "AND pid = pg_backend_pid() AND objsubid = 1 "
    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
    "AND classid::bigint = ((hashtextextended(:key, 0) >> 32) & 4294967295) "
    "AND objid::bigint = (hashtextextended(:key, 0) & 4294967295))")


async def acquire_session_lock(connection, key):
    try:
        # A pooler can hand a dead client's backend to the next client. Re-entering
        # a lock that survived would succeed and leave a count behind after unlock.
        if await connection.scalar(_HELD_BY_THIS_BACKEND, {"key": key}):
            raise RuntimeError("Session lock already held by this backend")
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
