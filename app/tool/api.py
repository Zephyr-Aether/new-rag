"""Tool 控制面 + 执行 API（§32 MVP 子集）：

GET  /tools                    列出已注册工具（含风险级/权限/版本）
POST /tools/{ref}/execute      直接执行一个工具（走 ToolRuntime 全管线）
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common.contracts import Subject, ToolCallRequest, ToolCallResult
from app.common.errors import ToolNotFoundError
from app.gateway.deps import get_subject
from app.state import AppState

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolExecuteRequest(BaseModel):
    call_id: str | None = None  # 幂等键；缺省自动生成
    args: dict = Field(default_factory=dict)


@router.get("")
async def list_tools(request: Request) -> dict:
    state: AppState = request.app.state.agent
    return {
        "tools": [
            {
                "ref": t.ref,
                "description": t.description,
                "risk_level": t.risk_level,
                "permission": t.permission,
                "version": t.version,
                "input_schema": t.input_schema,
            }
            for t in state.registry.list()
        ]
    }


@router.post("/{ref}/execute", response_model=ToolCallResult)
async def execute_tool_endpoint(
    ref: str,
    body: ToolExecuteRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> ToolCallResult:
    state: AppState = request.app.state.agent
    if not any(t.ref == ref for t in state.registry.list()):
        raise ToolNotFoundError(f"tool not found: {ref}")
    call = ToolCallRequest(
        call_id=body.call_id or uuid.uuid4().hex,
        tenant_id=subject.tenant_id,
        user_id=subject.user_id,
        run_id="direct",
        tool_ref=ref,
        args=body.args,
    )
    return await state.tool_runtime.execute(call)
