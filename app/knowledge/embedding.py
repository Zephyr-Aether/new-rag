"""EmbeddingService（§4.4）。

MVP：
- HashEmbedding：确定性伪向量（哈希技巧词袋 + L2 归一化），离线/测试跑通全链路；
- OpenAIEmbedding：OpenAI 兼容 /embeddings 端点（生产换真语义向量）。
接口留好，后续可切 bge-m3 等本地模型。
"""

import hashlib
import logging
import math
import re
from abc import ABC, abstractmethod

import httpx

from app.common.errors import ModelError
from app.settings import Settings

logger = logging.getLogger(__name__)

EMBED_DIM = 64

# 中英混合分词：拉丁词 + 单个 CJK 字
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[一-鿿]")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class EmbeddingCache:
    """§15.4/§24 embedding 幂等缓存：text_hash -> vector。

    相同文本 + 相同 embed 版本 => 同向量（幂等）；增量索引时跳过未变块。
    版本入 key：embed 模型升级后自然产生新 key。
    """

    def __init__(self):
        self._store: dict[str, list[float]] = {}

    @staticmethod
    def key(text: str, embed_version: str) -> str:
        return hashlib.sha256(f"{embed_version}|{text}".encode()).hexdigest()

    def get(self, text: str, embed_version: str) -> list[float] | None:
        return self._store.get(self.key(text, embed_version))

    def set(self, text: str, embed_version: str, vector: list[float]) -> None:
        self._store[self.key(text, embed_version)] = vector


class EmbeddingService(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def version(self) -> str:
        """embedding 模型版本（§49.5 缓存键维度）。"""
        return "unknown"


class HashEmbedding(EmbeddingService):
    """确定性伪向量：token 哈希映射到带符号桶，L2 归一化。同文本 -> 同向量（幂等，§4.4 缓存友好）。"""

    dim = EMBED_DIM

    @property
    def version(self) -> str:
        return "hash"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in tokenize(text):
            h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h & 1) else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [round(x / norm, 6) for x in v]


class OpenAIEmbedding(EmbeddingService):
    def __init__(self, settings: Settings, transport=None):
        if not settings.llm_base_url:
            raise ModelError("APP_LLM_BASE_URL required for provider=openai embedding")
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.embedding_model
        self.timeout_s = settings.llm_timeout_s
        self.transport = transport  # 测试注入 MockTransport
        self._hash_fallback = HashEmbedding()
        self._broken = False  # 首次失败后粘滞回退 hash，避免每次重复报错

    @property
    def version(self) -> str:
        return "hash" if self._broken else self.model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # embedding 端点不可用（模型名/配额/网络）时回退本地 hash 伪向量，不阻断写入/召回
        if self._broken:
            return await self._hash_fallback.embed(texts)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers=headers,
            )
        if resp.status_code >= 400:
            self._broken = True
            logger.warning(
                "embedding endpoint failed (%s %s), fallback to hash", resp.status_code, resp.text[:120]
            )
            return await self._hash_fallback.embed(texts)
        data = resp.json()["data"]
        return [d["embedding"] for d in data]


def make_embedding(settings: Settings) -> EmbeddingService:
    if settings.llm_provider == "openai":
        return OpenAIEmbedding(settings)
    return HashEmbedding()
