"""租户管理 API（Phase 1 对外产品）：平台管理员创建租户 + 初始管理员 + 默认策略。

POST /tenants  创建租户（租户 + 初始管理员 + 默认策略，一次 onboarding）
GET  /tenants  列出租户
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import require_perm
from app.gateway.passwords import hash_password
from app.state import AppState
from app.storage.models import PolicyRow, RoleRow, TenantRow, UserRoleRow, UserRow
from app.storage.seed import DEFAULT_POLICIES

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreate(BaseModel):
    tenant_id: str = ""  # 留空自动生成 tenant-xxxx
    name: str = Field(min_length=1)
    admin_user_id: str = Field(min_length=1)
    admin_email: str = ""
    admin_password: str = ""  # 客户端已 SHA-256；为空则该管理员无密码（后续重置）


@router.post("")
async def create_tenant(
    body: TenantCreate,
    request: Request,
    _: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    tenant_id = body.tenant_id or f"tenant-{uuid.uuid4().hex[:8]}"
    async with state.sessions() as s:
        if await s.get(TenantRow, tenant_id) is not None:
            raise AgentError("tenant exists", code="TENANT_EXISTS")
        if await s.get(UserRow, body.admin_user_id) is not None:
            raise AgentError("admin user exists", code="USER_EXISTS")
        s.add(TenantRow(id=tenant_id, name=body.name))
        s.add(
            UserRow(
                id=body.admin_user_id,
                tenant_id=tenant_id,
                email=body.admin_email or f"{body.admin_user_id}@local",
                display_name=f"{body.name} Admin",
                password_hash=hash_password(body.admin_password) if body.admin_password else None,
                must_change_password=bool(body.admin_password),
            )
        )
        # Phase 1 租户生命周期：默认管理员角色 + 绑定（与 seed_defaults 一致，避免新租户无角色）
        admin_role = RoleRow(
            id=f"role-{uuid.uuid4().hex[:10]}",
            tenant_id=tenant_id,
            name="管理员",
            description="平台管理员：用户/策略/配置/队列等治理能力",
        )
        s.add(admin_role)
        s.add(
            UserRoleRow(
                id=f"ur-{uuid.uuid4().hex[:10]}",
                tenant_id=tenant_id,
                user_id=body.admin_user_id,
                role_id=admin_role.id,
            )
        )
        for action, resource in DEFAULT_POLICIES:
            s.add(
                PolicyRow(
                    id=f"pol-{uuid.uuid4().hex[:12]}",
                    tenant_id=tenant_id,
                    name="default-allow",
                    effect="ALLOW",
                    action=action,
                    resource=resource,
                )
            )
        await s.commit()
    return {"ok": True, "tenant_id": tenant_id, "admin_user_id": body.admin_user_id}


@router.get("")
async def list_tenants(
    request: Request,
    _: Annotated[Subject, Depends(require_perm("policy:manage", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        rows = (await s.scalars(select(TenantRow).order_by(TenantRow.name))).all()
        return {"tenants": [{"id": t.id, "name": t.name} for t in rows]}
