"""AuditService（§6.7）：权限决策 / 工具执行 / 数据访问 全量落审计。

与 Trace 同源（trace_id），保证"这条 trace 里为什么拒绝"可查。
detail 落库前统一脱敏（§13.3）。
"""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.security.redact import mask_object
from app.storage.models import AuditLogRow


def _now() -> datetime:
    return datetime.now(UTC)


class AuditService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def record(
        self,
        *,
        tenant_id: str,
        actor_id: str = "",
        action: str,
        resource: str = "",
        resource_id: str = "",
        outcome: str,
        detail: dict | None = None,
        trace_id: str = "",
    ) -> None:
        async with self.sessions() as s:
            s.add(
                AuditLogRow(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    trace_id=trace_id,
                    action=action,
                    resource=resource,
                    resource_id=resource_id,
                    outcome=outcome,
                    detail_json=json.dumps(mask_object(detail or {}), ensure_ascii=False),
                )
            )
            await s.commit()

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        since_hours: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """§6.7 审计查询：按租户/动作/资源/时间筛选。"""
        async with self.sessions() as s:
            q = select(AuditLogRow).order_by(AuditLogRow.created_at.desc())
            if tenant_id:
                q = q.where(AuditLogRow.tenant_id == tenant_id)
            if action:
                q = q.where(AuditLogRow.action == action)
            if resource:
                q = q.where(AuditLogRow.resource == resource)
            if since_hours:
                q = q.where(AuditLogRow.created_at >= _now() - timedelta(hours=since_hours))
            rows = (await s.scalars(q.limit(limit))).all()
            return [
                {
                    "id": r.id,
                    "tenant_id": r.tenant_id,
                    "actor_id": r.actor_id,
                    "trace_id": r.trace_id,
                    "action": r.action,
                    "resource": r.resource,
                    "resource_id": r.resource_id,
                    "outcome": r.outcome,
                    "detail_json": r.detail_json,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
