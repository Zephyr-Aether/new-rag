"""版本化检索缓存 + Singleflight（§49.5 / §49.7 / §49.6 Redis）。"""

import asyncio

import pytest

from app.knowledge.cache import RedisRetrievalCache, RetrievalCache
from app.knowledge.embedding import EmbeddingCache, HashEmbedding
from app.knowledge.retrieval import KnowledgeService, RetrievalRequest
from app.knowledge.store import KnowledgeStore


async def test_cache_hit_and_version_bust(sessions):
    calls = {"n": 0}

    class _CountingEmbedding(HashEmbedding):
        async def embed(self, texts):
            calls["n"] += 1
            return await super().embed(texts)

    cache = RetrievalCache(ttl_s=300)
    svc = KnowledgeService(KnowledgeStore(sessions), _CountingEmbedding(), cache=cache)
    await svc.ingest_markdown(tenant_id="t", document_id="d", title="T", text="## 退款\n退款到账三天。")

    await svc.search(RetrievalRequest(query="退款", tenant_id="t"))
    calls["n"] = 0
    # 同参再搜：缓存命中，不重算 embedding
    r2 = await svc.search(RetrievalRequest(query="退款", tenant_id="t"))
    assert r2.hits and calls["n"] == 0
    # §49.5 换 knowledge_version：key 变 => 重算
    r3 = await svc.search(RetrievalRequest(query="退款", tenant_id="t", knowledge_version="v2"))
    assert r3.hits and calls["n"] == 1


async def test_cache_permission_scope_isolated(sessions):
    cache = RetrievalCache()
    svc = KnowledgeService(KnowledgeStore(sessions), HashEmbedding(), cache=cache)
    await svc.ingest_markdown(
        tenant_id="t", document_id="conf", title="机密", text="## 机密\n机密内容", permission="confidential"
    )
    r_public = await svc.search(RetrievalRequest(query="机密", tenant_id="t", permission="public"))
    r_conf = await svc.search(RetrievalRequest(query="机密", tenant_id="t", permission="confidential"))
    # 权限 scope 不同 => 缓存不串（public 不命中 confidential 的结果）
    assert all(h.document_id != "conf" for h in r_public.hits)
    assert any(h.document_id == "conf" for h in r_conf.hits)


async def test_singleflight_coalesces(sessions):
    calls = {"n": 0}

    class _CountingEmbedding(HashEmbedding):
        async def embed(self, texts):
            await asyncio.sleep(0.01)
            calls["n"] += 1
            return await super().embed(texts)

    cache = RetrievalCache()
    svc = KnowledgeService(KnowledgeStore(sessions), _CountingEmbedding(), cache=cache)
    await svc.ingest_markdown(tenant_id="t", document_id="d", title="T", text="## 退款\n退款到账三天。")
    calls["n"] = 0  # ingest 也会 embed，清零后只看检索
    req = RetrievalRequest(query="退款", tenant_id="t")
    # §49.7 并发同 key：Singleflight 合并，embedding 只算一次
    results = await asyncio.gather(*[svc.search(req) for _ in range(5)])
    assert all(r.hits for r in results)
    assert calls["n"] == 1


async def test_embedding_cache_skips_reembed_on_ingest(sessions):
    """§15.4 增量索引 hash 缓存：相同文本跳过重算；只 embed 新增块。"""
    calls = {"n": 0}

    class _CountingEmbedding(HashEmbedding):
        async def embed(self, texts):
            calls["n"] += 1
            return await super().embed(texts)

    svc = KnowledgeService(KnowledgeStore(sessions), _CountingEmbedding(), embedding_cache=EmbeddingCache())
    text = "## 退款\n退款到账三天。\n## 退货\n30 天内可退货。"
    await svc.ingest_markdown(tenant_id="t", document_id="d1", title="T", text=text)
    calls["n"] = 0
    # 相同文档再 ingest：全部缓存命中，不重算 embedding
    await svc.ingest_markdown(tenant_id="t", document_id="d1", title="T", text=text)
    assert calls["n"] == 0
    # 增量：只 embed 新增块
    await svc.ingest_markdown(tenant_id="t", document_id="d1", title="T", text=text + "\n## 物流\n3 天送达。")
    assert calls["n"] == 1


async def test_redis_retrieval_cache():
    """§49.6 跨实例缓存：Redis GET/SET（TTL）。Redis 不可用时跳过。"""
    try:
        import redis.asyncio as aioredis

        probe = aioredis.from_url("redis://127.0.0.1:6379/15", decode_responses=True)
        await probe.ping()
        await probe.flushdb()
    except Exception:  # noqa: BLE001
        pytest.skip("Redis 不可用，跳过")

    cache = RedisRetrievalCache("redis://127.0.0.1:6379/15", ttl_s=300)
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"hits": [{"chunk_id": "c1", "score": 0.9}], "provenance": ["d#s#0"]}

    first = await cache.get_or_load("k1", loader)
    assert first["hits"]
    v2 = await cache.get_or_load("k1", loader)
    assert calls["n"] == 1  # 第二次命中 Redis，loader 不重跑
    assert v2["hits"][0]["chunk_id"] == "c1"
    await (await cache._client()).flushdb()  # noqa: SLF001


async def test_cache_warmup_background_load():
    """§49.7 预热：热点 key 后台加载，首个真实请求即命中（loader 不重跑）。"""
    cache = RetrievalCache()
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"hits": [{"chunk_id": "c1", "score": 0.9}]}

    cache.warm(loader, "w1")
    await asyncio.sleep(0.05)  # 后台预热完成
    v = await cache.get_or_load("w1", loader)
    assert v["hits"] and calls["n"] == 1  # 预热后首个请求即命中


async def test_ingest_clears_cache(sessions):
    """入库新内容后缓存必须失效：同 query 应立即检索到新文档（回归：旧结果遮蔽新内容）。"""
    cache = RetrievalCache(ttl_s=300)
    svc = KnowledgeService(KnowledgeStore(sessions), HashEmbedding(), cache=cache)
    await svc.ingest_markdown(tenant_id="t", document_id="a", title="A", text="## 保修\n烤箱保修期一年。")
    await svc.search(RetrievalRequest(query="金星烤箱保修", tenant_id="t"))  # 缓存旧结果（此时无 b）
    await svc.ingest_markdown(tenant_id="t", document_id="b", title="B", text="## 保修\n金星烤箱保修期两年。")
    r = await svc.search(RetrievalRequest(query="金星烤箱保修", tenant_id="t"))
    assert any(h.document_id == "b" for h in r.hits), "入库后缓存应失效，新文档立即可检索"
