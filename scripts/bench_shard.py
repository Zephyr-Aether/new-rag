"""§24 百万级分片基准：造 N 个租户各若干文档，对比「全量扫描」vs「按 shard 检索」耗时。

用法：python scripts/bench_shard.py [tenants=20] [docs_per_tenant=10]
"""

import asyncio
import os
import sys
import tempfile
import time

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/bench.db")

from app.knowledge.embedding import HashEmbedding  # noqa: E402
from app.knowledge.retrieval import KnowledgeService  # noqa: E402
from app.knowledge.store import KnowledgeStore  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402

SHARD_COUNT = 4


async def main() -> None:
    n_tenants = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    docs_per = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    store = KnowledgeStore(sessions, shard_count=SHARD_COUNT)
    svc = KnowledgeService(store, HashEmbedding())

    for t in range(n_tenants):
        tid = f"tenant-{t}"
        for d in range(docs_per):
            await svc.ingest_markdown(
                tenant_id=tid,
                document_id=f"doc-{d}",
                title=f"t{t}d{d}",
                text=f"## 分区 {t}.{d}\n租户 {t} 文档 {d} 的知识片段。",
            )
    total = n_tenants * docs_per
    print(f"== 租户分区基准: {n_tenants} tenants x {docs_per} docs = {total} chunks, shards={SHARD_COUNT}")

    qvec = (await HashEmbedding().embed(["知识"]))[0]

    async def bench(tid: str, shard: int | None) -> float:
        start = time.monotonic()
        await store.vector_search(tid, qvec, top_k=5, shard=shard)
        return (time.monotonic() - start) * 1000

    full_ms = await bench("tenant-0", None)
    shard_ms = await bench("tenant-0", store.shard_for("tenant-0"))
    ratio = full_ms / shard_ms if shard_ms else float("inf")
    print(f"tenant-0: 全量扫描 {full_ms:.2f}ms vs 按 shard 检索 {shard_ms:.2f}ms（加速 {ratio:.1f}x）")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
