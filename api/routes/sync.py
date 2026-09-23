"""M4 manual sync request; the jobs process performs the work."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.jobs import request_sync
from api.routes.plaid import _user_id

router = APIRouter(prefix="/sync")


class SyncRequest(BaseModel):
    item_ids: list[str] | None = Field(default=None, max_length=100)


@router.post("/request", status_code=202)
async def create_sync_request(request: SyncRequest):
    try:
        return await request_sync(_user_id(), request.item_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
