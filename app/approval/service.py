"""ApprovalService（§19）：创建审批 / 决策（approve/reject）/ 超时。"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.storage.models import ApprovalRow


def _now() -> datetime:
    return datetime.now(UTC)


def _to_dict(row: ApprovalRow) -> dict:
    return {
        "approval_id": row.id,
        "tenant_id": row.tenant_id,
        "requester_id": row.requester_id,
        "approver_id": row.approver_id,
        "tool_ref": row.tool_ref,
        "call_id": row.call_id,
        "risk_level": row.risk_level,
        "status": row.status,
        "reason": row.reason,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
    }


class ApprovalService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def find_for_call(self, *, tenant_id: str, call_id: str, tool_ref: str) -> dict | None:
        """按 (tenant, call_id, tool_ref) 找最新审批——批准/拒绝结果对同一 call 幂等（§19）。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(ApprovalRow)
                .where(
                    ApprovalRow.tenant_id == tenant_id,
                    ApprovalRow.call_id == call_id,
                    ApprovalRow.tool_ref == tool_ref,
                )
                .order_by(ApprovalRow.created_at.desc())
            )
        return _to_dict(row) if row else None

    async def create(
        self,
        *,
        tenant_id: str,
        requester_id: str,
        tool_ref: str,
        call_id: str,
        risk_level: str,
        reason: str = "",
        ttl_hours: int = 24,
    ) -> str:
        approval_id = uuid.uuid4().hex
        async with self.sessions() as s:
            s.add(
                ApprovalRow(
                    id=approval_id,
                    tenant_id=tenant_id,
                    requester_id=requester_id,
                    tool_ref=tool_ref,
                    call_id=call_id,
                    risk_level=risk_level,
                    reason=reason,
                    expires_at=_now() + timedelta(hours=ttl_hours),
                )
            )
            await s.commit()
        return approval_id

    async def get(self, approval_id: str) -> dict | None:
        async with self.sessions() as s:
            row = await s.get(ApprovalRow, approval_id)
            if row is None:
                return None
            return {
                "approval_id": row.id,
                "tenant_id": row.tenant_id,
                "requester_id": row.requester_id,
                "approver_id": row.approver_id,
                "tool_ref": row.tool_ref,
                "call_id": row.call_id,
                "risk_level": row.risk_level,
                "status": row.status,
                "reason": row.reason,
                "expires_at": row.expires_at,
            }

    async def query(
        self, *, tenant_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        """审批列表（status 可空 = 全部状态，§19 历史可查）。"""
        async with self.sessions() as s:
            q = select(ApprovalRow).order_by(ApprovalRow.created_at.desc())
            if tenant_id:
                q = q.where(ApprovalRow.tenant_id == tenant_id)
            if status:
                q = q.where(ApprovalRow.status == status)
            rows = (await s.scalars(q.limit(limit))).all()
            return [_to_dict(r) for r in rows]

    async def list_pending(self, *, tenant_id: str | None = None, limit: int = 50) -> list[dict]:
        """待审批列表（兼容别名，控制台默认视图）。"""
        return await self.query(tenant_id=tenant_id, status="PENDING", limit=limit)

    async def decide(self, approval_id: str, *, approver_id: str, approve: bool, reason: str = "") -> str:
        """返回新状态 APPROVED/REJECTED；已过期返回 TIMEOUT 不生效。"""
        async with self.sessions() as s:
            row = await s.get(ApprovalRow, approval_id)
            if row is None:
                return "NOT_FOUND"
            if row.status != "PENDING":
                return row.status
            # SQLite 返回 naive datetime，统一按 aware 比较（§3.4 审批超时）
            expires = row.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if _now() > expires:
                row.status = "TIMEOUT"
                row.decided_at = _now()
                await s.commit()
                return "TIMEOUT"
            row.status = "APPROVED" if approve else "REJECTED"
            row.approver_id = approver_id
            row.reason = reason or row.reason
            row.decided_at = _now()
            await s.commit()
            return row.status
