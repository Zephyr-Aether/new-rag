"""pgvector 落地烟测（§23 / §8.3.3）：Postgres + HNSW 距离检索。

用法：make smoke-pgvector 或 python scripts/smoke_pgvector.py
前置：docker compose up -d pgvector（端口 5433）。
退出码：全部通过=0，否则=1（可作 CI 门禁）。
"""

import asyncio
import os

os.environ.setdefault("APP_DATABASE_URL", "postgresql+asyncpg://agent:agent@127.0.0.1:5433/agent")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from sqlalchemy import text  # noqa: E402

from app.knowledge.embedding import HashEmbedding  # noqa: E402
from app.knowledge.retrieval import KnowledgeService, RetrievalRequest  # noqa: E402
from app.knowledge.store import KnowledgeStore  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402


async def main() -> int:
    failures = 0
    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    store = KnowledgeStore(sessions)
    await store.setup_pgvector()

    ok = await store.is_postgres()
    print(f"[{'PASS' if ok else 'FAIL'}] 连接 Postgres（pgvector 容器）")
    failures += not ok

    svc = KnowledgeService(store, HashEmbedding())
    n = await svc.ingest_markdown(
        tenant_id="t", document_id="d", title="T", text="## 退款\n退款到账三天。\n## 退货\n30 天内可退货。"
    )
    print(f"[PASS] ingest chunks={n}")

    res = await svc.search(RetrievalRequest(query="退款到账", tenant_id="t", rerank_n=2))
    ok = bool(res.hits) and res.hits[0].document_id == "d"
    print(f"[{'PASS' if ok else 'FAIL'}] pgvector 检索命中：{res.hits[0].section if res.hits else '-'}")
    failures += not ok

    async with sessions() as s:
        idx = (await s.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'"))).all()
    names = [r[0] for r in idx]
    ok = any("hnsw" in name for name in names)
    print(f"[{'PASS' if ok else 'FAIL'}] HNSW 索引存在：{names}")
    failures += not ok

    await engine.dispose()
    print("== pgvector 烟测：" + ("PASS" if failures == 0 else f"{failures} FAILED") + " ==")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
