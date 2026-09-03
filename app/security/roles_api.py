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


class RoleTemplateRequest(BaseModel):
    template: str


# Phase 1 角色模板（§67）：预设角色 + 默认策略集，管理员一键创建（客户不必从零配 RBAC）
ROLE_TEMPLATES: dict[str, dict] = {
    "admin": {
        "name": "管理员",
        "description": "平台管理员：用户/策略/配置/队列等全部治理能力",
        "policies": [
            ("agent:use", "*"),
            ("run:create", "*"),
            ("tool:execute", "calc.add"),
            ("tool:execute", "echo"),
            ("tool:execute", "kb.search"),
            ("tool:execute", "graph.query"),
            ("model:configure", "*"),
            ("data:purge", "*"),
            ("release:publish", "*"),
            ("policy:manage", "*"),
            ("config:write", "*"),
            ("flags:write", "*"),
            ("cost:reconcile", "*"),
            ("release:ops", "*"),
            ("release:version:create", "*"),
            ("queue:ops", "*"),
            ("kb:ingest", "*"),
            ("memory:write", "*"),
            ("eval:write", "*"),
            ("graph:write", "*"),
        ],
    },
    "operator": {
        "name": "运维",
        "description": "日常运维：导入知识、运行对话、发布与队列治理",
        "policies": [
            ("agent:use", "*"),
            ("run:create", "*"),
            ("tool:execute", "calc.add"),
            ("tool:execute", "echo"),
            ("tool:execute", "kb.search"),
            ("tool:execute", "graph.query"),
            ("kb:ingest", "*"),
            ("memory:write", "*"),
            ("release:ops", "*"),
            ("release:version:create", "*"),
            ("queue:ops", "*"),
        ],
    },
    "reviewer": {
        "name": "评审",
        "description": "质检与评审：运行对话验证、评测写入、引用检索（无治理写权限）",
        "policies": [
            ("agent:use", "*"),
            ("run:create", "*"),
            ("tool:execute", "calc.add"),
            ("tool:execute", "kb.search"),
            ("tool:execute", "graph.query"),
            ("eval:write", "*"),
            ("graph:write", "*"),
        ],
    },
    "viewer": {
        "name": "访客",
        "description": "只读使用：运行对话、检索知识（无任何治理/写权限）",
        "policies": [
            ("agent:use", "*"),
            ("run:create", "*"),
            ("tool:execute", "kb.search"),
            ("tool:execute", "graph.query"),
        ],
    },
}


@router.get("/templates")
async def list_role_templates(
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    """Phase 1 角色模板列表（§67）：预设角色定义，供「从模板创建」。"""
    return {
        "templates": [
            {"key": k, "name": t["name"], "description": t["description"]} for k, t in ROLE_TEMPLATES.items()
        ]
    }


@router.post("/templates")
async def create_role_from_template(
    body: RoleTemplateRequest,
    request: Request,
    subject: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    """Phase 1 从模板创建角色（§67）：建角色 + 默认策略集，幂等（同名已存在则返回已存在）。"""
    state: AppState = request.app.state.agent
    tpl = ROLE_TEMPLATES.get(body.template)
    if tpl is None:
        raise AgentError(f"unknown role template: {body.template}", code="BAD_REQUEST")
    role_id = f"role-{uuid.uuid4().hex[:10]}"
    async with state.sessions() as s:
        existing = await s.scalar(
            select(RoleRow).where(
                RoleRow.tenant_id == subject.tenant_id, RoleRow.name == tpl["name"]
            )
        )
        if existing is not None:
            return {"id": existing.id, "name": existing.name, "created": False}
        s.add(
            RoleRow(
                id=role_id,
                tenant_id=subject.tenant_id,
                name=tpl["name"],
                description=tpl["description"],
            )
        )
        for action, resource in tpl["policies"]:
            s.add(
                PolicyRow(
                    id=f"pol-{uuid.uuid4().hex[:10]}",
                    tenant_id=subject.tenant_id,
                    role_id=role_id,
                    name=f"template-{body.template}",
                    effect="ALLOW",
                    action=action,
                    resource=resource,
                )
            )
        await s.commit()
    return {"id": role_id, "name": tpl["name"], "created": True}


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
