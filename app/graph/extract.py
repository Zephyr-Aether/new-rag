"""Graph 抽取管线（§16 Pipeline）：LLM 从文档抽事实，规则兜底。

- 有 llm 时：请求模型输出 JSON 事实列表；解析失败/无 llm 则走规则。
- 规则：中文"X 的 P 是 Y"模式（MVP；生产以 LLM 抽取为主）。
"""

import json
import re

_FACT_RE = re.compile(r"(.{1,40}?)\s*的\s*([^，。；]{1,12}?)\s*是\s*(.{1,40}?)[。；;]")
_EXTRACT_SYSTEM = "从文本抽取事实三元组 (subject, predicate, object)，仅输出 JSON 数组，不要其它文字。"


class GraphExtractor:
    def __init__(self, llm=None):
        self.llm = llm  # async callable(text) -> str（模型 JSON 输出）

    async def extract(self, text: str) -> list[dict]:
        if self.llm is not None:
            try:
                raw = await self.llm(text)
                parsed = self._parse_json_array(raw)
                if isinstance(parsed, list):
                    # 兼容两种模型输出：对象数组 [{subject,predicate,object}] 或 数组套数组 [[s,p,o]]
                    facts: list[dict] = []
                    for f in parsed:
                        if isinstance(f, dict) and {"subject", "predicate", "object"} <= f.keys():
                            facts.append(f)
                        elif isinstance(f, (list, tuple)) and len(f) >= 3:
                            facts.append(
                                {
                                    "subject": str(f[0]).strip(),
                                    "predicate": str(f[1]).strip(),
                                    "object": str(f[2]).strip(),
                                }
                            )
                    if facts:
                        for f in facts:
                            f.setdefault("confidence", 0.85)
                            f.setdefault("extracted_by", "llm")
                        return facts
            except Exception:  # noqa: BLE001 模型输出不可解析则回落规则
                pass
        return self._rules(text)

    @staticmethod
    def _parse_json_array(raw: str):
        """从模型输出提取 JSON 数组（容忍 markdown 代码围栏/前后缀文字）。"""
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None

    def _rules(self, text: str) -> list[dict]:
        facts: list[dict] = []
        for m in _FACT_RE.finditer(text):
            subject, predicate, obj = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            if not subject or not predicate or not obj:
                continue
            facts.append(
                {
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "confidence": 0.6,
                    "extracted_by": "rule",
                }
            )
        return facts


async def _llm_extract(gateway, text: str) -> str:
    """把 ModelGateway 接成抽取 LLM（§16 接真 LLM）。"""
    res = await gateway.complete(
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": text},
        ],
        tools=[],
        tier="medium",
    )
    return res.content or ""


def make_graph_extractor(gateway) -> GraphExtractor:
    """GraphExtractor 接 ModelGateway：mock 输出不可解析时自动回落规则。"""
    return GraphExtractor(llm=lambda text: _llm_extract(gateway, text))
