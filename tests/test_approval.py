"""审批流（§19）：创建审批 / approve / reject / 风险闸接入 / 批准后自动续跑。"""

import uuid

import pytest

from app.agent.runtime.store import RunStore
from app.approval.service import ApprovalService
from app.common.contracts import ToolCallRequest
from app.common.errors import ApprovalRequiredError
from app.storage.models import PolicyRow
from app.tool.limiter import RateLimiter
from app.tool.registry import ToolDefinition, ToolRegistry
from app.tool.runtime import ToolRuntime


async def test_approval_create_and_approve(sessions):
    svc = ApprovalService(sessions)
    aid = await svc.create(
        tenant_id="t", requester_id="u", tool_ref="pay", call_id="c1", risk_level="CRITICAL"
    )
    assert (await svc.get(aid))["status"] == "PENDING"
    assert await svc.decide(aid, approver_id="manager", approve=True) == "APPROVED"
    assert (await svc.get(aid))["approver_id"] == "manager"


async def test_approval_reject_and_idempotent(sessions):
    svc = ApprovalService(sessions)
    aid = await svc.create(
        tenant_id="t", requester_id="u", tool_ref="pay", call_id="c1", risk_level="CRITICAL"
    )
    assert await svc.decide(aid, approver_id="m", approve=False) == "REJECTED"
    assert await svc.decide(aid, approver_id="m2", approve=True) == "REJECTED"  # 已终态不生效


async def test_risk_gate_creates_approval(sessions, policy, audit):
    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="danger-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="danger",
            )
        )
        await s.commit()
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            ref="danger",
            description="高风险工具（测试）",
            input_schema={"type": "object", "properties": {}},
            fn=lambda: "boom",
            risk_level="CRITICAL",
            permission="danger",
        )
    )
    approvals = ApprovalService(sessions)
    rt = ToolRuntime(
        registry=reg,
        policy=policy,
        audit=audit,
        limiter=RateLimiter(""),
        idem=RunStore(sessions),
        approvals=approvals,
    )
    call = ToolCallRequest(call_id="d1", tenant_id="t", user_id="u", tool_ref="danger", args={})
    with pytest.raises(ApprovalRequiredError) as excinfo:
        await rt.execute(call)
    approval_id = excinfo.value.detail.get("approval_id")
    assert approval_id
    assert (await approvals.get(approval_id))["status"] == "PENDING"


async def test_risk_gate_notifies(sessions, policy, audit):
    """§19 审批人通知：创建审批时通知 notifier。"""
    notified: list[dict] = []

    class _SpyNotifier:
        async def notify(self, **kw):
            notified.append(kw)

    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="danger-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="danger",
            )
        )
        await s.commit()
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            ref="danger",
            description="x",
            input_schema={"type": "object", "properties": {}},
            fn=lambda: "boom",
            risk_level="CRITICAL",
            permission="danger",
        )
    )
    rt = ToolRuntime(
        registry=reg,
        policy=policy,
        audit=audit,
        limiter=RateLimiter(""),
        idem=RunStore(sessions),
        approvals=ApprovalService(sessions),
        notifier=_SpyNotifier(),
    )
    call = ToolCallRequest(call_id="d2", tenant_id="t", user_id="u", tool_ref="danger", args={})
    with pytest.raises(ApprovalRequiredError):
        await rt.execute(call)
    assert notified
    assert notified[0]["tool_ref"] == "danger"
    assert notified[0]["approval_id"]


async def test_approval_blocked_run_resumes_after_approval(sessions, policy, audit):
    """§19 批准后自动续跑：run 进 WAITING_APPROVAL -> 批准 -> resume 重放，工具按幂等键只执行一次。"""
    from app.agent.model.gateway import BaseProvider, ModelGateway, ModelResult
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.cancel import CancelService
    from app.agent.runtime.runtime import RuntimeDeps, execute_run, resume_run
    from app.common.contracts import RunInput, ToolCallDraft
    from app.settings import Settings
    from app.storage.lock import RunLockService

    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="danger-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="danger",
            )
        )
        await s.commit()
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            ref="danger",
            description="x",
            input_schema={"type": "object", "properties": {}},
            fn=lambda: "approved-done",
            risk_level="CRITICAL",
            permission="danger",
        )
    )
    approvals = ApprovalService(sessions)
    store = RunStore(sessions)
    rt = ToolRuntime(
        registry=reg,
        policy=policy,
        audit=audit,
        limiter=RateLimiter(""),
        idem=store,
        approvals=approvals,
    )

    class _DangerProvider(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            if any(m.get("role") == "tool" for m in messages):
                return ModelResult(content="final", tokens_in=1, tokens_out=1, cost=0, model=model)
            return ModelResult(
                tool_calls=[ToolCallDraft(id="d", name="danger", arguments="{}")],
                tokens_in=1,
                tokens_out=0,
                cost=0,
                model=model,
            )

    gw = ModelGateway(Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    gw.provider = _DangerProvider()
    deps = RuntimeDeps(
        store=store,
        registry=reg,
        gateway=gw,
        lock=RunLockService(""),
        cancel=CancelService(""),
        tool_runtime=rt,
    )

    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="do danger")
    result = await execute_run(
        req, deps, run_id="r-appr", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    assert result.state == "WAITING_APPROVAL"
    assert result.error and result.error["code"] == "APPROVAL_REQUIRED"
    approval_id = result.error["detail"]["approval_id"]
    assert approval_id

    # 批准（幂等：同一 call_id 再次经过风险闸直接放行）
    assert await approvals.decide(approval_id, approver_id="manager", approve=True) == "APPROVED"
    resumed = await resume_run("r-appr", deps)
    assert resumed.state == "COMPLETED"
    assert resumed.answer == "final"
    # 工具在续跑中被执行且结果入 steps
    steps = await store.list_steps("r-appr")
    obs = [o for s in steps for o in s["tool_calls"] if o["tool_ref"] == "danger"]
    assert obs and obs[0]["data"] == "approved-done"
