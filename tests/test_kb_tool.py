"""kb.search 工具（§15 / Agentic RAG）：走 ToolRuntime 全管线，含主体注入与租户隔离。"""

import pytest

from app.common.contracts import ToolCallRequest
from app.common.errors import ToolPermissionDeniedError


async def test_kb_search_tool_returns_chunks(tool_runtime, knowledge_service):
    await knowledge_service.ingest_markdown(
        tenant_id="t",
        document_id="doc-ret",
        title="退货政策",
        text="## 退款到账时间\n退款 3-5 个工作日到账。",
    )
    call = ToolCallRequest(
        call_id="kb1", tenant_id="t", user_id="u", tool_ref="kb.search", args={"query": "退款到账", "k": 3}
    )
    res = await tool_runtime.execute(call)
    assert res.ok
    assert res.data and res.data[0]["document_id"] == "doc-ret"
    assert res.data[0]["section"] == "退款到账时间"


async def test_kb_search_scope_is_subject_not_args(
    sessions, policy, audit, rate_limiter, store, knowledge_service
):
    """租户来自主体身份（subject），绝不来自工具参数——防 LLM 伪造 tenant 越权。"""
    import uuid

    from app.knowledge.retrieval import register_knowledge_tool
    from app.storage.models import PolicyRow
    from app.tool.registry import default_registry
    from app.tool.runtime import ToolRuntime

    # 给 tB 授权 kb.search（否则默认拒绝，测不到检索隔离）
    async with sessions() as s:
        s.add(
            PolicyRow(
                id=f"pol-{uuid.uuid4().hex[:8]}",
                tenant_id="tB",
                name="test-kb-allow",
                effect="ALLOW",
                action="tool:execute",
                resource="kb.search",
            )
        )
        await s.commit()
    reg = default_registry()
    register_knowledge_tool(reg, knowledge_service)
    rt = ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store)

    await knowledge_service.ingest_markdown(
        tenant_id="tA",
        document_id="secret-doc",
        title="机密",
        text="## 机密信息\n这是 A 租户的机密数据。",
    )
    call = ToolCallRequest(
        call_id="kb2",
        tenant_id="tB",
        user_id="u",
        tool_ref="kb.search",
        args={"query": "机密", "k": 5, "tenant_id": "tA"},  # 伪造 tenant 无效
    )
    res = await rt.execute(call)
    assert res.ok
    assert res.data == []  # tB 允许检索，但搜不到 tA 的内容


async def test_kb_search_default_deny(tool_runtime):
    # "nobody" 租户无 kb.search 策略 => 工具层权限默认拒绝
    call = ToolCallRequest(
        call_id="kb3", tenant_id="nobody", user_id="u", tool_ref="kb.search", args={"query": "x"}
    )
    with pytest.raises(ToolPermissionDeniedError):
        await tool_runtime.execute(call)


async def test_retrieval_top_k_override(deps, knowledge_service):
    """§60 Replay 换检索参数：Run 级 retrieval_top_k 覆盖 kb.search 的 k。"""
    from app.agent.model.gateway import MockProvider, ModelResult
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.runtime import execute_run
    from app.common.contracts import RunInput, ToolCallDraft

    await knowledge_service.ingest_markdown(
        tenant_id="t",
        document_id="d1",
        title="政策",
        text="## 退款到账时间\n退款 3 个工作日到账。\n## 退货条件\n30 天内可退货。",
    )

    class _KbProvider(MockProvider):
        async def complete(self, messages, tools, model, token=None):
            if any(m.get("role") == "tool" for m in messages):
                return await super().complete(messages, tools, model, token=token)
            return ModelResult(
                tool_calls=[ToolCallDraft(id="k", name="kb.search", arguments='{"query": "退款", "k": 5}')],
                tokens_in=1,
                tokens_out=0,
                cost=0,
                model=model,
            )

    deps.gateway.provider = _KbProvider()
    req = RunInput(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        session_id="s",
        text="知识库: 退款",
        retrieval_top_k=1,
    )
    result = await execute_run(
        req, deps, run_id="r-topk", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    assert result.state == "COMPLETED"
    steps = await deps.store.list_steps("r-topk")
    obs = [o for s in steps for o in s["tool_calls"] if o["tool_ref"] == "kb.search"]
    assert obs and len(obs[0]["data"]) <= 1  # top_k=1 生效（LLM 请求 k=5 被覆盖）


async def test_knowledge_version_threading(sessions, knowledge_service):
    """§22.1 版本冻结：Run 级 knowledge_version 透传到检索（缓存键分版本，运行中不漂移）。"""
    from app.common.contracts import RETRIEVAL_KNOWLEDGE_VERSION, Subject
    from app.knowledge.embedding import HashEmbedding
    from app.knowledge.retrieval import register_knowledge_tool
    from app.knowledge.store import KnowledgeStore
    from app.tool.registry import default_registry

    captured = {}

    class _Capture(knowledge_service.__class__):
        async def search(self, req):
            captured["req"] = req
            return await super().search(req)

    svc = _Capture(KnowledgeStore(sessions), HashEmbedding())
    reg = default_registry()
    register_knowledge_tool(reg, svc)
    tool = reg.resolve("kb.search")

    token = RETRIEVAL_KNOWLEDGE_VERSION.set("9")
    try:
        await tool.fn(subject=Subject(tenant_id="t", user_id="u"), query="x")
    finally:
        RETRIEVAL_KNOWLEDGE_VERSION.reset(token)
    assert captured["req"].knowledge_version == "9"
