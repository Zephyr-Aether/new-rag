"""§30.1 Load 压测：进程内跑 N 个 run，测 QPS / p50/p95/p99/max 延迟。

用法：python scripts/bench_load.py [runs=200]
"""

import asyncio
import os
import sys
import tempfile
import time

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/load.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from app.agent.model.gateway import ModelGateway  # noqa: E402
from app.agent.runtime.budget import ExecutionBudget  # noqa: E402
from app.agent.runtime.cancel import CancelService  # noqa: E402
from app.agent.runtime.runtime import RuntimeDeps, execute_run  # noqa: E402
from app.agent.runtime.store import RunStore  # noqa: E402
from app.common.contracts import RunInput  # noqa: E402
from app.security.audit import AuditService  # noqa: E402
from app.security.policy import PolicyEngine  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402
from app.storage.lock import RunLockService  # noqa: E402
from app.tool.limiter import RateLimiter  # noqa: E402
from app.tool.registry import default_registry  # noqa: E402
from app.tool.runtime import ToolRuntime  # noqa: E402


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    engine, sessions = create_engine_and_sessions(os.environ["APP_DATABASE_URL"])
    await create_all(engine)
    store = RunStore(sessions)
    reg = default_registry()
    deps = RuntimeDeps(
        store=store,
        registry=reg,
        gateway=ModelGateway(Settings(database_url=os.environ["APP_DATABASE_URL"], llm_provider="mock")),
        lock=RunLockService(""),
        cancel=CancelService(""),
        tool_runtime=ToolRuntime(
            registry=reg,
            policy=PolicyEngine(sessions),
            audit=AuditService(sessions),
            limiter=RateLimiter(""),
            idem=store,
        ),
    )
    budget = ExecutionBudget(max_steps=5)
    latencies: list[float] = []
    start = time.monotonic()
    for i in range(n):
        t0 = time.monotonic()
        await execute_run(
            RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
            deps,
            run_id=f"load-{i}",
            agent_version=1,
            system_prompt="",
            budget=budget,
        )
        latencies.append((time.monotonic() - t0) * 1000)
    total = time.monotonic() - start
    latencies.sort()

    def pct(p: float) -> float:
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))]

    print(f"== Load 压测: {n} runs / {total:.2f}s => {n / total:.1f} QPS")
    print(
        f"  latency p50={pct(0.5):.1f}ms p95={pct(0.95):.1f}ms "
        f"p99={pct(0.99):.1f}ms max={latencies[-1]:.1f}ms"
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
