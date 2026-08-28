"""§26 数据生命周期：租户清除 + 保留期清扫。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.data.service import DataLifecycleService
from app.storage.models import (
    AgentRow,
    AgentRunRow,
    AgentStepRow,
    AgentVersionRow,
    TenantRow,
)


async def test_purge_tenant_removes_all_data(sessions, deps):
    """§26.2 租户清除：agent/version/run/steps 全部删除，租户行一并删除。"""
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.runtime import execute_run
    from app.common.contracts import RunInput

    async with sessions() as s:
        s.add(AgentRow(id="ag-purge", tenant_id="t", owner_id="u", name="a", slug="a", status="ACTIVE"))
        s.add(
            AgentVersionRow(
                id="av-purge",
                tenant_id="t",
                agent_id="ag-purge",
                version=1,
                status="ACTIVE",
                system_prompt="p",
            )
        )
        await s.commit()
    await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="ag-purge", session_id="s", text="12 + 30"),
        deps,
        run_id="r-purge",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )

    report = await DataLifecycleService(sessions).purge_tenant("t")
    assert report["tenant_id"] == "t"
    assert report["deleted"]["agent_runs"] >= 1
    async with sessions() as s:
        assert await s.get(AgentRow, "ag-purge") is None
        assert await s.get(AgentVersionRow, "av-purge") is None
        assert await s.get(AgentRunRow, "r-purge") is None
        assert await s.scalar(select(AgentStepRow).where(AgentStepRow.run_id == "r-purge")) is None
        assert await s.get(TenantRow, "t") is None


async def test_retention_sweep_deletes_old_runs_only(sessions):
    """§26.2 保留期：只删超过保留期的已完结 run，新 run 保留。"""
    from app.agent.runtime.store import RunStore

    store = RunStore(sessions)
    for run_id in ("r-old", "r-new"):
        await store.create_run(
            run_id=run_id,
            tenant_id="t",
            user_id="u",
            agent_id="a",
            agent_version=1,
            session_id="s",
            state="COMPLETED",
            budget_json={},
            model_config={},
            input_json={},
        )
        await store.finish_run(
            run_id=run_id,
            state="COMPLETED",
            output_json={"answer": "x"},
            error_json=None,
            tokens_in=1,
            tokens_out=1,
            cost=0.01,
        )
    old = datetime.now(UTC) - timedelta(days=60)
    async with sessions() as s:
        await s.execute(text("UPDATE agent_runs SET finished_at = :t WHERE run_id = 'r-old'"), {"t": old})
        await s.commit()

    report = await DataLifecycleService(sessions).retention_sweep(retention_days=30)
    assert report["deleted_runs"] == 1
    async with sessions() as s:
        assert await s.get(AgentRunRow, "r-old") is None
        assert await s.get(AgentRunRow, "r-new") is not None


async def test_retention_sweep_per_type(sessions):
    """§26.2 差异化保留期：run(30d)/审计(200d)/payload(10d) 各自 cutoff。"""
    from app.storage.models import AuditLogRow, TracePayloadRow

    old = datetime.now(UTC) - timedelta(days=100)
    async with sessions() as s:
        s.add(
            AgentRunRow(
                run_id="r-type",
                tenant_id="t",
                user_id="u",
                agent_id="a",
                agent_version=1,
                session_id="s",
                state="COMPLETED",
                budget_json="{}",
                model_config="{}",
                input_json="{}",
                finished_at=old,
            )
        )
        s.add(
            AuditLogRow(tenant_id="t", actor_id="u", action="x", resource="y", outcome="OK", created_at=old)
        )
        s.add(
            TracePayloadRow(
                id="p-type",
                trace_id="t",
                run_id="r-type",
                span_name="s",
                kind="llm",
                payload_json="{}",
                created_at=old,
            )
        )
        await s.commit()

    report = await DataLifecycleService(sessions).retention_sweep(
        retention_days=30, audit_days=200, payload_days=10
    )
    assert report["deleted_runs"] == 1
    async with sessions() as s:
        assert await s.get(AgentRunRow, "r-type") is None  # 30d => 删
        assert await s.get(TracePayloadRow, "p-type") is None  # 10d => 删
        audit_id = await s.scalar(select(AuditLogRow.id).where(AuditLogRow.action == "x"))
        assert audit_id is not None  # 200d => 审计保留
