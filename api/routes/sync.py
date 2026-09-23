"""Manual sync requests and read-only M5 runtime status."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from api.db import SessionLocal
from api.jobs import request_sync
from api.models import Item, SyncItemRun, SyncRun, SyncRuntimeState
from api.routes.plaid import _user_id

router = APIRouter(prefix="/sync")


def timestamp(value):
    return value.isoformat() if value is not None else None


async def status_for_user(user_id, *, session_factory=SessionLocal, now=None):
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        # All fields in one response describe the same committed database state.
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        state = await db.get(SyncRuntimeState, user_id)
        run = (await db.execute(select(SyncRun).where(SyncRun.user_id == user_id)
                                .order_by(SyncRun.started_at.desc(), SyncRun.run_id.desc())
                                .limit(1))).scalar_one_or_none()
        items = (await db.execute(select(Item).where(Item.user_id == user_id)
                                  .order_by(Item.institution_name, Item.item_id))).scalars().all()
        outcomes = (await db.execute(select(SyncItemRun, SyncRun.started_at)
            .join(SyncRun, SyncRun.run_id == SyncItemRun.run_id)
            .where(SyncRun.user_id == user_id)
            .distinct(SyncItemRun.item_id)
            .order_by(SyncItemRun.item_id, SyncRun.started_at.desc(), SyncRun.run_id.desc()))).all()
        latest = {outcome.item_id: (outcome, started) for outcome, started in outcomes}
        heartbeat = state.jobs_heartbeat_at if state else None
        # A jobs tick can spend five minutes in sync before its next heartbeat.
        heartbeat_fresh = bool(heartbeat and heartbeat >= now - timedelta(minutes=7))
        # Backups can outlast the heartbeat grace period. The tick holds this
        # session lock throughout backup/sync; inspecting it never acquires it.
        owner_alive = await db.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM pg_locks
              WHERE locktype='advisory' AND granted AND objsubid=1
                AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
                AND classid::bigint=((hashtextextended(:key, 0) >> 32) & 4294967295)
                AND objid::bigint=(hashtextextended(:key, 0) & 4294967295))
        """), {"key": "pft-jobs:" + user_id})
        return {
            "last_published_run_id": state.last_published_run_id if state else None,
            "published_at": timestamp(state.published_at) if state else None,
            "current_run": {
                "run_id": run.run_id, "status": run.status,
                "started_at": timestamp(run.started_at), "finished_at": timestamp(run.finished_at),
                "classification_status": run.classification_status,
                "error_category": run.error_category,
            } if run else None,
            "jobs": {"heartbeat_at": timestamp(heartbeat),
                     "status": "running" if heartbeat_fresh or owner_alive else "stopped"},
            "backup": {
                "last_success_at": timestamp(state.last_backup_at) if state else None,
                "last_attempt_at": timestamp(state.last_backup_attempt_at) if state else None,
                "error_category": state.last_backup_error if state else None,
                "status": ("failed" if state and state.last_backup_error else
                           "never" if not state or not state.last_backup_at else
                           "overdue" if state.last_backup_at < now - timedelta(hours=25) else "healthy"),
            },
            "institutions": [{
                "item_id": item.item_id, "institution_id": item.institution_id,
                "institution_name": item.institution_name, "status": item.status,
                "sync_paused": item.sync_paused,
                "last_attempt_at": timestamp(item.last_sync_attempt_at),
                "last_success_at": timestamp(item.last_sync_success_at),
                "last_change_at": timestamp(item.last_sync_change_at),
                "next_retry_at": timestamp(item.next_sync_retry_at),
                "metadata_warning": item.metadata_warning,
                "metadata_warning_at": timestamp(item.metadata_warning_at),
                "latest_outcome": ({
                    "run_id": latest[item.item_id][0].run_id,
                    "status": latest[item.item_id][0].status,
                    "phase": latest[item.item_id][0].phase,
                    "started_at": timestamp(latest[item.item_id][1]),
                    "finished_at": timestamp(latest[item.item_id][0].finished_at),
                    "error_category": latest[item.item_id][0].error_category,
                    "counts": {name: getattr(latest[item.item_id][0], name) for name in (
                        "added_count", "modified_count", "removed_count", "classified_count")},
                } if item.item_id in latest else None),
            } for item in items],
        }


@router.get("/status")
async def get_sync_status():
    return await status_for_user(_user_id())


class SyncRequest(BaseModel):
    item_ids: list[str] | None = Field(default=None, max_length=100)


@router.post("/request", status_code=202)
async def create_sync_request(request: SyncRequest):
    try:
        return await request_sync(_user_id(), request.item_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
