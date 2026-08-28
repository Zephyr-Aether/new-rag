"""崩溃恢复（§3.6 / §8.4 / §55.8）。

策略：
- 有检查点的僵尸 run（锁过期的非终态）=> 启动时自动续跑（resume_stale_runs）。
- 无检查点的僵尸 run => 标记 FAILED/RECOVERY_ABANDONED（无可续内容，防僵尸 RUNNING）。
工具幂等保证重放不重复副作用（至多一次）。
"""

import time

from app.agent.runtime.runtime import RuntimeDeps, resume_run
from app.agent.runtime.store import RunStore
from app.storage.lock import RunLockService

STALE_STATES = ["PLANNING", "RUNNING", "WAITING_TOOL"]


async def _stale_run_ids(store: RunStore, lock: RunLockService, now: float) -> list[dict]:
    rows = await store.list_runs_in_states(STALE_STATES)
    return [r for r in rows if await lock.is_expired(r["run_id"], now)]


async def recover_stale_runs(
    store: RunStore, lock: RunLockService, *, now_ts: float | None = None
) -> list[str]:
    """回收无检查点的僵尸 run（标 FAILED/RECOVERY_ABANDONED）；有检查点的跳过交给续跑。"""
    now = now_ts if now_ts is not None else time.time()
    recovered: list[str] = []
    for row in await _stale_run_ids(store, lock, now):
        full = await store.get_run_full(row["run_id"])
        if full and full.get("checkpoint_json"):
            continue  # 有检查点：交给 resume_stale_runs
        # §3.3 CAS：版本被并发改动（另一执行者还活着在写）则放弃回收
        if full is not None and not await store.set_state_cas(row["run_id"], "FAILED", full["version"]):
            continue
        await store.finish_run(
            run_id=row["run_id"],
            state="FAILED",
            output_json=None,
            error_json={
                "code": "RECOVERY_ABANDONED",
                "message": "run abandoned: executor lost lock (crash/timeout), no checkpoint",
            },
            tokens_in=0,
            tokens_out=0,
            cost=0.0,
        )
        recovered.append(row["run_id"])
    return recovered


async def resume_stale_runs(
    store: RunStore, lock: RunLockService, deps: RuntimeDeps, *, now_ts: float | None = None
) -> list[str]:
    """启动自动续跑：锁过期的非终态 Run 且有检查点 => resume（LLM 重做、工具幂等）。"""
    now = now_ts if now_ts is not None else time.time()
    resumed: list[str] = []
    for row in await _stale_run_ids(store, lock, now):
        full = await store.get_run_full(row["run_id"])
        if not full or not full.get("checkpoint_json"):
            continue
        try:
            await resume_run(row["run_id"], deps)
            resumed.append(row["run_id"])
        except Exception as exc:  # 单个 run 续跑失败不影响其他 run
            await store.finish_run(
                run_id=row["run_id"],
                state="FAILED",
                output_json=None,
                error_json={"code": "RESUME_FAILED", "message": str(exc)},
                tokens_in=0,
                tokens_out=0,
                cost=0.0,
            )
    return resumed
