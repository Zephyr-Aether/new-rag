"""密钥管理 API（Phase 1）：加密存储敏感凭据（LLM key / 工具凭据等）。

GET    /secrets        列出现有密钥 ref（不返回值）
POST   /secrets        新增 / 更新密钥 {ref, value}
DELETE /secrets/{ref}  删除密钥
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common.contracts import Subject
from app.gateway.deps import require_perm
from app.state import AppState

router = APIRouter(prefix="/secrets", tags=["secrets"])


class SecretWrite(BaseModel):
    ref: str = Field(min_length=1)
    value: str


@router.get("")
async def list_secrets(
    request: Request,
    _: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    refs = await state.secret_manager.list()
    return {"secrets": [{"ref": r} for r in refs]}


@router.post("")
async def set_secret(
    body: SecretWrite,
    request: Request,
    _: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    await state.secret_manager.set(body.ref, body.value)
    return {"ok": True, "ref": body.ref}


@router.delete("/{ref}")
async def delete_secret(
    ref: str,
    request: Request,
    _: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    await state.secret_manager.delete(ref)
    return {"ok": True, "deleted": ref}
