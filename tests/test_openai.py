"""OpenAI 兼容端点联调（§8）：通过 MockTransport 走完整 /chat/completions 解析路径。

覆盖：请求构造、tool_calls 解析、usage/成本、Agent 循环端到端。
"""

import json

import httpx

from app.agent.model.gateway import OpenAIProvider
from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.runtime import execute_run
from app.common.contracts import RunInput
from app.knowledge.embedding import OpenAIEmbedding
from app.settings import Settings


def _fake_chat_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    messages = body["messages"]
    # 已有工具回执 => 收束；否则返回 calc.add 工具调用
    if any(m.get("role") == "tool" for m in messages):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Answer: 42 (openai-mock)"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 21},
            },
        )
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "calc.add", "arguments": '{"a": 12, "b": 30}'},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1},
        },
    )


def _openai_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        llm_provider="openai",
        llm_base_url="http://fake-openai",
        llm_api_key="test-key",
    )


async def test_openai_provider_parses_tool_calls():
    transport = httpx.MockTransport(_fake_chat_handler)
    provider = OpenAIProvider(_openai_settings(), transport=transport)
    result = await provider.complete(
        [{"role": "user", "content": "12 + 30"}],
        [{"name": "calc.add", "description": "x", "input_schema": {}}],
        "model-x",
    )
    assert result.tool_calls and result.tool_calls[0].name == "calc.add"
    assert json.loads(result.tool_calls[0].arguments) == {"a": 12, "b": 30}
    assert result.tokens_in == 10 and result.cost > 0


async def test_openai_provider_final_answer():
    transport = httpx.MockTransport(_fake_chat_handler)
    provider = OpenAIProvider(_openai_settings(), transport=transport)
    result = await provider.complete(
        [{"role": "user", "content": "12 + 30"}, {"role": "tool", "tool_call_id": "c1", "content": "42"}],
        [],
        "model-x",
    )
    assert result.content == "Answer: 42 (openai-mock)"


async def test_openai_end_to_end_agent_run(deps):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _fake_chat_handler(request)

    deps.gateway.provider = OpenAIProvider(_openai_settings(), transport=httpx.MockTransport(handler))
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
    result = await execute_run(
        req, deps, run_id="r-openai", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    assert result.state == "COMPLETED"
    assert "42" in (result.answer or "")
    assert calls["n"] == 2  # 工具调用一次 + 收束一次
    assert result.tokens_in > 0 and result.cost > 0


async def test_openai_embedding():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        n = len(body["input"])
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2] * 4} for _ in range(n)]},
        )

    emb = OpenAIEmbedding(_openai_settings(), transport=httpx.MockTransport(handler))
    vectors = await emb.embed(["hello", "world"])
    assert len(vectors) == 2 and len(vectors[0]) == 8


async def test_openai_provider_streams_tokens():
    """流式：stream:true 请求，content 增量回调 on_token。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("stream") is True
        sse = (
            'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
            'data: {"choices":[{"delta":{}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    provider = OpenAIProvider(_openai_settings(), transport=httpx.MockTransport(handler))
    chunks: list[str] = []

    async def collect(t: str) -> None:
        chunks.append(t)

    result = await provider.stream([{"role": "user", "content": "hi"}], [], "m", on_token=collect)
    assert chunks == ["你", "好"]
    assert result.content == "你好"
