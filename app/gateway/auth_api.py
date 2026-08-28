"""Auth API（§27）：POST /auth/token mint JWT（密码登录；未设密码的用户兼容 dev 放行）。

约定：客户端把密码做 SHA-256 后再提交（password 字段非明文），服务端 pbkdf2 校验。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.auth import create_access_token
from app.gateway.deps import get_subject
from app.gateway.passwords import hash_password, verify_password
from app.state import AppState
from app.storage.models import UserRow

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    tenant_id: str
    user_id: str
    roles: list[str] = []
    password: str = ""  # 客户端已 SHA-256 哈希，非明文


class ChangePasswordRequest(BaseModel):
    old_password: str = ""  # 客户端已 SHA-256；用户已设密码时必须匹配
    new_password: str  # 客户端已 SHA-256，非明文


@router.post("/token")
async def issue_token(body: TokenRequest, request: Request) -> dict:
    state: AppState = request.app.state.agent
    settings = state.settings
    async with state.sessions() as s:
        user = await s.scalar(
            select(UserRow).where(UserRow.id == body.user_id, UserRow.tenant_id == body.tenant_id)
        )
    if user is None:
        raise AgentError("用户不存在", code="AUTH_INVALID_CREDENTIALS")
    if user.isDelete:
        raise AgentError("用户不存在", code="AUTH_INVALID_CREDENTIALS")
    if not user.enabled:
        raise AgentError("用户已禁用", code="AUTH_DISABLED")
    if user.password_hash:
        if not body.password or not verify_password(body.password, user.password_hash):
            raise AgentError("用户名或密码错误", code="AUTH_INVALID_CREDENTIALS")
    token = create_access_token(settings, tenant_id=body.tenant_id, user_id=body.user_id, roles=body.roles)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.auth_jwt_expires_s,
        "tenant_id": body.tenant_id,
        "user_id": body.user_id,
        "must_change_password": bool(user.must_change_password),
    }


@router.post("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """修改当前用户密码：校验旧密码（已设时），成功后清除 must_change_password。"""
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        user = await s.get(UserRow, subject.user_id)
        if user is None or user.tenant_id != subject.tenant_id:
            raise AgentError("user not found", code="USER_NOT_FOUND")
        if user.password_hash:
            if not body.old_password or not verify_password(body.old_password, user.password_hash):
                raise AgentError("原密码错误", code="AUTH_INVALID_CREDENTIALS")
        user.password_hash = hash_password(body.new_password)
        user.must_change_password = False
        await s.commit()
    return {"ok": True}


@router.get("/me")
async def me(request: Request, subject: Annotated[Subject, Depends(get_subject)]) -> dict:
    """当前用户的生效权限（前端据此显隐按钮）。"""
    state: AppState = request.app.state.agent
    perms = await state.policy.list_actions(subject)
    return {"user_id": subject.user_id, "tenant_id": subject.tenant_id, **perms}
