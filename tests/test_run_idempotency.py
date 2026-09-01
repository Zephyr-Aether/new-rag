"""§32.5 run 幂等：client_run_id 去重——同 key 终态回放、非终态拒绝、无 key 不参与。"""

import asyncio
import json

from starlette.testclient import TestClient

from app.main import create_app


def _sse_done(text: str) -> dict | None:
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        data = json.loads(line[6:])
        if data.get("type") == "done":
            return data
    return None


def _complete(client, key=None):
    body = {"input": "12 + 30"}
    if key:
        body["client_run_id"] = key
    r = client.post("/agents/runs", json=body)
    assert r.status_code == 200
    return r.json()


def test_same_client_run_id_returns_same_run():
    with TestClient(create_app()) as c:
        first = _complete(c, "k-same")
        replay = _complete(c, "k-same")
        assert replay["run_id"] == first["run_id"]
        assert replay["state"] == "COMPLETED"
        assert "42" in (replay["answer"] or "")


def test_different_keys_create_new_runs():
    with TestClient(create_app()) as c:
        a = _complete(c, "k-a")
        b = _complete(c, "k-b")
        assert a["run_id"] != b["run_id"]


def test_without_key_still_runs_fresh():
    """无 client_run_id 保持原行为：每次都是新 run，不参与幂等。"""
    with TestClient(create_app()) as c:
        a = _complete(c)
        b = _complete(c)
        assert a["run_id"] != b["run_id"]


def test_stream_replay_same_run_id():
    """流式同 key 第二次是回放：done 的 run_id 一致，不重复执行。"""
    with TestClient(create_app()) as c:
        s1 = c.post("/agents/runs/stream", json={"input": "12 + 30", "client_run_id": "k-stream"})
        s2 = c.post("/agents/runs/stream", json={"input": "12 + 30", "client_run_id": "k-stream"})
        assert s1.status_code == 200 and s2.status_code == 200
        d1 = _sse_done(s1.text)
        d2 = _sse_done(s2.text)
        assert d1 and d2
        assert d1["run_id"] == d2["run_id"]
        assert d1["state"] == "COMPLETED" and "42" in (d1.get("answer") or "")


def test_nonterminal_rejected():
    """同 key 已有非终态 run（上一条仍在处理）→ 拒绝重复执行，返回 error 事件。"""

    async def _seed_running(state):
        await state.store.create_run(
            run_id="run-inflight",
            tenant_id=state.settings.seed_tenant,
            user_id="u",
            agent_id=state.seed["agent_id"],
            agent_version=1,
            session_id="s-inflight",
            state="RUNNING",
            budget_json={},
            model_config={},
            input_json={"text": "12 + 30"},
            client_run_id="k-inflight",
        )

    with TestClient(create_app()) as c:
        # 通过 app 自身的事件循环 seed（portal 复用同一 loop，避免跨循环连接冲突）
        c.portal.call(_seed_running, c.app.state.agent)
        r = c.post("/agents/runs/stream", json={"input": "12 + 30", "client_run_id": "k-inflight"})
        assert r.status_code == 200
        assert '"type": "error"' in r.text and "在处理中" in r.text


def test_interrupted_message_persists_partial_and_state():
    """中断 run：局部答案 + CANCELLED 状态写入会话历史，刷新后不是空气泡。"""
    from app.agent.api.sessions import persist_chat_messages
    from app.storage.models import SessionRow

    async def _seed(state, run_id, session_id):
        async with state.sessions() as s:
            if await s.get(SessionRow, session_id) is None:
                s.add(
                    SessionRow(
                        id=session_id,
                        tenant_id=state.settings.seed_tenant,
                        user_id="u",
                        agent_id=state.seed["agent_id"],
                        agent_version=1,
                    )
                )
                await s.commit()
        await state.store.create_run(
            run_id=run_id,
            tenant_id=state.settings.seed_tenant,
            user_id="u",
            agent_id=state.seed["agent_id"],
            agent_version=1,
            session_id=session_id,
            state="CANCELLED",
            budget_json={},
            model_config={},
            input_json={"text": "12 + 30"},
        )
        await state.store.finish_run(
            run_id=run_id,
            state="CANCELLED",
            output_json={"answer": "部分答案…"},
            error_json=None,
            tokens_in=0,
            tokens_out=0,
            cost=0.0,
        )
        await persist_chat_messages(state, run_id)

    with TestClient(create_app()) as c:
        state = c.app.state.agent
        c.portal.call(_seed, state, "run-cancelled", "ses-cancelled")
        msgs = c.get("/agents/sessions/ses-cancelled/messages").json()["messages"]
        asst = [m for m in msgs if m["role"] == "assistant"]
        assert asst and asst[0]["content"] == "部分答案…"
        assert asst[0]["state"] == "CANCELLED"


async def test_task_cancel_persists_partial_and_state(deps, store):
    """客户端断开路径（任务被 cancel → CancelledError）：局部内容 + CANCELLED 落 run。"""
    from app.agent.model.gateway import MockProvider, ModelResult
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.runtime import execute_run
    from app.common.contracts import RunInput

    class _SlowStream(MockProvider):
        async def stream(self, messages, tools, model, on_token=None, token=None):
            text = "退款 3-5 个工作日到账"
            for ch in text:
                if on_token:
                    await on_token(ch)
                await asyncio.sleep(0.03)
            return ModelResult(
                content=text, tokens_in=len(messages), tokens_out=len(text), cost=0, model=model
            )

    deps.gateway.provider = _SlowStream()
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="hello")

    async def _emit(event) -> None:  # 非 None emit → 走 provider.stream 流式
        pass

    task = asyncio.create_task(
        execute_run(
            req,
            deps,
            run_id="r-abort",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
            emit=_emit,
        )
    )
    await asyncio.sleep(0.3)  # 流出一部分 token 后模拟客户端断开
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)  # 吞掉 CancelledError

    run = await store.get_run("r-abort")
    assert run["state"] == "CANCELLED"
    out = json.loads(run["output_json"] or "{}")
    assert "退款" in out.get("answer", ""), f"partial content lost: {out!r}"


async def test_task_cancel_no_content_still_cancelled(deps, store):
    """取消发生在出任何内容之前：状态仍落 CANCELLED（刷新后能识别为中断，而非空气泡）。"""
    from app.agent.model.gateway import MockProvider, ModelResult
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.runtime import execute_run
    from app.common.contracts import RunInput

    class _SlowStart(MockProvider):
        async def stream(self, messages, tools, model, on_token=None, token=None):
            await asyncio.sleep(5)  # 长时间不吐内容
            return ModelResult(content="答案", tokens_in=1, tokens_out=1, cost=0, model=model)

    deps.gateway.provider = _SlowStart()
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="hello")

    async def _emit(event) -> None:
        pass

    task = asyncio.create_task(
        execute_run(
            req,
            deps,
            run_id="r-abort-empty",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
            emit=_emit,
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    run = await store.get_run("r-abort-empty")
    assert run["state"] == "CANCELLED"
