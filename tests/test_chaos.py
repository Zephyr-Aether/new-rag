"""混沌工程（§80）：注入故障验证 降级/重试/取消/优雅失败（含 §30.2 DB 故障注入）。"""

import asyncio
import time

import pytest

from app.agent.model.gateway import MockProvider
from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.runtime import execute_run
from app.chaos import ChaosProvider, run_chaos
from app.common.contracts import ModelResult, RunInput, ToolCallDraft


async def test_model_failure_fails_gracefully(deps):
    deps.gateway.provider = ChaosProvider(MockProvider(), fail_count=1000)
    start = time.monotonic()
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
        deps,
        run_id="ch-model-fail",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "FAILED"
    assert result.error and result.error["code"] == "MODEL_ERROR"
    assert time.monotonic() - start < 3  # 重试耗尽后优雅失败，不悬挂


async def test_429_recovers_after_retry(deps):
    deps.gateway.provider = ChaosProvider(MockProvider(), fail_count=1, fail_429=True)
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
        deps,
        run_id="ch-429",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "COMPLETED"
    assert "42" in (result.answer or "")  # 429 被重试吸收


async def test_slow_model_cancelled_inflight(deps):
    deps.gateway.provider = ChaosProvider(MockProvider(), slow_s=2.0)
    task = asyncio.create_task(
        execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
            deps,
            run_id="ch-slow",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
    )
    await asyncio.sleep(0.1)
    await deps.cancel.cancel("ch-slow")
    start = time.monotonic()
    result = await asyncio.wait_for(task, timeout=2.0)
    assert result.state == "CANCELLED"
    assert time.monotonic() - start < 1.5  # 在途被中断（未等 2s 慢请求）


async def test_tool_failure_graceful_observation(deps, policy, audit, rate_limiter, store):
    import uuid

    from app.storage.models import PolicyRow
    from app.tool.registry import ToolDefinition, default_registry
    from app.tool.runtime import ToolRuntime

    async with store.sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="t",
                name="broken-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="broken",
            )
        )
        await s.commit()

    def _broken():
        raise RuntimeError("boom")

    reg = default_registry()
    reg.register(
        ToolDefinition(
            ref="broken",
            description="x",
            input_schema={"type": "object", "properties": {}},
            fn=_broken,
            permission="broken",
        )
    )
    deps.registry = reg
    deps.tool_runtime = ToolRuntime(
        registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store
    )

    class _BrokenToolProvider(MockProvider):
        async def complete(self, messages, tools, model, token=None):
            if any(m.get("role") == "tool" for m in messages):
                return await super().complete(messages, tools, model, token=token)  # 收束
            return ModelResult(
                tool_calls=[ToolCallDraft(id="b", name="broken", arguments="{}")],
                tokens_in=1,
                tokens_out=0,
                cost=0,
                model=model,
            )

    deps.gateway.provider = _BrokenToolProvider()
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="do it"),
        deps,
        run_id="ch-tool",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "COMPLETED"  # 工具失败作为 observation 回喂，run 优雅收敛
    steps = await store.list_steps("ch-tool")
    obs = [o for s in steps for o in s["tool_calls"] if o["tool_ref"] == "broken"]
    assert obs and obs[0]["ok"] is False


async def test_run_chaos_reports():
    async def bad_scenario():
        raise AssertionError("boom")

    assert (await run_chaos("scenario-bad", bad_scenario))["status"] == "failed"

    async def good_scenario():
        return True

    assert (await run_chaos("scenario-good", good_scenario))["status"] == "passed"


async def _chaos_deps(sessions, registry, gateway, lock, cancel, tool_runtime, chaos_store):
    from app.agent.runtime.runtime import RuntimeDeps
    from app.agent.runtime.store import RunStore

    return RuntimeDeps(
        store=RunStore(chaos_store),
        registry=registry,
        gateway=gateway,
        lock=lock,
        cancel=cancel,
        tool_runtime=tool_runtime,
    )


async def test_chaos_sessions_slow_db_run_completes(sessions, registry, gateway, lock, cancel, tool_runtime):
    """§30.2 DB 慢注入：run 仍优雅完成，不悬挂。"""
    from app.agent.runtime.runtime import execute_run
    from app.chaos import ChaosSessions
    from app.common.contracts import RunInput

    chaos = ChaosSessions(sessions, delay_s=0.05)
    deps = await _chaos_deps(sessions, registry, gateway, lock, cancel, tool_runtime, chaos)
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
        deps,
        run_id="ch-db-slow",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert result.state == "COMPLETED"
    assert "42" in (result.answer or "")


async def test_chaos_sessions_db_failure_fails_fast(sessions, registry, gateway, lock, cancel, tool_runtime):
    """§30.2 DB 故障注入：首次会话失败 => run 快速抛错而非悬挂。"""
    from app.agent.runtime.runtime import execute_run
    from app.chaos import ChaosSessions
    from app.common.contracts import RunInput

    chaos = ChaosSessions(sessions, fail_count=1)
    deps = await _chaos_deps(sessions, registry, gateway, lock, cancel, tool_runtime, chaos)
    start = time.monotonic()
    with pytest.raises(RuntimeError):
        await execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
            deps,
            run_id="ch-db-fail",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
    assert time.monotonic() - start < 2  # 快速失败，无悬挂


async def test_chaos_knowledge_search_slow(sessions, knowledge_service):
    """§30.2 检索慢注入（Vector DB 慢）：ChaosKnowledgeService 延迟生效。"""
    from app.chaos import ChaosKnowledgeService
    from app.knowledge.retrieval import RetrievalRequest

    await knowledge_service.ingest_markdown(tenant_id="t", document_id="d1", title="x", text="## A\nabc")
    chaos = ChaosKnowledgeService(knowledge_service, delay_s=0.05)
    start = time.monotonic()
    res = await chaos.search(RetrievalRequest(query="abc", tenant_id="t"))
    assert time.monotonic() - start >= 0.05  # 延迟注入生效
    assert res.hits  # 检索仍正常返回
