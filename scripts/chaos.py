"""混沌工程运行（§80）：对真实应用注入故障，输出场景报告。

用法：make chaos 或 python scripts/chaos.py（SQLite + mock，无需外部依赖）
场景：模型持续失败 / 429 重试恢复 / 慢模型取消 / 工具失败优雅收敛 / DB 慢 / DB 故障。
"""

import asyncio
import os
import tempfile

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/chaos.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from app.agent.model.gateway import MockProvider, ModelGateway  # noqa: E402
from app.agent.runtime.budget import ExecutionBudget  # noqa: E402
from app.agent.runtime.cancel import CancelService  # noqa: E402
from app.agent.runtime.runtime import RuntimeDeps, execute_run  # noqa: E402
from app.agent.runtime.store import RunStore  # noqa: E402
from app.chaos import ChaosProvider, ChaosSessions, run_chaos  # noqa: E402
from app.common.contracts import RunInput  # noqa: E402
from app.common.errors import QueueFullError  # noqa: E402
from app.queue.queue import JobQueue  # noqa: E402
from app.queue.store import JobStore  # noqa: E402
from app.security.audit import AuditService  # noqa: E402
from app.security.policy import PolicyEngine  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402
from app.storage.lock import RunLockService  # noqa: E402
from app.tool.limiter import RateLimiter  # noqa: E402
from app.tool.registry import default_registry  # noqa: E402
from app.tool.runtime import ToolRuntime  # noqa: E402


async def main() -> int:
    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    store = RunStore(sessions)
    reg = default_registry()
    tr = ToolRuntime(
        registry=reg,
        policy=PolicyEngine(sessions),
        audit=AuditService(sessions),
        limiter=RateLimiter(""),
        idem=store,
    )
    deps = RuntimeDeps(
        store=store,
        registry=reg,
        gateway=ModelGateway(Settings(database_url=os.environ["APP_DATABASE_URL"], llm_provider="mock")),
        lock=RunLockService(""),
        cancel=CancelService(""),
        tool_runtime=tr,
    )

    async def scenario_model_fails():
        deps.gateway.provider = ChaosProvider(MockProvider(), fail_count=1000)
        r = await execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
            deps,
            run_id="chaos-1",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
        assert r.state == "FAILED" and r.error and r.error["code"] == "MODEL_ERROR", "应优雅失败而非悬挂"

    async def scenario_429_recovers():
        deps.gateway.provider = ChaosProvider(MockProvider(), fail_count=1, fail_429=True)
        r = await execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
            deps,
            run_id="chaos-2",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
        assert r.state == "COMPLETED", "429 应被重试吸收后完成"

    async def scenario_db_slow():
        deps.store = RunStore(ChaosSessions(sessions, delay_s=0.03))
        r = await execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
            deps,
            run_id="chaos-db-slow",
            agent_version=1,
            system_prompt="",
            budget=ExecutionBudget(max_steps=5),
        )
        assert r.state == "COMPLETED", "慢 DB 下应仍完成而非悬挂"

    async def scenario_db_failure():
        deps.store = RunStore(ChaosSessions(sessions, fail_count=1))
        try:
            await execute_run(
                RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
                deps,
                run_id="chaos-db-fail",
                agent_version=1,
                system_prompt="",
                budget=ExecutionBudget(max_steps=5),
            )
            raise AssertionError("DB 故障应快速抛错而非悬挂")
        except RuntimeError:
            pass  # 注入的 DB 失败被抛出 => 快速失败

    async def scenario_queue_flood():
        # §30.2 队列洪峰：容量 3，灌 10 个 => 高水位触发拒绝（优雅 QueueFullError，不挂）
        q = JobQueue(JobStore(sessions), capacity=3)
        accepted = 0
        rejected = 0
        for _ in range(10):
            try:
                await q.enqueue(tenant_id="t", job_type="flood", payload={}, priority=2)
                accepted += 1
            except QueueFullError:
                rejected += 1
        assert accepted <= 3 and rejected > 0, "洪峰应触发水位拒绝（QueueFullError）"

    print("== 混沌工程报告 ==")
    reports = [
        await run_chaos("模型持续失败 -> 优雅 FAILED", scenario_model_fails),
        await run_chaos("429 注入 -> 重试恢复 COMPLETED", scenario_429_recovers),
        await run_chaos("DB 慢注入 -> 仍完成不悬挂", scenario_db_slow),
        await run_chaos("DB 故障注入 -> 快速抛错", scenario_db_failure),
        await run_chaos("队列洪峰 -> 水位拒绝不悬挂", scenario_queue_flood),
    ]
    failed = 0
    for report in reports:
        print(
            f"  [{report['status']}] {report['name']}  ({report['elapsed_s']}s)"
            + (f"  error={report['error']}" if report["error"] else "")
        )
        failed += report["status"] != "passed"
    await engine.dispose()
    print(f"== 结果：{'PASS' if failed == 0 else f'{failed} FAILED'} ==")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
