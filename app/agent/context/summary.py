"""Context 生命周期分层（§10.4）：近轮保留原文，旧轮折叠为摘要。

- llm 提供时用 LLM 摘要；否则规则摘要（截断 + 轮次标注）。
- 配合 §50.4：Recent 原文 / Old 摘要 / Long-term 进 Memory / Retrieval 按需。
"""

import logging

logger = logging.getLogger("agent-platform.context")


async def _summarize(messages: list[dict], llm=None) -> str:
    text = " ".join(str(m.get("content", "")) for m in messages if m.get("content"))
    if not text:
        return ""
    if llm is not None:
        try:
            res = await llm(text)
            if res:
                return str(res)[:500]
        except Exception as exc:  # noqa: BLE001 摘要失败回落规则
            logger.warning("history summary via llm failed: %s", exc)
    return f"{text[:120]}…（共 {len(messages)} 条历史已折叠）"


async def compress_history(messages: list[dict], *, keep_recent: int = 5, llm=None) -> list[dict]:
    """§10.4 历史压缩：近 keep_recent 条保留原文，更早的折叠成一条摘要。"""
    if len(messages) <= keep_recent:
        return messages
    older, recent = messages[:-keep_recent], messages[-keep_recent:]
    summary = await _summarize(older, llm)
    prefix = [{"role": "system", "content": f"（历史摘要）{summary}"}] if summary else []
    return prefix + recent


def _total_tokens(messages: list[dict]) -> int:
    from app.knowledge.embedding import tokenize

    return sum(len(tokenize(str(m.get("content", "")))) for m in messages)


async def apply_context_budget(messages: list[dict], *, max_tokens: int, keep_recent: int = 5) -> list[dict]:
    """§10.4 上下文生命周期分层 + 预算：近轮原文、旧轮摘要；仍超预算则进一步收紧。

    防止 Context Overflow（§5.6）：system + 摘要 + 最近 keep_recent 轮，总量受 max_tokens 约束。
    """
    if len(messages) > keep_recent * 2:
        messages = await compress_history(messages, keep_recent=keep_recent)
    if _total_tokens(messages) <= max_tokens:
        return messages
    # 仍超预算：只保留 system + 摘要 + 最近 2 条
    return await compress_history(messages, keep_recent=2)
