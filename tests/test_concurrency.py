"""Phase 2/3：CAS 乐观锁 + 单步超时 + UNKNOWN + Pause + 租户配额。"""

import asyncio

import pytest

from app.agent.model.gateway import BaseProvider, MockProvider, ModelResult
from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.runtime import execute_run, resume_run
from app.common.contracts import RunInput, ToolCallDraft
from app.common.errors import AgentError


async def _seed_run(deps, run_id: str, state: str = "RUNNING") -> None:
    await deps.store.create_run(
        run_id=run_id,
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state=state,
        budget_json={},
        model_config={},
        input_json={},
    )


async def test_set_state_cas(deps):
    """§3.3 乐观锁：版本不匹配不生效；匹配才更新且版本自增。"""
    await _seed_run(deps, "r-cas")
    assert await deps.store.set_state_cas("r-cas", "FAILED", 99) is False
    assert (await deps.store.get_run("r-cas"))["state"] == "RUNNING"
    assert await deps.store.set_state_cas("r-cas", "FAILED", 1) is True
    full = await deps.store.get_run_full("r-cas")
    assert full["state"] == "FAILED" and full["version"] == 2


async def test_atomic_set_state_bumps_version(deps):
    """§3.3 set_state 原子 UPDATE + 版本自增（无读改写竞态）。"""
    await _seed_run(deps, "r-v")
    await deps.store.set_state("r-v", "COMPLETED")
    assert (await deps.store.get_run_full("r-v"))["version"] == 2


async def test_step_timeout(deps):
    """§9.1 单步超时：慢 LLM 超过 step_timeout_s => run TIMEOUT（AGENT_TIMEOUT）。"""

    class _Slow(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            await asyncio.sleep(1.0)
            return ModelResult(content="done", tokens_in=1, tokens_out=1, cost=0, model=model)

    deps.gateway.provider = _Slow()
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="hi"),
        deps,
        run_id="r-step-to",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5, step_timeout_s=0.05),
    )
    assert result.state == "TIMEOUT"
    assert result.error and result.error["code"] == "AGENT_TIMEOUT"


async def test_tool_timeout_leads_unknown(
    sessions, policy, audit, rate_limiter, store, gateway, lock, cancel
):
    """§3.4 工具超时结果未知 => run UNKNOWN（TOOL_TIMEOUT_UNKNOWN），而非误判 FAILED。"""
    import uuid

    from app.agent.runtime.runtime import RuntimeDeps
    from app.storage.models import PolicyRow
    from app.tool.registry import ToolDefinition, default_registry
    from app.tool.runtime import ToolRuntime

    async def _slow():
        await asyncio.sleep(1.0)

    reg = default_registry()
    reg.register(
        ToolDefinition(
            ref="slow",
            description="x",
            input_schema={"type": "object", "properties": {}},
            fn=_slow,
            timeout_s=0.05,
        )
    )
    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="slow-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="slow",
            )
        )
        await s.commit()
    deps = RuntimeDeps(
        store=store,
        registry=reg,
        gateway=gateway,
        lock=lock,
        cancel=cancel,
        tool_runtime=ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store),
    )

    class _SlowToolProvider(MockProvider):
        async def complete(self, messages, tools, model, token=None):
            if any(m.get("role") == "tool" for m in messages):
                return await super().complete(messages, tools, model, token=token)
            return ModelResult(
                tool_calls=[ToolCallDraft(id="s", name="slow", arguments="{}")],
                tokens_in=1,
                tokens_out=0,
                cost=0,
                model=model,
            )

    deps.gateway.provider = _SlowToolProvider()
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="do it"),
        deps,
        run_id="r-unknown",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "UNKNOWN"
    assert result.error and result.error["code"] == "TOOL_TIMEOUT_UNKNOWN"


async def test_pause_then_resume(deps):
    """§10.3 用户暂停：PAUSED + checkpoint 已落；resume 续跑 COMPLETED。"""
    step2_started = asyncio.Event()

    class _MultiStep(MockProvider):
        def __init__(self):
            super().__init__()
            self.n = 0

        async def complete(self, messages, tools, model, token=None):
            self.n += 1
            if self.n == 1:
                return ModelResult(
                    tool_calls=[ToolCallDraft(id="p1", name="calc.add", arguments='{"a": 1, "b": 2}')],
                    tokens_in=1,
                    tokens_out=0,
                    cost=0,
                    model=model,
                )
            if self.n == 2:
                step2_started.set()  # 步 2 LLM 开始 => 步 1 checkpoint 已落
                await asyncio.sleep(0.5)  # 暂停窗口：pause 落在本步 LLM 内，步 3 顶部检测到
                return ModelResult(
                    tool_calls=[ToolCallDraft(id="p2", name="echo", arguments='{"text": "hi"}')],
                    tokens_in=1,
                    tokens_out=0,
                    cost=0,
                    model=model,
                )
            return await super().complete(messages, tools, model, token=model)

    deps.gateway.provider = _MultiStep()
    task = asyncio.create_task(
        execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="go"),
            deps,
            run_id="r-pause",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
    )
    await asyncio.wait_for(step2_started.wait(), timeout=3)
    await deps.cancel.pause("r-pause")
    result = await asyncio.wait_for(task, timeout=3)
    assert result.state == "PAUSED"
    assert (await deps.store.get_run_full("r-pause"))["checkpoint_json"] is not None

    # resume：清 pause + 从断点续跑
    deps.gateway.provider = MockProvider()
    resumed = await resume_run("r-pause", deps)
    assert resumed.state == "COMPLETED"


async def test_tenant_quota(deps):
    """§16.3 租户并发配额：active >= limit 抛 TENANT_RUN_QUOTA。"""
    from app.agent.api.runs import _enforce_tenant_quota

    await deps.store.create_run(
        run_id="q1",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={},
        model_config={},
        input_json={},
    )
    with pytest.raises(AgentError) as excinfo:
        await _enforce_tenant_quota(deps, "t", limit=1)
    assert excinfo.value.code == "TENANT_RUN_QUOTA"
    await _enforce_tenant_quota(deps, "t", limit=2)  # 未超限


async def test_count_active_runs(deps):
    await deps.store.create_run(
        run_id="a1",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={},
        model_config={},
        input_json={},
    )
    await deps.store.create_run(
        run_id="a2",
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
    assert await deps.store.count_active_runs("t") == 1


async def test_checkpoint_structured(deps):
    """§10.4 检查点结构化：含 current_step/run_state，且 messages 有界。"""
    import json

    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
        deps,
        run_id="r-cp3",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "COMPLETED"
    full = await deps.store.get_run_full("r-cp3")
    cp = json.loads(full["checkpoint_json"])
    assert "current_step" in cp and "run_state" in cp
    assert len(cp["messages"]) < 20  # apply_context_budget 截断为有界


async def test_rebuild_messages_round_trip(deps):
    """§10.4 从 steps 重建消息 == 运行时构建（证明不存 messages 也能重建）。"""
    import json

    from app.agent.runtime.runtime import rebuild_messages_from_run

    class _ToolThenAnswer(MockProvider):
        def __init__(self):
            super().__init__()
            self.n = 0

        async def complete(self, messages, tools, model, token=None):
            self.n += 1
            if self.n == 1:
                return ModelResult(
                    tool_calls=[ToolCallDraft(id="r1", name="calc.add", arguments='{"a": 1, "b": 2}')],
                    tokens_in=1,
                    tokens_out=0,
                    cost=0,
                    model=model,
                )
            return await super().complete(messages, tools, model, token=token)

    deps.gateway.provider = _ToolThenAnswer()
    await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="do it"),
        deps,
        run_id="r-rebuild",
        agent_version=1,
        system_prompt="sys-prompt",
        budget=ExecutionBudget(max_steps=5),
    )
    run = await deps.store.get_run_full("r-rebuild")
    steps = await deps.store.list_steps("r-rebuild")
    rebuilt = rebuild_messages_from_run(run, steps)
    cp = json.loads(run["checkpoint_json"])
    assert rebuilt == cp["messages"]  # 重建 == 运行时消息


async def test_llm_call_token_breakdown(deps):
    """§H.1 CostBreakdown：llm_calls 含 prompt/history/tool/rag 分项。"""
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
        deps,
        run_id="r-tok",
        agent_version=1,
        system_prompt="sys",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "COMPLETED"
    calls = await deps.store.list_llm_calls("r-tok")
    assert calls
    for c in calls:
        assert c["prompt_tokens"] >= 0
        assert c["history_tokens"] >= 0
        assert c["tool_tokens"] >= 0
        assert c["rag_tokens"] >= 0
    # 首次调用必有 system(prompt) token
    assert calls[0]["prompt_tokens"] > 0
