"""Checkpoint / Resume（§8.4）：崩溃后从检查点续跑，已完成工具不重复执行。"""

import json

import pytest

from app.agent.model.gateway import BaseProvider, MockProvider
from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.runtime import execute_run, resume_run
from app.common.contracts import ModelResult, RunInput, ToolCallDraft
from app.common.errors import AgentError, ModelError


class _CrashAfterFirstToolProvider(BaseProvider):
    """第 1 次调用返回 calc.add 工具调用；第 2 次调用抛 ModelError（模拟崩溃）。"""

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools, model, token=None):
        self.calls += 1
        if self.calls == 1:
            return ModelResult(
                tool_calls=[ToolCallDraft(id="call1", name="calc.add", arguments='{"a": 12, "b": 30}')],
                tokens_in=1,
                tokens_out=0,
                cost=0,
                model=model,
            )
        raise ModelError("simulated crash after step 1")


async def test_checkpoint_persisted(deps):
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
    await execute_run(
        req, deps, run_id="r-cp", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    run = await deps.store.get_run_full("r-cp")
    assert run["checkpoint_json"] is not None
    cp = json.loads(run["checkpoint_json"])
    assert cp["steps"] >= 1
    assert any(m["role"] == "tool" for m in cp["messages"])


async def test_resume_after_crash(deps):
    deps.gateway.provider = _CrashAfterFirstToolProvider()
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
    first = await execute_run(
        req, deps, run_id="r-crash", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    assert first.state == "FAILED"
    assert first.error and first.error["code"] == "MODEL_ERROR"

    # 换健康 provider 后续跑
    deps.gateway.provider = MockProvider()
    resumed = await resume_run("r-crash", deps)
    assert resumed.state == "COMPLETED"
    assert "42" in (resumed.answer or "")

    # 工具不重复执行：全程只有 step1 的 calc.add，step2 收束无工具
    steps = await deps.store.list_steps("r-crash")
    tool_refs = [o["tool_ref"] for s in steps for o in s["tool_calls"]]
    assert tool_refs == ["calc.add"]
    assert len(steps) >= 2


async def test_resume_completed_is_noop(deps):
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="hello")
    await execute_run(
        req, deps, run_id="r-done", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    resumed = await resume_run("r-done", deps)
    assert resumed.state == "COMPLETED"


async def test_resume_no_checkpoint(deps):
    await deps.store.create_run(
        run_id="r-nocp",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={},
        model_config={"model": "m"},
        input_json={},
    )
    resumed = await resume_run("r-nocp", deps)
    assert resumed.state == "FAILED"
    assert resumed.error and resumed.error["code"] == "NO_CHECKPOINT"


async def test_resume_not_found(deps):
    with pytest.raises(AgentError):
        await resume_run("r-missing", deps)


async def test_resume_restores_retrieval_top_k(deps, knowledge_service):
    """§60 续跑恢复 run 级 retrieval_top_k：否则续跑期间新检索会丢失覆盖。"""
    from app.agent.model.gateway import MockProvider

    await knowledge_service.ingest_markdown(
        tenant_id="t",
        document_id="d1",
        title="政策",
        text="## 政策A\n退款规则：3 天到账。\n## 政策B\n退款流程：在线申请。",  # 两条都匹配"退款"
    )

    class _KbThenCrash(MockProvider):
        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools, model, token=None):
            self.calls += 1
            if self.calls == 1:
                return ModelResult(
                    tool_calls=[
                        ToolCallDraft(id="kb1", name="kb.search", arguments='{"query": "退款", "k": 5}')
                    ],
                    tokens_in=1,
                    tokens_out=0,
                    cost=0,
                    model=model,
                )
            raise ModelError("simulated crash after kb.search")

    deps.gateway.provider = _KbThenCrash()  # 首次 kb.search 后崩溃
    req = RunInput(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        session_id="s",
        text="知识库: 退款",
        retrieval_top_k=1,
    )
    first = await execute_run(
        req,
        deps,
        run_id="r-topk-resume",
        agent_version=1,
        system_prompt="",
        budget=ExecutionBudget(max_steps=5),
    )
    assert first.state == "FAILED"

    class _ResumeKb(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def complete(self, messages, tools, model, token=None):
            self.calls += 1
            if self.calls == 1:  # 续跑第一次 LLM 调用重新触发 kb.search（id 不同 => 非幂等命中）
                return ModelResult(
                    tool_calls=[
                        ToolCallDraft(id="kb2", name="kb.search", arguments='{"query": "退款", "k": 5}')
                    ],
                    tokens_in=1,
                    tokens_out=0,
                    cost=0,
                    model=model,
                )
            return await super().complete(messages, tools, model, token=token)

    deps.gateway.provider = _ResumeKb()
    resumed = await resume_run("r-topk-resume", deps)
    assert resumed.state == "COMPLETED"
    steps = await deps.store.list_steps("r-topk-resume")
    kb_obs = [o for s in steps for o in s["tool_calls"] if o["tool_ref"] == "kb.search"]
    # 续跑期间的新检索同样受 retrieval_top_k=1 约束（≤1 条；若不恢复则达 k=5 -> 2 条）
    assert kb_obs and all(len(o.get("data", [])) <= 1 for o in kb_obs)
