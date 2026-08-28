"""Cost API（§50）：
GET  /cost/overview   按 tenant/user/agent/version 聚合 runs 的 tokens/cost
POST /cost/reconcile  账单对账：估算 cost 按权威价校正（actual_cost + run.cost）
GET  /cost/growth     Token/Run 环比 + 增长告警
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.common.contracts import Subject
from app.gateway.deps import get_subject, require_perm
from app.state import AppState

router = APIRouter(prefix="/cost", tags=["cost"])


@router.post("/reconcile")
async def cost_reconcile(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("cost:reconcile", "*"))],
    tenant_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
) -> dict:
    state: AppState = request.app.state.agent
    return await state.cost_service.reconcile(tenant_id=tenant_id, run_id=run_id)


@router.get("/overview")
async def cost_overview(
    request: Request,
    tenant_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    since_days: int = Query(default=7, ge=1),
) -> dict:
    state: AppState = request.app.state.agent
    rows = await state.cost_service.overview(tenant_id=tenant_id, user_id=user_id, since_days=since_days)
    return {"rows": rows, "total": len(rows)}


@router.get("/growth")
async def cost_growth(request: Request) -> dict:
    state: AppState = request.app.state.agent
    return {"rows": await state.cost_service.growth()}


@router.get("/usage")
async def cost_usage(
    request: Request,
    tenant_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """租户×日用量（对客户计费/用量报表）：runs/tokens/cost 按天聚合。"""
    state: AppState = request.app.state.agent
    return {"rows": await state.cost_service.usage(tenant_id=tenant_id, days=days), "days": days}
