"""离线评测雏形（Phase 3，§19/§20 检索评测的落地）：

    Recall@k / MRR / Faithfulness（启发式，替代 LLM-judge 的占位）

用法：make eval 或 python scripts/eval.py
- 内置样例 KB（两篇 Markdown）+ Golden 评测集（query + 期望命中 doc/section）
- 输出评测报告；可作为"改检索必须过门禁"的脚本（§20 只保留评测提升的改动）
- 无需 Docker / LLM key（HashEmbedding 离线）
"""

import asyncio
import os
import tempfile

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/eval.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from app.knowledge.embedding import HashEmbedding, tokenize  # noqa: E402
from app.knowledge.retrieval import KnowledgeService, RetrievalRequest  # noqa: E402
from app.knowledge.store import KnowledgeStore  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402

EVAL_TENANT = "eval"

SAMPLE_DOCS: dict[str, tuple[str, str]] = {
    "doc-returns": (
        "退货政策",
        "# 退货政策\n"
        "## 退货条件\n商品需在签收后 30 天内申请退货，包装完整不影响二次销售。\n"
        "## 退款到账时间\n退款在审核通过后 3-5 个工作日内原路退回。\n"
        "## 退货运费\n质量问题商家承担运费，其他情况买家承担。\n",
    ),
    "doc-api": (
        "API 文档",
        "# API 文档\n"
        "## 限流\n每分钟最多 100 次请求，超出返回 429。\n"
        "## 错误码\n429=限流，500=服务错误，401=未认证。\n"
        "## 鉴权\n使用 Bearer Token 访问 /v1 接口。\n",
    ),
}

GOLDEN = [
    {"query": "退款多久能到账", "doc": "doc-returns", "section": "退款到账时间"},
    {"query": "退货需要什么条件", "doc": "doc-returns", "section": "退货条件"},
    {"query": "退货运费谁承担", "doc": "doc-returns", "section": "退货运费"},
    {"query": "API 每分钟能请求多少次", "doc": "doc-api", "section": "限流"},
    {"query": "429 是什么错误", "doc": "doc-api", "section": "错误码"},
    {"query": "如何访问 API", "doc": "doc-api", "section": "鉴权"},
]

STOPWORDS = set("的了吗呢在是会把要个与和或这那".split())


def recall_at_k(hits: list[dict], gold_ids: set[str], k: int) -> float:
    if not gold_ids:
        return 0.0
    hit = {h["chunk_id"] for h in hits[:k]}
    return len(hit & gold_ids) / len(gold_ids)


def mrr(hits: list[dict], gold_ids: set[str]) -> float:
    for i, h in enumerate(hits):
        if h["chunk_id"] in gold_ids:
            return 1.0 / (i + 1)
    return 0.0


def heuristic_faithfulness(answer: str, context_texts: list[str]) -> float:
    """Faithfulness 启发式：答案实词出现在检索上下文中的比例（真实产品换 LLM-judge）。"""
    words = set(tokenize(answer)) - STOPWORDS
    ctx = set().union(*(set(tokenize(t)) for t in context_texts)) if context_texts else set()
    if not words:
        return 1.0
    return len(words & ctx) / len(words)


async def main() -> int:
    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    store = KnowledgeStore(sessions)
    svc = KnowledgeService(store, HashEmbedding())

    # 1) 索引样例 KB
    for doc_id, (title, text) in SAMPLE_DOCS.items():
        n = await svc.ingest_markdown(tenant_id=EVAL_TENANT, document_id=doc_id, title=title, text=text)
        print(f"[ingest] {doc_id} -> {n} chunks")

    # 2) 评测
    all_chunks = await store.all_chunks(EVAL_TENANT)
    recalls_1, recalls_3, mrrs, faiths = [], [], [], []
    print(f"\n{'query':<20} {'r@1':<6} {'r@3':<6} {'MRR':<6} {'faith':<6} top_doc")
    for g in GOLDEN:
        res = await svc.search(
            RetrievalRequest(query=g["query"], tenant_id=EVAL_TENANT, top_k=10, bm25_top_k=10, rerank_n=5)
        )
        hits = [h.model_dump() for h in res.hits]
        gold_ids = {
            c["chunk_id"] for c in all_chunks if c["document_id"] == g["doc"] and g["section"] in c["section"]
        }
        r1 = recall_at_k(hits, gold_ids, 1)
        r3 = recall_at_k(hits, gold_ids, 3)
        m = mrr(hits, gold_ids)
        faith = (
            heuristic_faithfulness(hits[0]["text"] if hits else "", [h["text"] for h in hits[:3]])
            if hits
            else 0.0
        )
        recalls_1.append(r1)
        recalls_3.append(r3)
        mrrs.append(m)
        faiths.append(faith)
        top_doc = hits[0]["document_id"] if hits else "-"
        print(f"{g['query']:<20} {r1:<6.2f} {r3:<6.2f} {m:<6.2f} {faith:<6.2f} {top_doc}")

    n = len(GOLDEN)
    print(
        f"\n== 评测报告 ==\n"
        f"Recall@1={sum(recalls_1) / n:.3f}  Recall@3={sum(recalls_3) / n:.3f}  "
        f"MRR={sum(mrrs) / n:.3f}  Faithfulness={sum(faiths) / n:.3f}\n"
    )
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
