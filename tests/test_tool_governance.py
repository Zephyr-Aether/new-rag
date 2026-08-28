"""工具治理（§6.3）：熔断接入 / 工具级超时 / 执行重试。"""

import asyncio
import uuid

import pytest

from app.common.contracts import Subject, ToolCallRequest
from app.common.errors import ToolError, ToolExecutionFailedError, ToolTimeoutError
from app.storage.models import PolicyRow
from app.tool.registry import ToolDefinition, default_registry, execute_tool
from app.tool.runtime import ToolRuntime


async def _allow(store_sessions, resource: str) -> None:
    async with store_sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="allow",
                effect="ALLOW",
                action="tool:execute",
                resource=resource,
            )
        )
        await s.commit()


async def test_execute_tool_timeout(store):
    """§6.3 工具级超时：慢工具超时抛 ToolTimeoutError。"""

    async def _slow():
        await asyncio.sleep(1.0)

    tool = ToolDefinition(
        ref="slow",
        description="x",
        input_schema={"type": "object", "properties": {}},
        fn=_slow,
        timeout_s=0.05,
    )
    with pytest.raises(ToolTimeoutError):
        await execute_tool(tool, {}, call_id="t1", subject=Subject(tenant_id="t", user_id="u"), idem=store)


async def test_execute_tool_retry(store):
    """§6.3 工具重试：前两次失败，重试后成功（带抖动退避）。"""
    state = {"n": 0}

    def _flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    tool = ToolDefinition(
        ref="flaky", description="x", input_schema={"type": "object", "properties": {}}, fn=_flaky, retry=2
    )
    r = await execute_tool(tool, {}, call_id="t2", subject=Subject(tenant_id="t", user_id="u"), idem=store)
    assert r.ok and r.data == "ok" and state["n"] == 3


async def test_execute_tool_retry_exhausted(store):
    """重试耗尽仍失败 => ToolExecutionFailedError。"""
    state = {"n": 0}

    def _always_fail():
        state["n"] += 1
        raise RuntimeError("boom")

    tool = ToolDefinition(
        ref="bad",
        description="x",
        input_schema={"type": "object", "properties": {}},
        fn=_always_fail,
        retry=1,
    )
    with pytest.raises(ToolExecutionFailedError):
        await execute_tool(tool, {}, call_id="t3", subject=Subject(tenant_id="t", user_id="u"), idem=store)
    assert state["n"] == 2  # 1 次执行 + 1 次重试


async def test_tool_breaker_opens_after_failures(policy, audit, rate_limiter, store, sessions):
    """§6.3 工具级熔断：连续执行失败达阈值 => TOOL_BREAKER_OPEN 快速失败。"""
    await _allow(sessions, "boom")
    reg = default_registry()

    def _boom():
        raise RuntimeError("downstream down")

    reg.register(
        ToolDefinition(
            ref="boom", description="x", input_schema={"type": "object", "properties": {}}, fn=_boom
        )
    )
    rt = ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store)
    for i in range(5):  # failure_threshold=5
        with pytest.raises(ToolExecutionFailedError):
            await rt.execute(ToolCallRequest(call_id=f"b{i}", tenant_id="t", user_id="u", tool_ref="boom"))
    with pytest.raises(ToolError) as excinfo:
        await rt.execute(ToolCallRequest(call_id="b6", tenant_id="t", user_id="u", tool_ref="boom"))
    assert excinfo.value.code == "TOOL_BREAKER_OPEN"


async def test_tool_breaker_not_tripped_by_bad_args(policy, audit, rate_limiter, store, sessions):
    """§6.3 参数类错误不算工具故障，不熔断。"""
    await _allow(sessions, "calc.add")
    rt = ToolRuntime(
        registry=default_registry(), policy=policy, audit=audit, limiter=rate_limiter, idem=store
    )
    for i in range(8):
        with pytest.raises(ToolError):
            await rt.execute(
                ToolCallRequest(
                    call_id=f"a{i}", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": "x"}
                )
            )
    # 参数校验错误不熔断：仍能正常执行
    r = await rt.execute(
        ToolCallRequest(call_id="aok", tenant_id="t", user_id="u", tool_ref="calc.add", args={"a": 1, "b": 2})
    )
    assert r.ok and r.data == 3
