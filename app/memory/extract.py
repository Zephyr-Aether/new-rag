"""记忆自动沉淀（§12.4）：对话跑完后用 LLM 提炼用户持久事实，自动写入记忆（untrusted）。

- mock 网关无法可靠提炼，直接跳过；
- 写入走 MemoryService 守卫（注入/敏感内容会被拒，安全兜底）；
- 按内容去重：与已有记忆完全相同的跳过一次。
"""

import json

from app.common.contracts import Subject


class MemoryExtractor:
    def __init__(self, gateway, memory_service):
        self.gateway = gateway
        self.memory_service = memory_service

    async def sediment(self, subject: Subject, messages: list[dict]) -> int:
        """从会话 messages 提炼用户事实并写入记忆，返回写入条数。"""
        if self.gateway.provider.name == "mock":
            return 0  # mock 无法可靠提炼
        user_msgs = [m.get("content") for m in messages if m.get("role") == "user" and m.get("content")]
        if not user_msgs:
            return 0
        convo = "\n".join(f"- {t[:300]}" for t in user_msgs[-10:])
        prompt = (
            "你是记忆沉淀助手。从用户对话中提炼值得长期记住的用户事实（偏好、身份、需求、承诺等），"
            "不要提炼一次性任务指令。每条用一句话客观陈述，避免主观臆测。只输出一个 JSON 数组，例如："
            '["用户喜欢喝美式咖啡", "用户是上海人"]。不要输出其它内容。\n\n对话：\n'
            f"{convo}"
        )
        try:
            res = await self.gateway.complete(
                messages=[{"role": "user", "content": prompt}], tools=[], model=None
            )
        except Exception:  # noqa: BLE001 提炼失败不影响主流程
            return 0
        facts = self._parse_facts(res.content or "")
        written = 0
        for fact in facts:
            if len(fact) < 4 or len(fact) > 200:
                continue
            if await self._content_exists(subject, fact):
                continue
            try:
                await self.memory_service.write(
                    subject,
                    scope="USER",
                    memory_type="SEMANTIC",
                    content=fact,
                    source="auto",
                    source_trust="untrusted",
                )
                written += 1
            except Exception:  # noqa: BLE001 单条失败跳过（含守卫拒绝）
                continue
        return written

    async def _content_exists(self, subject: Subject, fact: str) -> bool:
        """语义去重：召回该事实相关记忆，相似度高于阈值即视为已存在（LLM 措辞差异也命中）。"""
        try:
            entries = await self.memory_service.recall(subject, query=fact, k=3)
        except Exception:  # noqa: BLE001
            return False
        return any(float(e.get("score") or 0) >= 0.88 for e in entries)

    @staticmethod
    def _parse_facts(text: str) -> list[str]:
        text = (text or "").strip()
        try:
            start, end = text.find("["), text.rfind("]")
            if start >= 0 and end > start:
                arr = json.loads(text[start : end + 1])
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if isinstance(x, str) and x.strip()]
        except (ValueError, json.JSONDecodeError):
            pass
        return [
            line.strip("- *").strip()
            for line in text.splitlines()
            if line.strip() and len(line.strip()) < 100
        ]
