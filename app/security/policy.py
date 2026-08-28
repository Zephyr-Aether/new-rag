"""Policy Engine（§6.2）：RBAC/ABAC 决策，默认拒绝。

规则：
- 显式 DENY 优先于 ALLOW；
- 任一 ALLOW 命中即放行；
- 无任何命中 => 默认拒绝（default-deny）。
ABAC condition 字段已留（condition_json），Phase 后启用。
"""

from pydantic import BaseModel
from sqlalchemy import select

from app.common.contracts import Subject
from app.storage.models import PolicyRow, UserRoleRow


class PolicyDecision(BaseModel):
    allowed: bool
    policy_id: str | None = None
    reason: str


class PolicyEngine:
    def __init__(self, sessions):
        self.sessions = sessions

    async def _user_role_ids(self, subject: Subject) -> list[str]:
        async with self.sessions() as s:
            rows = await s.scalars(
                select(UserRoleRow.role_id).where(
                    UserRoleRow.tenant_id == subject.tenant_id, UserRoleRow.user_id == subject.user_id
                )
            )
            return list(rows.all())

    async def _rows_for(self, subject: Subject) -> list[PolicyRow]:
        role_ids = await self._user_role_ids(subject)
        async with self.sessions() as s:
            q = select(PolicyRow).where(
                PolicyRow.tenant_id == subject.tenant_id,
                PolicyRow.enabled == True,  # noqa: E712
            )
            # 用户级 / 角色级 / 租户级策略都参与
            user_cond = (PolicyRow.user_id.is_(None)) | (PolicyRow.user_id == subject.user_id)
            if role_ids:
                q = q.where(user_cond & ((PolicyRow.role_id.is_(None)) | (PolicyRow.role_id.in_(role_ids))))
            else:
                q = q.where(user_cond & (PolicyRow.role_id.is_(None)))
            return list((await s.scalars(q)).all())

    async def is_allowed(self, subject: Subject, action: str, resource: str) -> PolicyDecision:
        rows = await self._rows_for(subject)
        deny: PolicyRow | None = None
        allow: PolicyRow | None = None
        for row in rows:
            if not self._matches(row, action, resource):
                continue
            if row.effect == "DENY":
                deny = row
                break  # DENY 优先，命中即结束
            if row.effect == "ALLOW" and allow is None:
                allow = row

        if deny is not None:
            return PolicyDecision(allowed=False, policy_id=deny.id, reason=f"deny by policy {deny.name}")
        if allow is not None:
            return PolicyDecision(allowed=True, policy_id=allow.id, reason=f"allow by policy {allow.name}")
        return PolicyDecision(allowed=False, reason="default-deny (no matching policy)")

    async def list_actions(self, subject: Subject) -> dict:
        """列出该主体对每个 action 的生效权限（ALLOW 集合减去被 DENY 的）。前端据此显隐按钮。"""
        allowed: set[str] = set()
        denied: set[str] = set()
        for row in await self._rows_for(subject):
            if row.resource != "*":
                continue  # 资源级策略不进入 action 级判定（页面按 action 显隐）
            if row.effect == "ALLOW":
                allowed.add(row.action)
            else:
                denied.add(row.action)
        denied &= allowed  # 仅当同一 action 也有 ALLOW 时，DENY 才需要体现
        return {"allowed": sorted(allowed - denied), "denied": sorted(denied)}

    @staticmethod
    def _matches(row: PolicyRow, action: str, resource: str) -> bool:
        action_ok = row.action == "*" or row.action == action
        resource_ok = row.resource == "*" or row.resource == resource
        return action_ok and resource_ok
