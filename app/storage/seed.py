"""种子数据：默认租户/用户/Agent（Phase 0 最小身份，多租户模型自始成立）。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.passwords import client_sha256, hash_password
from app.storage.models import (
    AgentRow,
    AgentVersionRow,
    PolicyRow,
    RoleRow,
    TenantRow,
    UserRoleRow,
    UserRow,
)

# 默认种子用户密码（客户端传输时先 SHA-256）
DEFAULT_PASSWORD = "admin123"

DEFAULT_SYSTEM_PROMPT = (
    "你是企业 Agent 助手。只用给定上下文回答；不确定就说不知道，不要编造。如需调用工具，使用提供的工具。"
)

# 默认租户的最小权限（default-deny 下的显式 allow，§6.2）
DEFAULT_POLICIES: list[tuple[str, str]] = [
    ("agent:use", "*"),
    ("run:create", "*"),
    ("tool:execute", "calc.add"),
    ("tool:execute", "echo"),
    ("tool:execute", "kb.search"),
    ("tool:execute", "graph.query"),
    # §6.2 敏感操作权限（供 require_perm AOP 校验）
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
]


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def seed_defaults(session: AsyncSession, tenant_id: str, user_id: str) -> dict:
    """幂等种子：返回 (tenant_id, user_id, agent_id, agent_version)。"""
    tenant = await session.get(TenantRow, tenant_id)
    if tenant is None:
        session.add(TenantRow(id=tenant_id, name="Default Tenant"))

    user = await session.get(UserRow, user_id)
    if user is None:
        session.add(
            UserRow(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{user_id}@local",
                display_name="Default User",
                password_hash=hash_password(client_sha256(DEFAULT_PASSWORD)),
            )
        )

    # 管理员角色 + 绑定种子用户：前端据此识别「管理员」，普通用户不落入管理菜单
    admin_role = await session.scalar(
        select(RoleRow).where(RoleRow.tenant_id == tenant_id, RoleRow.name == "管理员")
    )
    if admin_role is None:
        admin_role = RoleRow(
            id=_uid("role"),
            tenant_id=tenant_id,
            name="管理员",
            description="平台管理员：用户/策略/配置/队列等治理能力",
        )
        session.add(admin_role)
        await session.flush()
    binding = await session.scalar(
        select(UserRoleRow).where(UserRoleRow.user_id == user_id, UserRoleRow.role_id == admin_role.id)
    )
    if binding is None:
        session.add(
            UserRoleRow(
                id=_uid("ur"),
                tenant_id=tenant_id,
                user_id=user_id,
                role_id=admin_role.id,
            )
        )

    # 默认策略（幂等：租户已存在任何策略则跳过）
    existing_policy = await session.scalar(
        select(PolicyRow.id).where(PolicyRow.tenant_id == tenant_id).limit(1)
    )
    if existing_policy is None:
        for action, resource in DEFAULT_POLICIES:
            session.add(
                PolicyRow(
                    id=_uid("pol"),
                    tenant_id=tenant_id,
                    name="default-allow",
                    effect="ALLOW",
                    action=action,
                    resource=resource,
                )
            )

    agent = await session.scalar(
        select(AgentRow).where(AgentRow.tenant_id == tenant_id, AgentRow.slug == "assistant")
    )
    if agent is None:
        agent_id = _uid("agent")
        agent = AgentRow(
            id=agent_id,
            tenant_id=tenant_id,
            owner_id=user_id,
            name="assistant",
            slug="assistant",
            status="ACTIVE",
        )
        session.add(agent)
        session.add(
            AgentVersionRow(
                id=_uid("av"),
                tenant_id=tenant_id,
                agent_id=agent_id,
                version=1,
                status="ACTIVE",
                system_prompt=DEFAULT_SYSTEM_PROMPT,
            )
        )
        await session.commit()
        return {"tenant_id": tenant_id, "user_id": user_id, "agent_id": agent_id, "agent_version": 1}

    await session.commit()
    version = await session.scalar(
        select(AgentVersionRow)
        .where(AgentVersionRow.tenant_id == tenant_id, AgentVersionRow.agent_id == agent.id)
        .order_by(AgentVersionRow.version.desc())
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "agent_id": agent.id,
        "agent_version": version.version if version else 1,
    }
