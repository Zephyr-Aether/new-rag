"""用户管理 API（Phase 1 对外产品）：租户管理员维护用户与密码。

GET    /users             列出当前租户用户（含角色）
POST   /users             创建用户（密码可选，客户端 SHA-256 后提交）
PUT    /users/{id}        更新用户（显示名 / 邮箱 / 启用 / 密码重置 / 角色）
DELETE /users/{id}        软删除用户（置 isDelete=1，同时解除角色关联）
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import require_perm
from app.gateway.passwords import hash_password
from app.state import AppState
from app.storage.models import UserRoleRow, UserRow

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    email: str = ""
    display_name: str = ""
    password: str = ""  # 客户端已 SHA-256，非明文
    role_ids: list[str] = []


class UserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    enabled: bool | None = None
    password: str | None = None  # 重置密码（客户端 SHA-256）
    role_ids: list[str] | None = None


async def _sync_roles(s, tenant_id: str, user_id: str, role_ids: list[str]) -> None:
    await s.execute(
        delete(UserRoleRow).where(UserRoleRow.tenant_id == tenant_id, UserRoleRow.user_id == user_id)
    )
    for role_id in role_ids:
        s.add(
            UserRoleRow(
                id=f"ur-{uuid.uuid4().hex[:10]}", tenant_id=tenant_id, user_id=user_id, role_id=role_id
            )
        )


@router.get("")
async def list_users(
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        users = (
            await s.scalars(
                select(UserRow).where(
                    UserRow.tenant_id == subject.tenant_id,
                    UserRow.isDelete == False,  # 软删除：已删除的不再列出
                )
            )
        ).all()
        links = (await s.scalars(select(UserRoleRow).where(UserRoleRow.tenant_id == subject.tenant_id))).all()
    roles_by_user: dict[str, list[str]] = {}
    for link in links:
        roles_by_user.setdefault(link.user_id, []).append(link.role_id)
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "enabled": u.enabled,
                "must_change_password": u.must_change_password,
                "role_ids": roles_by_user.get(u.id, []),
            }
            for u in users
        ]
    }


@router.post("")
async def create_user(
    body: UserCreate,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        existing = await s.get(UserRow, body.user_id)
        if existing is not None:
            raise AgentError("user already exists", code="USER_EXISTS")
        s.add(
            UserRow(
                id=body.user_id,
                tenant_id=subject.tenant_id,
                email=body.email or f"{body.user_id}@local",
                display_name=body.display_name or body.user_id,
                password_hash=hash_password(body.password) if body.password else None,
                must_change_password=bool(body.password),  # 管理员配的密码，首次登录需改
            )
        )
        if body.role_ids:
            await _sync_roles(s, subject.tenant_id, body.user_id, body.role_ids)
        await s.commit()
    return {"ok": True, "id": body.user_id}


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        user = await s.get(UserRow, user_id)
        if user is None or user.tenant_id != subject.tenant_id:
            raise AgentError("user not found", code="USER_NOT_FOUND")
        if body.display_name is not None:
            user.display_name = body.display_name
        if body.email is not None:
            user.email = body.email
        if body.enabled is not None:
            user.enabled = body.enabled
        if body.password:
            user.password_hash = hash_password(body.password)
            user.must_change_password = True  # 管理员重置密码后，用户需在下次登录改密
        if body.role_ids is not None:
            await _sync_roles(s, subject.tenant_id, user_id, body.role_ids)
        await s.commit()
    return {"ok": True, "id": user_id}


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        user = await s.get(UserRow, user_id)
        if user is None or user.tenant_id != subject.tenant_id:
            raise AgentError("user not found", code="USER_NOT_FOUND")
        await s.execute(
            delete(UserRoleRow).where(
                UserRoleRow.tenant_id == subject.tenant_id, UserRoleRow.user_id == user_id
            )
        )
        user.isDelete = True  # 软删除：删除某条 = 修改 isDelete 字段，不删行
        await s.commit()
    return {"ok": True, "deleted": user_id}
