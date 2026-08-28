"""Approval API（§19 MVP 子集）：

GET  /approvals              待审批列表（控制台）
GET  /approvals/{id}         查询审批
POST /approvals/{id}/approve 批准
POST /approvals/{id}/reject  拒绝
"""

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.agent.runtime.runtime import resume_run
from app.common.errors import AgentError
from app.state import AppState

router = APIRouter(prefix="/approvals", tags=["approvals"])


class DecideRequest(BaseModel):
    approver_id: str = "approver"
    reason: str = ""


@router.get("")
async def list_approvals(request: Request, status: str | None = Query(default=None), limit: int = 50) -> dict:
    """审批列表（status 可空 = 全部状态，含历史 APPROVED/REJECTED/TIMEOUT）。"""
    state: AppState = request.app.state.agent
    rows = await state.approvals.query(status=status, limit=limit)
    return {"rows": rows, "total": len(rows)}


@router.get("/{approval_id}")
async def get_approval(approval_id: str, request: Request) -> dict:
    state: AppState = request.app.state.agent
    row = await state.approvals.get(approval_id)
    if row is None:
        raise AgentError(f"approval not found: {approval_id}", code="APPROVAL_NOT_FOUND")
    return row


@router.post("/{approval_id}/approve")
async def approve_approval(approval_id: str, body: DecideRequest, request: Request) -> dict:
    state: AppState = request.app.state.agent
    status = await state.approvals.decide(
        approval_id, approver_id=body.approver_id, approve=True, reason=body.reason
    )
    # §19 批准后自动续跑：定位被该审批阻塞的 run，从检查点重放（工具按幂等键至多一次）
    resumed = None
    if status == "APPROVED":
        row = await state.approvals.get(approval_id)
        if row and row["call_id"]:
            run_id = await state.store.find_run_by_tool_call(row["call_id"])
            if run_id:
                run = await state.store.get_run(run_id)
                if run and run["state"] == "WAITING_APPROVAL":
                    result = await resume_run(run_id, state.deps())
                    resumed = {"run_id": run_id, "state": result.state}
    return {"approval_id": approval_id, "status": status, "resumed": resumed}


@router.post("/{approval_id}/reject")
async def reject_approval(approval_id: str, body: DecideRequest, request: Request) -> dict:
    state: AppState = request.app.state.agent
    status = await state.approvals.decide(
        approval_id, approver_id=body.approver_id, approve=False, reason=body.reason
    )
    return {"approval_id": approval_id, "status": status}
