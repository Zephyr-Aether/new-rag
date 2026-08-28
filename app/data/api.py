"""Data Lifecycle API（§26）：租户数据清除 / 保留期清扫。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject, require_perm
from app.state import AppState

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/tenant/{tenant_id}/purge")
async def purge_tenant(
    tenant_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("data:purge", "*"))],  # 权限 AOP
) -> dict:
    """§26.2 删除租户全部数据（仅限自己的租户，防越权清除）。"""
    if subject.tenant_id != tenant_id:
        raise AgentError("cannot purge another tenant", code="POLICY_DENIED")
    state: AppState = request.app.state.agent
    return await state.data_lifecycle.purge_tenant(tenant_id)


@router.post("/sweep")
async def retention_sweep(
    request: Request,
    retention_days: int = Query(default=30, ge=1),
    audit_days: int | None = Query(default=None, ge=1),
    payload_days: int | None = Query(default=None, ge=1),
) -> dict:
    state: AppState = request.app.state.agent
    return await state.data_lifecycle.retention_sweep(
        retention_days=retention_days, audit_days=audit_days, payload_days=payload_days
    )
