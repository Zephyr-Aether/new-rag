"""KnowledgeService：ingest + 混合检索（向量 + BM25 → RRF → rerank），§15。

MVP 取舍：rerank 目前为恒等（保留 RRF 序），接口已留（§15.5 换 cross-encoder）；
embedding 用 HashEmbedding（离线），生产切 OpenAIEmbedding/本地模型。
"""

import math
import uuid
from collections import Counter

from pydantic import BaseModel

from app.common.contracts import RETRIEVAL_KNOWLEDGE_VERSION, RETRIEVAL_TOP_K, Subject
from app.knowledge.cache import RetrievalCache
from app.knowledge.chunker import chunk_markdown
from app.knowledge.embedding import EmbeddingCache, EmbeddingService, tokenize
from app.knowledge.rerank import IdentityReranker, Reranker
from app.knowledge.store import KnowledgeStore
from app.tool.registry import ToolDefinition, ToolRegistry

BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60


def chunk_id_for(tenant_id: str, document_id: str, seq: int) -> str:
    """确定性块 id（可复现、可回源、评测 gold 可用 doc+seq 引用）。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{document_id}:{seq}").hex


class RetrievalRequest(BaseModel):
    query: str
    tenant_id: str
    top_k: int = 20
    bm25_top_k: int = 20
    rerank_n: int = 5
    kb_filter: str | None = None  # 限定文档（MVP：文档 id 前缀匹配）
    kb_id: str | None = None  # §15.5 限定知识库
    permission: str | None = None  # §15.6 权限前置过滤：无权限内容的块不进入候选集
    knowledge_version: str = "0"  # §63：KB 版本，入缓存键（版本升级自然失效）


class ChunkHit(BaseModel):
    chunk_id: str
    document_id: str
    seq: int
    section: str
    source: str
    text: str
    score: float
    rankers: list[str] = []  # 命中的检索器（vector/bm25）


class RetrievalResult(BaseModel):
    hits: list[ChunkHit]
    provenance: list[str]  # "document#section#seq"，供引用/审计回源


def bm25_rank(chunks: list[dict], query_tokens: list[str], top_k: int) -> list[dict]:
    if not chunks:
        return []
    corpus = [tokenize(c["text"]) for c in chunks]
    n = len(corpus)
    avg_dl = sum(len(d) for d in corpus) / n
    df = Counter()
    for d in corpus:
        df.update(set(d))
    idf = {t: math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1.0) for t in set(query_tokens)}
    for c, d in zip(chunks, corpus, strict=False):
        tf = Counter(d)
        dl = len(d)
        c["bm25_score"] = sum(
            idf.get(t, 0.0)
            * (tf[t] * (BM25_K1 + 1))
            / (tf[t] + BM25_K1 * (1 - BM25_B + BM25_B * dl / avg_dl))
            for t in set(query_tokens)
        )
    chunks.sort(key=lambda c: c["bm25_score"], reverse=True)
    return chunks[:top_k]


def rrf_fuse(*lists: list[dict], k: int = RRF_K) -> list[dict]:
    """RRF 融合（§4.6）：只依赖名次，不需归一化各检索器分数。"""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    rankers: dict[str, set[str]] = {}
    for lst in lists:
        for rank, item in enumerate(lst):
            cid = item["chunk_id"]
            items.setdefault(cid, item)
            rankers.setdefault(cid, set())
            # 记录命中的检索器（调用方在 item 上标记）
            if "vector_score" in item and item["vector_score"] is not None:
                rankers[cid].add("vector")
            if "bm25_score" in item and item["bm25_score"] is not None:
                rankers[cid].add("bm25")
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    merged = sorted(items.values(), key=lambda it: scores[it["chunk_id"]], reverse=True)
    for it in merged:
        it["score"] = round(scores[it["chunk_id"]], 4)
        it["rankers"] = sorted(rankers[it["chunk_id"]])
    return merged


class KnowledgeService:
    def __init__(
        self,
        store: KnowledgeStore,
        embedding: EmbeddingService,
        reranker: Reranker | None = None,
        cache: RetrievalCache | None = None,
        embedding_cache: EmbeddingCache | None = None,
    ):
        self.store = store
        self.embedding = embedding
        self.reranker = reranker or IdentityReranker()
        self.cache = cache
        self.embedding_cache = embedding_cache

    async def ingest_markdown(
        self,
        *,
        tenant_id: str,
        document_id: str,
        title: str,
        text: str,
        source_uri: str = "",
        permission: str = "",
        kb_id: str = "default",
    ) -> int:
        pieces = chunk_markdown(text)
        # §15.4 增量索引 hash 缓存：相同文本跳过重算 embedding
        if self.embedding_cache is not None:
            vecs = []
            to_embed: list[str] = []
            for p in pieces:
                v = self.embedding_cache.get(p.text, self.embedding.version)
                if v is not None:
                    vecs.append(v)
                else:
                    to_embed.append(p.text)
                    vecs.append(None)
            if to_embed:
                new_vecs = await self.embedding.embed(to_embed)
                j = 0
                for i, v in enumerate(vecs):
                    if v is None:
                        vecs[i] = new_vecs[j]
                        self.embedding_cache.set(pieces[i].text, self.embedding.version, new_vecs[j])
                        j += 1
        else:
            vecs = await self.embedding.embed([p.text for p in pieces])
        rows = [
            {
                "chunk_id": chunk_id_for(tenant_id, document_id, p.seq),
                "document_id": document_id,
                "kb_id": kb_id,
                "seq": p.seq,
                "section": p.section,
                "source": f"{title}#{p.section}#{p.seq}",
                "text": p.text,
                "token_count": len(tokenize(p.text)),
                "embedding": vec,
                "permission": permission,
                "hash": f"{document_id}:{p.seq}",
            }
            for p, vec in zip(pieces, vecs, strict=False)
        ]
        # 整体替换（增量更新按来源 id，§15.4）
        await self.store.delete_document_chunks(tenant_id=tenant_id, document_id=document_id)
        await self.store.upsert_document(
            document_id=document_id,
            tenant_id=tenant_id,
            kb_id=kb_id,
            owner_id="",
            title=title,
            source_uri=source_uri,
            hash=document_id,
        )
        await self.store.add_chunks(tenant_id=tenant_id, chunks=rows)
        await self._clear_cache()  # 知识库变更：清检索缓存，防新内容被旧结果遮蔽
        return len(rows)

    async def delete_document(self, tenant_id: str, document_id: str) -> bool:
        ok = await self.store.delete_document(tenant_id=tenant_id, document_id=document_id)
        if ok:
            await self._clear_cache()
        return ok

    async def _clear_cache(self) -> None:
        if self.cache is not None:
            await self.cache.clear()

    async def search(self, req: RetrievalRequest) -> RetrievalResult:
        async def _do() -> RetrievalResult:
            shard = self.store.shard_for(req.tenant_id)  # §24 租户分区：只扫该分区
            # §15.5 库级检索参数：指定知识库时用其配置覆盖默认 top_k/bm25_top_k/rerank_n
            top_k, bm25_top_k, rerank_n = req.top_k, req.bm25_top_k, req.rerank_n
            if req.kb_id:
                cfg = await self.store.get_base_config(tenant_id=req.tenant_id, kb_id=req.kb_id)
                top_k = cfg.get("top_k") or top_k
                bm25_top_k = cfg.get("bm25_top_k") or bm25_top_k
                rerank_n = cfg.get("rerank_n") or rerank_n
            chunks = await self.store.all_chunks(req.tenant_id, shard=shard, kb_id=req.kb_id)
            if req.kb_filter:
                chunks = [
                    c
                    for c in chunks
                    if c["document_id"] == req.kb_filter or req.kb_filter in c["document_id"]
                ]
            # §15.6 权限前置：无权限块（公开）或权限匹配才进入候选集——先过滤后召回
            if req.permission:
                chunks = [c for c in chunks if not c["permission"] or c["permission"] == req.permission]
            if not chunks:
                return RetrievalResult(hits=[], provenance=[])

            qvec = (await self.embedding.embed([req.query]))[0]
            # §23 pgvector：Postgres 走 SQL 距离检索；SQLite 暴力余弦（store 内分派）
            vec_hits = await self.store.vector_search(
                req.tenant_id, qvec, top_k, permission=req.permission, shard=shard, kb_id=req.kb_id
            )

            bm25_hits = bm25_rank([dict(c) for c in chunks], tokenize(req.query), bm25_top_k)
            for c in bm25_hits:
                c.setdefault("vector_score", None)

            fused = rrf_fuse(vec_hits, bm25_hits)
            # §15.5 Rerank 漏斗：fusion 后精排，再取 top-n 进 Context
            top = await self.reranker.rerank(query=req.query, candidates=fused, n=rerank_n)
            hits = [
                ChunkHit(
                    chunk_id=c["chunk_id"],
                    document_id=c["document_id"],
                    seq=c["seq"],
                    section=c["section"],
                    source=c["source"],
                    text=c["text"],
                    score=c["score"],
                    rankers=c.get("rankers", []),
                )
                for c in top
            ]
            return RetrievalResult(
                hits=hits, provenance=[f"{h.document_id}#{h.section}#{h.seq}" for h in hits]
            )

        if self.cache is None:
            return await _do()
        # §49.5 版本化缓存：key 含 tenant/permission/kb_version/embed_version/query
        cache_key = self.cache.key(
            tenant_id=req.tenant_id,
            query=req.query,
            permission=req.permission or "",
            kb_version=req.knowledge_version,
            embed_version=self.embedding.version,
        )
        cached = await self.cache.get_or_load(cache_key, _do)
        if isinstance(cached, RetrievalResult):
            return cached
        return RetrievalResult(**cached)  # Redis 后端返回 dict，包回模型


def register_knowledge_tool(registry: ToolRegistry, service: KnowledgeService) -> None:
    """把检索注册为工具（§7 Agentic RAG：检索通道以工具暴露给模型自选）。"""

    async def _kb_search(subject: Subject, query: str, k: int = 5, **_ignored) -> list[dict]:
        # **_ignored：LLM 可能幻觉多余参数（如伪造 tenant_id），一律忽略——租户只信 subject（§15.6）
        # §60 Replay 换检索参数：Run 级 top_k 覆盖优先
        override_k = RETRIEVAL_TOP_K.get()
        if override_k is not None:
            k = min(k, override_k)
        res = await service.search(
            RetrievalRequest(
                query=query,
                tenant_id=subject.tenant_id,
                top_k=k,
                bm25_top_k=k,
                rerank_n=k,
                # §22.1 版本冻结：Run 级 knowledge_version（无则回落默认 "0"）
                knowledge_version=RETRIEVAL_KNOWLEDGE_VERSION.get() or "0",
            )
        )
        return [
            {
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "section": h.section,
                "text": h.text[:500],
                "score": h.score,
            }
            for h in res.hits
        ]

    registry.register(
        ToolDefinition(
            ref="kb.search",
            description="检索企业内部知识库，返回最相关的文档片段（含来源与分数）。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词/问题"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
            },
            fn=_kb_search,
            permission="knowledge:search",
            context_aware=True,
            timeout_s=10.0,  # §9.1 分层超时：RAG 检索上限（超时抛 TOOL_TIMEOUT）
        )
    )
