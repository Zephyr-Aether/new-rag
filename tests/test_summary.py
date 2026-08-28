"""Context 生命周期分层（§10.4）：近轮原文 + 旧轮摘要。"""

from app.agent.context.summary import compress_history


async def test_short_history_untouched():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert await compress_history(msgs, keep_recent=5) == msgs


async def test_long_history_folds_old_to_summary():
    msgs = [{"role": "user", "content": f"消息{i}"} for i in range(8)]  # 8 条，keep_recent=3
    out = await compress_history(msgs, keep_recent=3)
    # 1 条摘要 + 近 3 条原文
    assert len(out) == 4
    assert "历史摘要" in out[0]["content"]
    assert out[0]["role"] == "system"
    # 近 3 条原文保留
    assert [m["content"] for m in out[1:]] == [f"消息{i}" for i in range(5, 8)]


async def test_llm_summary_used_when_available():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(6)]

    async def fake_llm(text):
        return "LLM 生成的摘要"

    out = await compress_history(msgs, keep_recent=2, llm=fake_llm)
    assert "LLM 生成的摘要" in out[0]["content"]


async def test_history_compressed_in_runtime(deps):
    """§10.4 上下文分层接入 runtime：长历史自动折叠为摘要 + 近轮原文。"""
    import json

    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.runtime import execute_run
    from app.common.contracts import RunInput

    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"历史问题{i}"})
        history.append({"role": "assistant", "content": f"历史回答{i}"})
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30", history=history)
    result = await execute_run(
        req, deps, run_id="r-hist", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    assert result.state == "COMPLETED"
    cp = json.loads((await deps.store.get_run_full("r-hist"))["checkpoint_json"])
    assert any("历史摘要" in m.get("content", "") for m in cp["messages"])
