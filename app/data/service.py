"""DataLifecycleService（§26）：租户数据清除 + 保留期清扫。

purge_tenant：按 FK 依赖倒序硬删该租户全部数据（GDPR 风格"用户删除数据后"）。
retention_sweep：删除超过保留期的已完结 run 及其子数据。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.storage.models import (
    AgentRow,
    AgentRunRow,
    AgentStepRow,
    AgentVersionRow,
    ApprovalRow,
    AuditLogRow,
    ChunkRow,
    ConfigurationRow,
    DocumentRow,
    EntityRow,
    EvaluationCaseRow,
    EvaluationDatasetRow,
    FeatureFlagRow,
    JobRow,
    KnowledgeFactRow,
    LLMCallRow,
    MemoryRow,
    PolicyRow,
    RegressionRunRow,
    SessionRow,
    TenantRow,
    ToolCallRow,
    TracePayloadRow,
    UserRow,
)


def _now() -> datetime:
    return datetime.now(UTC)


class DataLifecycleService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def purge_tenant(self, tenant_id: str) -> dict:
        """硬删该租户全部数据（子表先删，最后删租户/用户）。"""
        async with self.sessions() as s:
            run_ids = (
                await s.scalars(select(AgentRunRow.run_id).where(AgentRunRow.tenant_id == tenant_id))
            ).all()
            counts: dict[str, int] = {"steps": len(run_ids)}
            if run_ids:
                await s.execute(delete(AgentStepRow).where(AgentStepRow.run_id.in_(run_ids)))
                await s.execute(delete(TracePayloadRow).where(TracePayloadRow.run_id.in_(run_ids)))
            for model in (
                ToolCallRow,
                LLMCallRow,
                EvaluationCaseRow,
                RegressionRunRow,
                AgentVersionRow,
                SessionRow,
                AgentRunRow,
                ChunkRow,
                DocumentRow,
                MemoryRow,
                EntityRow,
                KnowledgeFactRow,
                PolicyRow,
                AuditLogRow,
                ApprovalRow,
                JobRow,
                ConfigurationRow,
                FeatureFlagRow,
                EvaluationDatasetRow,
                UserRow,
            ):
                r = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                counts[model.__tablename__] = r.rowcount
            r = await s.execute(delete(AgentRow).where(AgentRow.tenant_id == tenant_id))
            counts["agents"] = r.rowcount
            r = await s.execute(delete(TenantRow).where(TenantRow.id == tenant_id))
            counts["tenants"] = r.rowcount
            await s.commit()
        return {"tenant_id": tenant_id, "deleted": counts}

    async def retention_sweep(
        self,
        *,
        retention_days: int = 30,
        audit_days: int | None = None,
        payload_days: int | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """§26.2 差异化保留期：run 子数据按 retention_days；审计/payload 各自独立 cutoff。"""
        audit_days = audit_days if audit_days is not None else retention_days
        payload_days = payload_days if payload_days is not None else retention_days
        run_cutoff = _now() - timedelta(days=retention_days)
        audit_cutoff = _now() - timedelta(days=audit_days)
        payload_cutoff = _now() - timedelta(days=payload_days)
        async with self.sessions() as s:
            # 1) run 及其子数据（steps/tool_calls/llm_calls/payloads）按 run 保留期
            q = select(AgentRunRow.run_id).where(AgentRunRow.finished_at < run_cutoff)
            if tenant_id:
                q = q.where(AgentRunRow.tenant_id == tenant_id)
            run_ids = (await s.scalars(q)).all()
            if run_ids:
                await s.execute(delete(AgentStepRow).where(AgentStepRow.run_id.in_(run_ids)))
                await s.execute(delete(ToolCallRow).where(ToolCallRow.run_id.in_(run_ids)))
                await s.execute(delete(LLMCallRow).where(LLMCallRow.run_id.in_(run_ids)))
                await s.execute(delete(TracePayloadRow).where(TracePayloadRow.run_id.in_(run_ids)))
                await s.execute(delete(AgentRunRow).where(AgentRunRow.run_id.in_(run_ids)))
            # 2) 审计日志按 audit_days（独立于 run 保留期，可更长）
            await s.execute(delete(AuditLogRow).where(AuditLogRow.created_at < audit_cutoff))
            # 3) Trace payload 按 payload_days（可更短）
            await s.execute(delete(TracePayloadRow).where(TracePayloadRow.created_at < payload_cutoff))
            await s.commit()
            return {
                "deleted_runs": len(run_ids),
                "retention_days": retention_days,
                "audit_days": audit_days,
                "payload_days": payload_days,
            }
