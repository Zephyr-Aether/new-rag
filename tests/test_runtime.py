"""Runtime 集成测试：状态机编排 / 预算超时 / 死循环检测 / 持久化。"""

import asyncio

from app.agent.model.gateway import BaseProvider
from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.cancel import CancelService
from app.agent.runtime.runtime import RuntimeDeps, execute_run
from app.common.contracts import ModelResult, RunInput, ToolCallDraft


async def test_completes_with_tool_call(deps):
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
    result = await execute_run(
        req,
        deps,
        run_id="r-complete",
        agent_version=1,
        system_prompt="test agent",
        budget=ExecutionBudget(max_steps=10),
    )
    assert result.state == "COMPLETED"
    assert result.steps >= 2  # 工具步骤 + 收敛步骤
    assert "42" in (result.answer or "")
    assert result.cost > 0

    run = await deps.store.get_run("r-complete")
    assert run["state"] == "COMPLETED"
    steps = await deps.store.list_steps("r-complete")
    assert len(steps) >= 2
    assert steps[0]["tool_calls"]  # 第一步应含工具观察


async def test_budget_timeout(deps):
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
    result = await execute_run(
        req, deps, run_id="r-budget", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=1)
    )
    assert result.state == "TIMEOUT"
    assert result.error and result.error["code"] == "BUDGET_EXCEEDED"


class _LoopProvider(BaseProvider):
    async def complete(self, messages, tools, model, token=None):
        return ModelResult(tool_calls=[ToolCallDraft(id="x", name="echo", arguments='{"text":"hi"}')])


async def test_loop_detection(deps):
    deps.gateway.provider = _LoopProvider()
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="go")
    result = await execute_run(
        req, deps, run_id="r-loop", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=10)
    )
    assert result.state == "FAILED"
    assert result.error and result.error["code"] == "AGENT_LOOP_DETECTED"


class _SlowProvider(BaseProvider):
    """2s 慢请求：验证取消能打断在途 LLM 调用（§8.2），而非等到调用结束。"""

    async def complete(self, messages, tools, model, token=None):
        from app.agent.runtime.cancel import cancelable_sleep

        await cancelable_sleep(token, 2.0)
        return ModelResult(content="slow answer", tokens_in=1, tokens_out=1, cost=0, model=model)


async def test_cancellation_interrupts_inflight_llm(deps):
    import asyncio
    import time

    deps.gateway.provider = _SlowProvider()
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="hello")
    task = asyncio.create_task(
        execute_run(
            req,
            deps,
            run_id="r-cancel-inflight",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
    )
    await asyncio.sleep(0.15)  # 让 run 进入在途 LLM 调用
    await deps.cancel.cancel("r-cancel-inflight")
    started = time.monotonic()
    result = await asyncio.wait_for(task, timeout=2.0)
    elapsed = time.monotonic() - started
    assert result.state == "CANCELLED"
    assert result.answer is None
    assert elapsed < 1.0  # 未等到 2s 慢请求结束 => 在途被中断


async def _slow_tool(seconds: int = 2) -> str:
    await asyncio.sleep(seconds)
    return "slow-done"


async def test_cancellation_interrupts_inflight_tool(
    sessions, policy, audit, rate_limiter, store, gateway, lock
):
    """§8.2 取消能打断在途的异步工具执行（而非等到工具结束）。"""
    import asyncio
    import time
    import uuid

    from app.storage.models import PolicyRow
    from app.tool.registry import ToolDefinition, ToolRegistry
    from app.tool.runtime import ToolRuntime

    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="slow-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="slow.op",
            )
        )
        await s.commit()

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            ref="slow.op",
            description="慢工具",
            input_schema={"type": "object", "properties": {"seconds": {"type": "integer"}}},
            fn=_slow_tool,
            permission="slow:op",
        )
    )
    tool_runtime = ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store)

    class _ToolProvider(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            return ModelResult(
                tool_calls=[ToolCallDraft(id="s1", name="slow.op", arguments='{"seconds": 2}')],
                tokens_in=1,
                tokens_out=0,
                cost=0,
                model=model,
            )

    gateway.provider = _ToolProvider()
    deps = RuntimeDeps(
        store=store,
        registry=reg,
        gateway=gateway,
        lock=lock,
        cancel=CancelService(""),
        tool_runtime=tool_runtime,
    )
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="do it")
    task = asyncio.create_task(
        execute_run(
            req,
            deps,
            run_id="r-cancel-tool",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
    )
    await asyncio.sleep(0.15)  # 让 run 进入在途工具执行
    await deps.cancel.cancel("r-cancel-tool")
    started = time.monotonic()
    result = await asyncio.wait_for(task, timeout=2.0)
    elapsed = time.monotonic() - started
    assert result.state == "CANCELLED"
    assert result.answer is None
    assert elapsed < 1.0  # 未等到 2s 工具结束 => 在途被中断


async def test_cancellation(deps):
    from app.agent.runtime.cancel import CancelService

    deps.cancel = CancelService("")
    await deps.cancel.cancel("r-cancel")
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="hello")
    result = await execute_run(
        req, deps, run_id="r-cancel", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=10)
    )
    assert result.state == "CANCELLED"
    assert result.error and result.error["code"] == "RUN_CANCELLED"
