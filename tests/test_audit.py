"""审计：权限决策 + 工具执行全量落 audit_logs（§6.7）。"""

from sqlalchemy import select

from app.common.contracts import ToolCallRequest
from app.storage.models import AuditLogRow


async def test_tool_execution_writes_audit(audit, tool_runtime):
    call = ToolCallRequest(
        call_id="aud-1", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 1}
    )
    res = await tool_runtime.execute(call)
    assert res.ok and res.data == 2

    async with audit.sessions() as s:
        rows = (await s.scalars(select(AuditLogRow).where(AuditLogRow.action == "tool:execute"))).all()
    outcomes = {(r.outcome, r.resource) for r in rows}
    assert ("ALLOWED", "calc.add") in outcomes  # 权限决策
    assert ("SUCCEEDED", "calc.add") in outcomes  # 执行结果


async def test_permission_denied_writes_audit(audit, tool_runtime):
    from app.common.errors import ToolPermissionDeniedError

    call = ToolCallRequest(
        call_id="aud-2", tenant_id="nobody", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 1}
    )
    try:
        await tool_runtime.execute(call)
    except ToolPermissionDeniedError:
        pass
    async with audit.sessions() as s:
        rows = (await s.scalars(select(AuditLogRow).where(AuditLogRow.action == "tool:execute"))).all()
    assert any(r.outcome == "DENIED" and r.actor_id == "u" for r in rows)
