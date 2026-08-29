"""Events API（§28.2）：事件 Outbox 发布 / 查询 / 重放。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.common.contracts import Subject
from app.gateway.deps import get_subject
from app.state import AppState

router = APIRouter(prefix="/events", tags=["events"])


class PublishEventRequest(BaseModel):
    event_type: str = Field(min_length=1)
    aggregate_id: str = ""
    payload: dict = Field(default_factory=dict)
    dedupe_key: str | None = None


@router.post("/publish")
async def publish_event(
    body: PublishEventRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    return await state.event_outbox.publish(
        event_type=body.event_type,
        tenant_id=subject.tenant_id,
        aggregate_id=body.aggregate_id,
        payload=body.payload,
        dedupe_key=body.dedupe_key,
    )


@router.get("")
async def list_events(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    state: AppState = request.app.state.agent
    rows = await state.event_outbox.list_events(
        tenant_id=subject.tenant_id, event_type=event_type, limit=limit
    )
    return {"rows": rows, "total": len(rows)}


@router.get("/stats")
async def events_stats(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """事件统计：按类型计数 + 近 24h 每小时发布量（监控图用）。"""
    state: AppState = request.app.state.agent
    return await state.event_outbox.stats(tenant_id=subject.tenant_id)


@router.post("/replay/{aggregate_id}")
async def replay_events(
    aggregate_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    rows = await state.event_outbox.replay(tenant_id=subject.tenant_id, aggregate_id=aggregate_id)
    return {"aggregate_id": aggregate_id, "events": rows, "total": len(rows)}


@router.get("/aggregate/{aggregate_id}/state")
async def aggregate_state(
    aggregate_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """聚合当前状态快照（事件数/类型分布/最后一条），供重放前后对比。"""
    state: AppState = request.app.state.agent
    return await state.event_outbox.aggregate_state(tenant_id=subject.tenant_id, aggregate_id=aggregate_id)
