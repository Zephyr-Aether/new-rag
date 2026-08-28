"""角色管理 API（§6.2 RBAC）：角色是一组策略的命名集合，用户通过 user_roles 挂到角色。

GET    /roles                    列出当前租户的角色
POST   /roles                    创建角色
PUT    /roles/{id}               更新角色（名称 / 描述）
DELETE /roles/{id}               删除角色（连同其策略与关联）
POST   /roles/{id}/users         把用户加入角色
DELETE /roles/{id}/users/{uid}   把用户移出角色
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import require_perm
from app.state import AppState
from app.storage.models import PolicyRow, RoleRow, UserRoleRow

router = APIRouter(prefix="/roles", tags=["roles"])


class RoleRequest(BaseModel):
    name: str
    description: str = ""


class RoleUserRequest(BaseModel):
    user_id: str


class RoleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("")
async def list_roles(
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        roles = await s.scalars(
            select(RoleRow).where(RoleRow.tenant_id == subject.tenant_id).order_by(RoleRow.name)
        )
        roles = list(roles)
        user_rows = await s.scalars(select(UserRoleRow).where(UserRoleRow.tenant_id == subject.tenant_id))
        members: dict[str, list[str]] = {}
        for ur in user_rows:
            members.setdefault(ur.role_id, []).append(ur.user_id)
        return {
            "roles": [
                {"id": r.id, "name": r.name, "description": r.description, "users": members.get(r.id, [])}
                for r in roles
            ]
        }


@router.post("")
async def create_role(
    body: RoleRequest,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    role_id = f"role-{uuid.uuid4().hex[:10]}"
    async with state.sessions() as s:
        s.add(RoleRow(id=role_id, tenant_id=subject.tenant_id, name=body.name, description=body.description))
        await s.commit()
    return {"id": role_id, "name": body.name}


@router.put("/{role_id}")
async def update_role(
    role_id: str,
    body: RoleUpdateRequest,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    """更新角色名称 / 描述（字段缺省=保持不变）。"""
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        row = await s.get(RoleRow, role_id)
        if row is None or row.tenant_id != subject.tenant_id:
            raise AgentError("role not found", code="ROLE_NOT_FOUND")
        if body.name is not None:
            if not body.name.strip():
                raise AgentError("name must not be empty", code="BAD_REQUEST")
            row.name = body.name.strip()
        if body.description is not None:
            row.description = body.description
        await s.commit()
    return {"ok": True, "id": role_id}


@router.delete("/{role_id}")
async def delete_role(
    role_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        row = await s.get(RoleRow, role_id)
        if row is None or row.tenant_id != subject.tenant_id:
            raise AgentError("role not found", code="ROLE_NOT_FOUND")
        await s.execute(delete(UserRoleRow).where(UserRoleRow.role_id == role_id))
        await s.execute(delete(PolicyRow).where(PolicyRow.role_id == role_id))
        await s.delete(row)
        await s.commit()
    return {"ok": True, "deleted": role_id}


@router.post("/{role_id}/users")
async def add_user_to_role(
    role_id: str,
    body: RoleUserRequest,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        role = await s.get(RoleRow, role_id)
        if role is None or role.tenant_id != subject.tenant_id:
            raise AgentError("role not found", code="ROLE_NOT_FOUND")
        exists = await s.scalar(
            select(UserRoleRow.id)
            .where(
                UserRoleRow.tenant_id == subject.tenant_id,
                UserRoleRow.user_id == body.user_id,
                UserRoleRow.role_id == role_id,
            )
            .limit(1)
        )
        if not exists:
            s.add(
                UserRoleRow(
                    id=f"ur-{uuid.uuid4().hex[:10]}",
                    tenant_id=subject.tenant_id,
                    user_id=body.user_id,
                    role_id=role_id,
                )
            )
            await s.commit()
    return {"ok": True, "role_id": role_id, "user_id": body.user_id}


@router.delete("/{role_id}/users/{user_id}")
async def remove_user_from_role(
    role_id: str,
    user_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        await s.execute(
            delete(UserRoleRow).where(
                UserRoleRow.tenant_id == subject.tenant_id,
                UserRoleRow.role_id == role_id,
                UserRoleRow.user_id == user_id,
            )
        )
        await s.commit()
    return {"ok": True}
