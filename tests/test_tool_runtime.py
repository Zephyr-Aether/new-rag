"""ToolRuntime 全管线：权限/限流/风险闸/幂等/审计。"""

import pytest

from app.agent.runtime.store import RunStore
from app.common.contracts import ToolCallRequest
from app.common.errors import ApprovalRequiredError, ToolPermissionDeniedError, ToolRateLimitedError
from app.tool.limiter import RateLimiter
from app.tool.registry import ToolDefinition, ToolRegistry
from app.tool.runtime import ToolRuntime


async def test_allowed_tool_runs(tool_runtime):
    call = ToolCallRequest(
        call_id="c1", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 2}
    )
    res = await tool_runtime.execute(call)
    assert res.ok and res.data == 3
    assert res.decision and res.decision["policy_id"]


async def test_default_deny(tool_runtime):
    call = ToolCallRequest(
        call_id="c2", tenant_id="nobody", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 2}
    )
    with pytest.raises(ToolPermissionDeniedError):
        await tool_runtime.execute(call)


async def test_rate_limited(tool_runtime):
    tool_runtime.limiter = RateLimiter("", default_limit=1, default_window_s=60)
    await tool_runtime.execute(
        ToolCallRequest(call_id="ok", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 2})
    )
    with pytest.raises(ToolRateLimitedError):
        await tool_runtime.execute(
            ToolCallRequest(
                call_id="rl", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 2}
            )
        )


async def test_risk_gate_requires_approval(sessions, policy, audit):
    import uuid

    from app.storage.models import PolicyRow

    # 先给 danger 配 allow 策略（否则权限先拒绝，到不了风险闸）
    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="test-danger-allow",
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
    rt = ToolRuntime(
        registry=reg,
        policy=policy,
        audit=audit,
        limiter=RateLimiter("", default_limit=100),
        idem=RunStore(sessions),
    )
    call = ToolCallRequest(call_id="d1", tenant_id="t", user_id="u", tool_ref="danger", args={})
    with pytest.raises(ApprovalRequiredError):
        await rt.execute(call)


async def test_idempotent_replay_via_runtime(tool_runtime):
    call = ToolCallRequest(
        call_id="idem-1", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": 3, "b": 4}
    )
    r1 = await tool_runtime.execute(call)
    r2 = await tool_runtime.execute(call)
    assert r1.ok and r2.ok and r1.data == r2.data == 7


async def test_sandbox_output_cap_blocks(sessions, policy, audit, rate_limiter, store, registry):
    """§23.4 Sandbox：工具输出超过上限被拒（ToolExecutionFailedError）。"""
    from app.common.errors import ToolExecutionFailedError
    from app.sandbox import SandboxConfig

    rt = ToolRuntime(
        registry=registry,
        policy=policy,
        audit=audit,
        limiter=rate_limiter,
        idem=store,
        sandbox=SandboxConfig(max_output_bytes=10),
    )
    call = ToolCallRequest(
        call_id="sb1", tenant_id="t", user_id="u", tool_ref="echo", args={"text": "x" * 100}
    )
    with pytest.raises(ToolExecutionFailedError):
        await rt.execute(call)


async def test_sandbox_output_within_limit_ok(sessions, policy, audit, rate_limiter, store, registry):
    from app.sandbox import SandboxConfig

    rt = ToolRuntime(
        registry=registry,
        policy=policy,
        audit=audit,
        limiter=rate_limiter,
        idem=store,
        sandbox=SandboxConfig(max_output_bytes=1000),
    )
    call = ToolCallRequest(call_id="sb2", tenant_id="t", user_id="u", tool_ref="echo", args={"text": "hi"})
    res = await rt.execute(call)
    assert res.ok and res.data == "hi"


async def test_http_port_allowlist():
    """§23.4 Sandbox：非白名单出站端口被拒（在发起请求前拦截）。"""
    from app.common.errors import ToolInvalidArgumentError
    from app.tool.registry import default_registry

    reg = default_registry(http_allowed_ports={80, 443})
    tool = reg.resolve("http.get")
    with pytest.raises(ToolInvalidArgumentError):
        await tool.fn(url="http://example.com:8080/")  # 非白名单端口，请求发起前拦截
