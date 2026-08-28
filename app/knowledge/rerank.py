"""Rerank（§15.5）：对召回候选精排（cross-encoder 的 MVP 占位）。

- IdentityReranker：保留 RRF 融合序（当前默认）
- TermBoostReranker：按"块与查询词面重合 + 原融合分"确定性重排（MVP 占位）
生产换 cross-encoder（bge-reranker 等）只需实现 Reranker 接口。
"""

from abc import ABC, abstractmethod

from app.knowledge.embedding import tokenize


class Reranker(ABC):
    @abstractmethod
    async def rerank(self, *, query: str, candidates: list[dict], n: int) -> list[dict]: ...


class IdentityReranker(Reranker):
    async def rerank(self, *, query: str, candidates: list[dict], n: int) -> list[dict]:
        return candidates[:n]


class TermBoostReranker(Reranker):
    async def rerank(self, *, query: str, candidates: list[dict], n: int) -> list[dict]:
        q_tokens = set(tokenize(query))

        def score(c: dict) -> tuple[int, float]:
            overlap = len(q_tokens & set(tokenize(c.get("text", ""))))
            return (overlap, float(c.get("score", 0.0)))

        return sorted(candidates, key=score, reverse=True)[:n]
