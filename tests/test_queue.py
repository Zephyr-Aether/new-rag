"""异步任务队列（§9）：优先级 / worker / 重试 / DLQ / agent_run 接入 / 水位限流 / 分池。"""

import pytest

from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.runtime import execute_run
from app.common.contracts import RunInput
from app.common.errors import QueueFullError
from app.queue.queue import JobQueue
from app.queue.store import JobStore


async def _echo(payload):
    return None


async def test_echo_job_processed(sessions):
    q = JobQueue(JobStore(sessions), handlers={"echo": _echo})
    job_id = await q.enqueue(tenant_id="t", job_type="echo", payload={"x": 1})
    assert await q.process_once() == job_id
    row = await q.store.get(job_id)
    assert row["state"] == "SUCCEEDED"


async def test_retry_then_dead_letter(sessions):
    async def _always_fail(payload):
        raise RuntimeError("boom")

    q = JobQueue(JobStore(sessions), handlers={"fail": _always_fail})
    job_id = await q.enqueue(tenant_id="t", job_type="fail", payload={}, max_attempts=2)
    await q.process_once()  # attempt1 -> QUEUED（重试）
    await q.process_once()  # attempt2 -> DEAD_LETTER
    row = await q.store.get(job_id)
    assert row["state"] == "DEAD_LETTER"
    assert row["attempts"] == 2


async def test_priority_order(sessions):
    q = JobQueue(JobStore(sessions), handlers={"rec": _echo})
    processed: list[str] = []

    async def _record(payload):
        processed.append(payload["tag"])

    q.register("rec", _record)
    await q.enqueue(tenant_id="t", job_type="rec", payload={"tag": "p3"}, priority=3)
    await q.enqueue(tenant_id="t", job_type="rec", payload={"tag": "p0"}, priority=0)
    await q.enqueue(tenant_id="t", job_type="rec", payload={"tag": "p1"}, priority=1)
    await q.drain()
    assert processed == ["p0", "p1", "p3"]


async def test_agent_run_via_queue(deps):
    q = JobQueue(JobStore(deps.store.sessions))

    async def _agent_run(payload):
        await execute_run(
            RunInput(**payload["run_input"]),
            deps,
            run_id=payload["run_id"],
            agent_version=payload["agent_version"],
            system_prompt=payload["system_prompt"],
            budget=ExecutionBudget(**payload["budget"]),
        )

    q.register("agent_run", _agent_run)
    await q.enqueue(
        tenant_id="t",
        job_type="agent_run",
        payload={
            "run_input": {
                "tenant_id": "t",
                "user_id": "u",
                "agent_id": "a",
                "session_id": "s",
                "text": "12 + 30",
                "model": None,
            },
            "run_id": "r-q",
            "agent_version": 1,
            "system_prompt": "",
            "budget": {"max_steps": 5},
        },
    )
    await q.process_once()
    run = await deps.store.get_run("r-q")
    assert run["state"] == "COMPLETED"


async def test_admission_control_rejects_low_priority(sessions):
    """§9.3 水位限流：>70% 拒低优，70-85% 区间高优可入。"""
    q = JobQueue(JobStore(sessions), handlers={"echo": _echo}, capacity=10)
    for _ in range(7):  # 水位 -> 0.7
        await q.enqueue(tenant_id="t", job_type="echo", payload={})
    with pytest.raises(QueueFullError):
        await q.enqueue(tenant_id="t", job_type="echo", payload={}, priority=2)
    await q.enqueue(tenant_id="t", job_type="echo", payload={}, priority=0)  # 高优可入


async def test_backpressure_flag(sessions):
    q = JobQueue(JobStore(sessions), capacity=20)
    for _ in range(18):  # 水位 0.9 > 0.85（priority=0 在 <0.95 区间可入）
        await q.enqueue(tenant_id="t", job_type="echo", payload={}, priority=0)
    assert q.is_backpressured()


async def test_per_type_pools_isolate(sessions):
    """§55 按任务类型分 Worker Pool：只处理指定类型，互不干扰。"""
    q = JobQueue(JobStore(sessions), handlers={"echo": _echo, "agent_run": _echo})
    await q.enqueue(tenant_id="t", job_type="echo", payload={"tag": "e"})
    await q.enqueue(tenant_id="t", job_type="agent_run", payload={"tag": "a"})
    jid = await q.process_once("agent_run")
    assert (await q.store.get(jid))["payload"]["tag"] == "a"
    assert q.pending() == 1  # echo 未被动
    await q.process_once("echo")
    assert q.pending() == 0


async def test_old_payload_schema_migrated(deps):
    """§57 版本兼容：旧版 payload（缺 schema_version/新字段）仍被正确处理。"""
    from app.queue.schema import migrate_agent_run_payload

    q = JobQueue(JobStore(deps.store.sessions))

    async def _agent_run(raw):
        payload = migrate_agent_run_payload(raw)
        assert payload["schema_version"] == 1
        assert payload["run_input"]["model"] is None  # 旧字段被补默认
        await execute_run(
            RunInput(**payload["run_input"]),
            deps,
            run_id=payload["run_id"],
            agent_version=payload["agent_version"],
            system_prompt=payload["system_prompt"],
            budget=ExecutionBudget(**payload["budget"]),
        )

    q.register("agent_run", _agent_run)
    old = {
        "run_input": {
            "tenant_id": "t",
            "user_id": "u",
            "agent_id": "a",
            "session_id": "s",
            "text": "12 + 30",
        },
        "run_id": "r-mig",
        "agent_version": 1,
        "system_prompt": "",
        "budget": {"max_steps": 5},
    }
    await q.enqueue(tenant_id="t", job_type="agent_run", payload=old)
    await q.process_once()
    run = await deps.store.get_run("r-mig")
    assert run["state"] == "COMPLETED"


async def test_worker_lease_and_zombie_recovery(sessions):
    """§55 Worker 租约/心跳：租约过期仍 RUNNING => Zombie 重新入队。"""
    from datetime import UTC, datetime, timedelta

    store = JobStore(sessions)
    q = JobQueue(store, handlers={"echo": _echo})
    job_id = await q.enqueue(tenant_id="t", job_type="echo", payload={})
    assert await store.claim(job_id, lease_s=30)
    row = await store.get(job_id)
    assert row["state"] == "RUNNING" and row["lease_until"] is not None
    # 心跳续租
    await store.heartbeat(job_id, lease_s=30)
    assert (await store.get(job_id))["lease_until"] >= row["lease_until"]
    # Zombie：租约过期 => 重新入队（QUEUED）
    now = datetime.now(UTC) + timedelta(seconds=60)
    expired = await store.recover_zombies(now=now)
    assert job_id in expired
    assert (await store.get(job_id))["state"] == "QUEUED"
    # 重新可被认领
    assert await store.claim(job_id, lease_s=30)
    assert (await store.get(job_id))["state"] == "RUNNING"


async def test_single_flight_dedupes_concurrent(sessions):
    """§11 单飞：同 dedupe_key 且未终态的任务合并为同一 job，只执行一次。"""
    calls = []

    async def _record(payload):
        calls.append(payload["n"])

    q = JobQueue(JobStore(sessions), handlers={"sf": _record})
    j1 = await q.enqueue(tenant_id="t", job_type="sf", payload={"n": 1}, dedupe_key="dup-1")
    j2 = await q.enqueue(tenant_id="t", job_type="sf", payload={"n": 2}, dedupe_key="dup-1")
    assert j1 == j2  # 合并：并发重复任务共享一次执行
    await q.process_once("sf")
    assert calls == [1]  # 只执行第一次入队的 payload


async def test_single_flight_different_key_creates_new(sessions):
    q = JobQueue(JobStore(sessions), handlers={"sf": _echo})
    j1 = await q.enqueue(tenant_id="t", job_type="sf", payload={}, dedupe_key="dup-a")
    j2 = await q.enqueue(tenant_id="t", job_type="sf", payload={}, dedupe_key="dup-b")
    assert j1 != j2  # 不同键 => 各自独立任务


async def test_single_flight_after_terminal_creates_new(sessions):
    q = JobQueue(JobStore(sessions), handlers={"sf": _echo})
    j1 = await q.enqueue(tenant_id="t", job_type="sf", payload={}, dedupe_key="dup-2")
    await q.process_once("sf")  # 完成 => SUCCEEDED（终态）
    assert (await q.store.get(j1))["state"] == "SUCCEEDED"
    j2 = await q.enqueue(tenant_id="t", job_type="sf", payload={}, dedupe_key="dup-2")
    assert j2 != j1  # 终态后同键 => 新建（可再次执行）


async def test_dlq_requeue(sessions):
    """DLQ 重放：死信任务重置后重新入堆，可再次执行成功。"""

    async def _always_fail(payload):
        raise RuntimeError("boom")

    q = JobQueue(JobStore(sessions), handlers={"fail": _always_fail})
    job_id = await q.enqueue(tenant_id="t", job_type="fail", payload={}, max_attempts=1)
    await q.process_once("fail")  # attempt1 -> DEAD_LETTER
    assert (await q.store.get(job_id))["state"] == "DEAD_LETTER"

    res = await q.requeue(job_id)
    assert res["state"] == "CREATED" and res.get("skipped") is False
    assert (await q.store.get(job_id))["attempts"] == 0  # 计数清零

    q.handlers["fail"] = _echo  # 换健康 handler
    assert await q.process_once("fail") == job_id
    assert (await q.store.get(job_id))["state"] == "SUCCEEDED"


async def test_job_cancel(sessions):
    """§11.2 取消排队任务 => CANCELLED（且从堆中移除）。"""
    q = JobQueue(JobStore(sessions), handlers={})
    job_id = await q.enqueue(tenant_id="t", job_type="echo", payload={})
    res = await q.cancel(job_id)
    assert res["state"] == "CANCELLED"
    assert (await q.store.get(job_id))["state"] == "CANCELLED"
    assert q.pending() == 0  # 已从堆中移除


async def test_job_expire_old(sessions):
    """§11.2 超龄 QUEUED => EXPIRED（清理堆积僵尸任务）。"""
    q = JobQueue(JobStore(sessions), handlers={})
    await q.enqueue(tenant_id="t", job_type="echo", payload={})
    res = await q.expire_old(ttl_s=0)
    assert res["count"] == 1
    assert (await q.store.get(res["expired"][0]))["state"] == "EXPIRED"


async def test_cross_instance_claim_queued(sessions):
    """HA 多实例：另一实例入队的任务（本地堆为空）能被本实例从共享库认领处理。"""
    store = JobStore(sessions)
    q = JobQueue(store, handlers={"echo": _echo})
    # 模拟另一实例入队：直接写库，不 push 本地堆
    job_id = await store.create(
        tenant_id="t", job_type="echo", payload={"text": "ha"}, priority=2, max_attempts=2
    )
    assert q.pending() == 0  # 本地堆确实为空
    # 本实例轮询共享库认领
    claimed = await store.claim_queued("echo", lease_s=30)
    assert claimed == job_id
    await q._process_job(claimed)
    row = await store.get(job_id)
    assert row["state"] == "SUCCEEDED"
