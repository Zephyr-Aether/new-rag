"""端到端演示（Phase 0-3 全链路）：健康 → 知识导入 → 工具 → Agent(计算) → Agent(RAG) → Trace → 审计。

用法：make demo 或 python scripts/demo.py（无需 Docker / LLM key，SQLite + mock）
"""

import asyncio
import os
import tempfile

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/demo.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from sqlalchemy import select  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.storage.db import create_engine_and_sessions  # noqa: E402
from app.storage.models import AuditLogRow  # noqa: E402

DOC_TEXT = (
    "# 退货政策\n"
    "## 退款到账时间\n退款在审核通过后 3-5 个工作日内原路退回。\n"
    "## 退货条件\n商品需在签收后 30 天内申请退货，包装完整不影响二次销售。\n"
    "## 退货运费\n质量问题商家承担运费，其他情况买家承担。\n"
)


def _print_audit() -> None:
    async def _q():
        eng, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
        async with sessions() as s:
            rows = (await s.scalars(select(AuditLogRow).order_by(AuditLogRow.id))).all()
            for r in rows[-10:]:
                print(f"    {r.action:14} {r.resource:10} -> {r.outcome}")
        await eng.dispose()

    asyncio.run(_q())


def main() -> None:
    app = create_app()
    with TestClient(app) as c:
        print("== 1. 健康检查 ==")
        print("   live :", c.get("/health/live").json())
        print("   ready:", c.get("/health/ready").json())

        print("\n== 2. 导入知识文档（ingest -> 分块 -> 向量 -> 入库）==")
        r = c.post(
            "/knowledge/documents", json={"document_id": "doc-returns", "title": "退货政策", "text": DOC_TEXT}
        )
        print("  ", r.json())

        print("\n== 3. 工具清单 ==")
        print("   " + ", ".join(t["ref"] for t in c.get("/tools").json()["tools"]))

        print("\n== 4. Agent 运行：Function Calling（calc.add）==")
        d = c.post("/agents/runs", json={"input": "12 + 30"}).json()
        print(f"   state={d['state']} steps={d['steps']} cost={d['cost']}")
        print(f"   answer: {d['answer']}")

        print("\n== 5. Agent 运行：RAG 检索（kb.search 工具）==")
        d = c.post("/agents/runs", json={"input": "知识库: 退款多久到账"}).json()
        print(f"   state={d['state']} steps={d['steps']} cost={d['cost']}")
        print(f"   answer: {d['answer']}")
        run_id = d["run_id"]

        print("\n== 6. RAG 那次的 Run Timeline（Step 时间线）==")
        trace = c.get(f"/agents/runs/{run_id}").json()
        for s in trace["steps"]:
            tools_called = [o["tool_ref"] for o in s["tool_calls"]]
            print(f"   step#{s['seq']} {s['state']:10} decision={s['decision']:9} tools={tools_called}")

        print("\n== 7. 直接混合检索（向量 + BM25 + RRF）==")
        hits = c.post("/knowledge/search", json={"query": "退货运费谁承担", "rerank_n": 3}).json()["hits"]
        for h in hits:
            print(f"   [{h['score']:.3f}] {h['document_id']}#{h['section']} :: {h['text'][:36]}")

        print("\n== 8. 直接工具执行（走权限/校验/审计全管线）==")
        t = c.post("/tools/calc.add/execute", json={"args": {"a": 5, "b": 7}}).json()
        print(f"   calc.add(5,7) = {t['data']}  (policy_id={t['decision']['policy_id']})")

        print("\n== 9. 审计日志（权限/执行全量落库）==")
        _print_audit()

    print("\n✅ 全链路演示完成：对话 -> 工具调用 -> RAG 检索 -> 引用 -> Trace -> 审计")


if __name__ == "__main__":
    main()
