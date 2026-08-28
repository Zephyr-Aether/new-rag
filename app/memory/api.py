"""Memory API（§12 MVP 子集）：

POST   /memory             写一条记忆（scope/memory_type/source_trust/TTL）
POST   /memory/recall      召回（严格 tenant+user 隔离）
DELETE /memory/{id}        删除（软删）
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject, require_perm
from app.state import AppState

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryWriteRequest(BaseModel):
    scope: str = "USER"
    memory_type: str = "SEMANTIC"
    content: str
    source: str = ""
    source_trust: str = "trusted"
    ttl_days: int | None = None


class MemoryRecallRequest(BaseModel):
    query: str = ""
    k: int = Field(default=5, ge=1, le=50)


@router.post("")
async def write_memory(
    body: MemoryWriteRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("memory:write", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    return await state.memory_service.write(
        subject,
        scope=body.scope,
        memory_type=body.memory_type,
        content=body.content,
        source=body.source,
        source_trust=body.source_trust,
        ttl_days=body.ttl_days,
    )


@router.post("/recall")
async def recall_memory(
    body: MemoryRecallRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    entries = await state.memory_service.recall(subject, query=body.query, k=body.k)
    return {"entries": entries}


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    ok = await state.memory_service.delete(subject, memory_id)
    if not ok:
        raise AgentError("memory not found or not owned", code="MEMORY_NOT_FOUND")
    return {"memory_id": memory_id, "deleted": True}
