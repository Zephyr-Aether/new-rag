"""混合检索（§15）：相关命中 / 租户隔离 / provenance / RRF。"""

from app.knowledge.embedding import HashEmbedding
from app.knowledge.retrieval import KnowledgeService, RetrievalRequest, rrf_fuse
from app.knowledge.store import KnowledgeStore

RETURN_DOC = (
    "# 退货政策\n"
    "## 退款到账时间\n退款会在审核通过后 3-5 个工作日内原路退回。\n"
    "## 退货条件\n商品需在签收后 30 天内申请退货。\n"
)
API_DOC = "# API 文档\n## 限流\n每分钟最多 100 次请求，超出返回 429。\n## 鉴权\n使用 Bearer Token 访问。\n"


def _svc(sessions) -> KnowledgeService:
    return KnowledgeService(KnowledgeStore(sessions), HashEmbedding())


async def test_search_finds_relevant_section(sessions):
    svc = _svc(sessions)
    await svc.ingest_markdown(tenant_id="t", document_id="doc-ret", title="退货政策", text=RETURN_DOC)
    await svc.ingest_markdown(tenant_id="t", document_id="doc-api", title="API 文档", text=API_DOC)
    res = await svc.search(RetrievalRequest(query="退款到账要多久", tenant_id="t", top_k=10, rerank_n=5))
    assert res.hits
    assert res.hits[0].document_id == "doc-ret"
    assert "退款" in res.hits[0].section or "到账" in res.hits[0].section


async def test_tenant_isolation(sessions):
    svc = _svc(sessions)
    await svc.ingest_markdown(tenant_id="tA", document_id="doc-ret", title="退货政策", text=RETURN_DOC)
    res = await svc.search(RetrievalRequest(query="退款到账", tenant_id="tB", top_k=5))
    assert res.hits == []  # 跨租户绝不返回


async def test_provenance_present(sessions):
    svc = _svc(sessions)
    await svc.ingest_markdown(tenant_id="t", document_id="doc-ret", title="退货政策", text=RETURN_DOC)
    res = await svc.search(RetrievalRequest(query="退款到账", tenant_id="t", top_k=5))
    assert res.provenance
    assert res.provenance[0].startswith("doc-ret#")


async def test_search_empty_kb(sessions):
    svc = _svc(sessions)
    res = await svc.search(RetrievalRequest(query="anything", tenant_id="t", top_k=5))
    assert res.hits == [] and res.provenance == []


async def test_permission_filter_before_retrieval(sessions):
    """§15.6 权限前置：无权限块的机密内容不进入候选集；匹配权限才返回。"""
    svc = _svc(sessions)
    await svc.ingest_markdown(
        tenant_id="t", document_id="pub", title="公开", text="## 公开信息\n这是公开内容。"
    )
    await svc.ingest_markdown(
        tenant_id="t",
        document_id="conf",
        title="机密",
        text="## 机密\n这是机密内容。",
        permission="confidential",
    )
    # 无权限过滤：机密块可返回
    res = await svc.search(RetrievalRequest(query="机密", tenant_id="t", top_k=10))
    assert any(h.document_id == "conf" for h in res.hits)
    # 权限不匹配：机密块被前置过滤
    res2 = await svc.search(RetrievalRequest(query="机密", tenant_id="t", top_k=10, permission="public"))
    assert all(h.document_id != "conf" for h in res2.hits)
    # 权限匹配：可访问
    res3 = await svc.search(
        RetrievalRequest(query="机密", tenant_id="t", top_k=10, permission="confidential")
    )
    assert any(h.document_id == "conf" for h in res3.hits)


async def test_reranker_default_and_injected(sessions):
    """§15.5 Rerank 接入：默认 Identity，注入 TermBoost 均可用。"""
    from app.knowledge.rerank import IdentityReranker, TermBoostReranker

    svc = KnowledgeService(KnowledgeStore(sessions), HashEmbedding())
    assert isinstance(svc.reranker, IdentityReranker)
    await svc.ingest_markdown(tenant_id="t", document_id="d", title="T", text="## 退款\n退款到账三天。")
    res = await svc.search(RetrievalRequest(query="退款", tenant_id="t", rerank_n=2))
    assert res.hits

    svc2 = KnowledgeService(KnowledgeStore(sessions), HashEmbedding(), reranker=TermBoostReranker())
    res2 = await svc2.search(RetrievalRequest(query="退款到账", tenant_id="t", rerank_n=2))
    assert res2.hits


async def test_term_boost_reranker_reorders():
    from app.knowledge.rerank import TermBoostReranker

    r = TermBoostReranker()
    candidates = [
        {"chunk_id": "a", "text": "无关内容", "score": 0.9},
        {"chunk_id": "b", "text": "退款到账需要三天", "score": 0.5},
    ]
    ranked = await r.rerank(query="退款到账", candidates=candidates, n=2)
    assert ranked[0]["chunk_id"] == "b"  # 词面重合更相关，从第 2 升到第 1


def test_rrf_ranks_overlap_first():
    a = [
        {"chunk_id": "c1", "vector_score": 0.9},
        {"chunk_id": "c2", "vector_score": 0.5},
        {"chunk_id": "c3", "vector_score": 0.4},
    ]
    b = [{"chunk_id": "c1", "bm25_score": 8.0}, {"chunk_id": "c3", "bm25_score": 5.0}]
    fused = rrf_fuse(a, b)
    assert fused[0]["chunk_id"] == "c1"  # 两条路都排第一的块胜出
    assert fused[0]["rankers"] == ["bm25", "vector"]  # 双检索器命中可见
