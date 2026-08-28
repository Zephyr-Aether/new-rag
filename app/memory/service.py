"""MemoryService（§12）：写 / 召回 / 删，严格作用域隔离 + §12.3 Memory Poisoning 防护。"""

import re

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.knowledge.embedding import EmbeddingCache, EmbeddingService, cosine, tokenize
from app.memory.store import MemoryStore

# §12.3 注入检测：命中即拒绝写入（防恶意内容污染记忆系统）
_INJECTION_PATTERNS = re.compile(
    r"忽略之前|忽略以上|ignore (all )?(previous|prior) (instructions|prompts|context)|"
    r"system prompt|系统提示词|请扮演|现在你是|你是.{0,8}(AI|助手)|override instructions|"
    r"bypass|disregard|你被劫持|forget everything",
    re.IGNORECASE,
)
# §12.3 敏感检测：email / 手机号 / 密钥
_SENSITIVE_PATTERNS = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+|(?<!\d)1[3-9]\d{9}(?!\d)|sk-[A-Za-z0-9]{16,}|"
    r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY",
)


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        embedding: EmbeddingService | None = None,
        embedding_cache: EmbeddingCache | None = None,
    ):
        self.store = store
        self.embedding = embedding
        self.embedding_cache = embedding_cache or EmbeddingCache()

    async def write(
        self,
        subject: Subject,
        *,
        scope: str = "USER",
        memory_type: str = "SEMANTIC",
        content: str,
        source: str = "",
        source_trust: str = "trusted",
        ttl_days: int | None = None,
        allow_sensitive: bool = False,
    ) -> dict:
        """写记忆（§12.3 写入守卫：注入/敏感内容拒绝，防止 Memory Poisoning）。"""
        self._guard_content(content, allow_sensitive=allow_sensitive)
        embedding = await self._embed(content) if self.embedding is not None else None
        memory_id = await self.store.add(
            tenant_id=subject.tenant_id,
            user_id=subject.user_id,
            agent_id=None,
            scope=scope,
            memory_type=memory_type,
            content=content,
            source=source,
            source_trust=source_trust,
            ttl_days=ttl_days,
            embedding=embedding,
        )
        return {"memory_id": memory_id}

    async def _embed(self, text: str) -> list[float]:
        """embedding 幂等缓存：同文本+同版本 => 同向量（§49.5）。"""
        cached = self.embedding_cache.get(text, self.embedding.version)
        if cached is not None:
            return cached
        vec = (await self.embedding.embed([text]))[0]
        self.embedding_cache.set(text, self.embedding.version, vec)
        return vec

    @staticmethod
    def _guard_content(content: str, *, allow_sensitive: bool = False) -> None:
        """§12.3 写入守卫：命中提示注入或敏感数据则拒绝（除非显式放行敏感）。"""
        if _INJECTION_PATTERNS.search(content):
            raise AgentError(
                "memory content matches prompt-injection pattern",
                code="MEMORY_POISONED",
                detail={"pattern": _INJECTION_PATTERNS.pattern[:60]},
            )
        if not allow_sensitive and _SENSITIVE_PATTERNS.search(content):
            raise AgentError(
                "memory content contains sensitive data (email/phone/secret)",
                code="MEMORY_SENSITIVE",
            )

    async def recall(self, subject: Subject, *, query: str = "", k: int = 5) -> list[dict]:
        """召回：先钉死 tenant+user scope，再做相关性排序（§12.2 跨用户绝不返回）。

        有 embedding 用向量余弦；旧数据无向量时回落关键词重叠。
        """
        entries = await self.store.recall(
            tenant_id=subject.tenant_id, user_id=subject.user_id, agent_id=None, k=k * 2
        )
        if not query:
            return entries[:k]
        q_tokens = set(tokenize(query))
        qvec = await self._embed(query) if self.embedding is not None else None
        for e in entries:
            vec = e.get("embedding") or []
            if qvec is not None and vec:
                e["score"] = round(cosine(qvec, vec), 4)
            else:
                e["score"] = len(q_tokens & set(tokenize(e["content"]))) / len(q_tokens) if q_tokens else 0.0
            e.pop("embedding", None)
        entries.sort(key=lambda e: e["score"], reverse=True)
        return entries[:k]

    async def delete(self, subject: Subject, memory_id: str) -> bool:
        return await self.store.delete(
            tenant_id=subject.tenant_id, user_id=subject.user_id, memory_id=memory_id
        )
