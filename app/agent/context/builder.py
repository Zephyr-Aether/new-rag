"""Context Engine 的 MVP 组装（§5.4 子集）。

MVP 阶段：system + user + 逐步追加的 tool 回执；不包含 memory/retrieval 分区
（接口留好，后续 Phase 接 Memory/RAG）。UNTRUSTED 数据隔离在 Phase 补。
"""

from typing import Any


def build_messages(*, system_prompt: str, user_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]


def append_tool_call_block(messages: list[dict], tool_calls: list) -> None:
    """把 LLM 的 tool_calls 意图回填为 assistant 消息（Function Calling 的入参）。"""
    messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in tool_calls
            ],
        }
    )


def append_tool_result(messages: list[dict], tool_call_id: str, content: str) -> None:
    """把工具结果回填为 tool 消息（OBSERVING）。"""
    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
