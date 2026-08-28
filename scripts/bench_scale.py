"""规模压测（§24 真验证的前置）：合成 N 个 chunk 入库，测检索延迟/内存随规模曲线。

用法：python scripts/bench_scale.py --n 50000   # 默认 50k，可配到 1M（耗时/内存线性增长）
输出：入库耗时、chunk 数、检索 P50/P95 延迟、进程内存。
不跑 CI；手动执行。
"""

import argparse
import asyncio
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/scale.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from app.knowledge.embedding import HashEmbedding  # noqa: E402
from app.knowledge.retrieval import KnowledgeService, RetrievalRequest  # noqa: E402
from app.knowledge.store import KnowledgeStore  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402

_SECTIONS = ["政策", "流程", "FAQ", "安全", "成本", "性能", "部署", "运维"]


def _chunk_text(i: int) -> str:
    sec = _SECTIONS[i % len(_SECTIONS)]
    return f"## {sec} {i}\n合成条目 {i}：用于规模压测，包含关键词 aaaaaaaa{random.randint(0, 9)}。"


async def main(n: int) -> int:
    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    ks = KnowledgeService(KnowledgeStore(sessions), HashEmbedding())

    t0 = time.monotonic()
    batch = 500
    for i in range(0, n, batch):
        docs = []
        for j in range(i, min(i + batch, n)):
            docs.append((f"doc-{j}", f"合成文档 {j}", _chunk_text(j)))
        for did, title, text in docs:
            await ks.ingest_markdown(tenant_id="scale", document_id=did, title=title, text=text)
        if i % 5000 == 0:
            print(f"  ingested {min(i + batch, n)}/{n}  ({time.monotonic() - t0:.1f}s)", flush=True)
    ingest_s = time.monotonic() - t0

    # 检索延迟
    queries = [f"关键词 aaaaaaaa{random.randint(0, 9)}" for _ in range(20)]
    lat = []
    for q in queries:
        s0 = time.monotonic()
        await ks.search(RetrievalRequest(query=q, tenant_id="scale", top_k=5, bm25_top_k=20, rerank_n=5))
        lat.append((time.monotonic() - s0) * 1000)
    lat.sort()
    p50 = lat[len(lat) // 2]
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    import resource as res
    import sys as _sys

    maxrss = res.getrusage(res.RUSAGE_SELF).ru_maxrss
    rss_mb = maxrss / (1024 * 1024) if _sys.platform == "darwin" else maxrss / 1024

    print("== 规模压测报告 ==")
    print(f"  chunks: {n}")
    print(f"  入库耗时: {ingest_s:.1f}s  ({n / ingest_s:.0f} chunks/s)")
    print(f"  检索 P50: {p50:.1f}ms  P95: {p95:.1f}ms")
    print(f"  进程峰值内存: {rss_mb:.0f} MB")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50000)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.n)))
