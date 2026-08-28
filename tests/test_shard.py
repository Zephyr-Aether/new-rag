"""§24 租户分区：shard 稳定、同租户同分区、分区过滤检索、shard_count=1 行为不变。"""

from app.knowledge.embedding import HashEmbedding
from app.knowledge.retrieval import KnowledgeService, RetrievalRequest
from app.knowledge.store import KnowledgeStore


async def test_shard_for_stable(sessions):
    store = KnowledgeStore(sessions, shard_count=4)
    s1 = store.shard_for("t1")
    assert 0 <= s1 < 4
    assert store.shard_for("t1") == s1  # 同一租户稳定落在同一分区


async def test_chunks_stored_in_tenant_shard(sessions):
    store = KnowledgeStore(sessions, shard_count=4)
    svc = KnowledgeService(store, HashEmbedding())
    await svc.ingest_markdown(tenant_id="tA", document_id="d1", title="a", text="## X\n内容A。")
    shard = store.shard_for("tA")
    chunks = await store.all_chunks("tA")
    assert chunks and all(c["shard"] == shard for c in chunks)
    assert len(await store.all_chunks("tA", shard=shard)) == len(chunks)
    assert await store.all_chunks("tA", shard=(shard + 1) % 4) == []  # 其他分区为空


async def test_shard_one_no_change(sessions):
    store = KnowledgeStore(sessions, shard_count=1)
    assert store.shard_for("any") == 0
    svc = KnowledgeService(store, HashEmbedding())
    await svc.ingest_markdown(tenant_id="tA", document_id="d1", title="a", text="## 分区\n内容A。")
    res = await svc.search(RetrievalRequest(query="内容", tenant_id="tA", top_k=5))
    assert res.hits and res.hits[0].document_id == "d1"


async def test_vector_search_scoped_to_shard(sessions):
    store = KnowledgeStore(sessions, shard_count=2)
    svc = KnowledgeService(store, HashEmbedding())
    await svc.ingest_markdown(tenant_id="tA", document_id="d1", title="a", text="## X\n内容A。")
    qvec = (await HashEmbedding().embed(["内容"]))[0]
    shard = store.shard_for("tA")
    hits = await store.vector_search("tA", qvec, top_k=5, shard=shard)
    assert hits and hits[0]["document_id"] == "d1"
    assert await store.vector_search("tA", qvec, top_k=5, shard=(shard + 1) % 2) == []
