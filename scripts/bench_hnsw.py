"""§54 HNSW 参数 Benchmark 治理：真实语料测 M / efConstruction / efSearch。

用法：make bench-hnsw 或 python scripts/bench_hnsw.py
前置：docker compose up -d pgvector（5433）。
以设计文档真实文本为语料，穷举参数组合，输出 Recall@10 / 建索引耗时 / 查询延迟，
据此选参（不凭经验拍）。退出码：全部配置跑通=0。
"""

import asyncio
import glob
import os
import statistics
import time

os.environ.setdefault("APP_DATABASE_URL", "postgresql+asyncpg://agent:agent@127.0.0.1:5433/agent")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from sqlalchemy import text  # noqa: E402

from app.knowledge.embedding import HashEmbedding, cosine  # noqa: E402
from app.knowledge.retrieval import KnowledgeService  # noqa: E402
from app.knowledge.store import KnowledgeStore  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402

BENCH_TENANT = "bench"
CONFIGS = [
    {"m": 16, "ef_construction": 64, "ef_search": 40},
    {"m": 16, "ef_construction": 64, "ef_search": 100},
    {"m": 32, "ef_construction": 128, "ef_search": 40},
    {"m": 32, "ef_construction": 128, "ef_search": 100},
    {"m": 32, "ef_construction": 200, "ef_search": 200},
]
N_QUERIES = 20
K = 10


async def main() -> int:
    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    store = KnowledgeStore(sessions)
    await store.setup_pgvector()
    svc = KnowledgeService(store, HashEmbedding())
    emb = HashEmbedding()

    # 真实语料：设计文档全文切块
    corpus = "\n\n".join(open(p, encoding="utf-8").read() for p in glob.glob("docs/*.md"))
    n = await svc.ingest_markdown(tenant_id=BENCH_TENANT, document_id="bench", title="bench", text=corpus)
    chunks = await store.all_chunks(BENCH_TENANT)
    queries = chunks[:N_QUERIES]
    print(f"[corpus] chunks={n}, queries={N_QUERIES}, dim=64")

    # 精确 top-k（暴力余弦）作为 gold
    gold: dict[str, set[str]] = {}
    all_emb = [(c["chunk_id"], c["embedding"]) for c in chunks]
    for q in queries:
        qv = (await emb.embed([q["text"]]))[0]
        gold[q["chunk_id"]] = {
            cid for _, cid in sorted(((cosine(qv, e), cid) for cid, e in all_emb), reverse=True)[:K]
        }

    print(f"{'M':>3} {'efC':>5} {'efS':>5} {'build(s)':>8} {'Recall@10':>9} {'p50(ms)':>8} {'p95(ms)':>8}")
    for cfg in CONFIGS:
        async with sessions() as s:
            await s.execute(text("DROP INDEX IF EXISTS idx_bench_hnsw"))
            t0 = time.monotonic()
            await s.execute(
                text(
                    "CREATE INDEX idx_bench_hnsw ON chunks USING hnsw "
                    "((embedding::vector(64)) vector_cosine_ops) "
                    f"WITH (m = {cfg['m']}, ef_construction = {cfg['ef_construction']})"
                )
            )
            build_s = time.monotonic() - t0
            await s.commit()

        recalls, lats = [], []
        for q in queries:
            qv = (await emb.embed([q["text"]]))[0]
            vec = "[" + ",".join(str(x) for x in qv) + "]"
            t0 = time.monotonic()
            async with sessions() as s:
                await s.execute(text(f"SET LOCAL hnsw.ef_search = {cfg['ef_search']}"))
                rows = await s.execute(
                    text(
                        "SELECT chunk_id FROM chunks WHERE tenant_id = :tenant "
                        "ORDER BY embedding::vector(64) <=> CAST(:v AS vector(64)) LIMIT :k"
                    ),
                    {"tenant": BENCH_TENANT, "v": vec, "k": K},
                )
                hit_ids = {r.chunk_id for r in rows}
            lats.append((time.monotonic() - t0) * 1000)
            recalls.append(len(hit_ids & gold[q["chunk_id"]]) / K)

        p95 = sorted(lats)[max(int(len(lats) * 0.95) - 1, 0)]
        print(
            f"{cfg['m']:>3} {cfg['ef_construction']:>5} {cfg['ef_search']:>5} "
            f"{build_s:>8.2f} {statistics.mean(recalls):>9.3f} "
            f"{statistics.median(lats):>8.1f} {p95:>8.1f}"
        )

    await engine.dispose()
    print("== 选参建议：在满足 Recall 要求下选 build 快 / p95 低 的组合 ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
