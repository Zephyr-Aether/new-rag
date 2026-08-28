"""崩溃恢复：锁过期的非终态 Run => FAILED/RECOVERY_ABANDONED（§3.6 / §55.8）。"""

from app.agent.runtime.recovery import recover_stale_runs, resume_stale_runs
from app.storage.lock import RunLockService


async def test_stale_running_run_is_recovered(store):
    lock = RunLockService("")
    await store.create_run(
        run_id="stale1",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={},
        model_config={},
        input_json={},
    )
    recovered = await recover_stale_runs(store, lock)
    assert "stale1" in recovered
    run = await store.get_run("stale1")
    assert run["state"] == "FAILED"
    assert "RECOVERY_ABANDONED" in run["error_json"]


async def test_running_run_holding_lock_not_recovered(store):
    lock = RunLockService("")
    await store.create_run(
        run_id="live",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={},
        model_config={},
        input_json={},
    )
    assert await lock.acquire("live") is True
    recovered = await recover_stale_runs(store, lock)
    assert recovered == []
    run = await store.get_run("live")
    assert run["state"] == "RUNNING"
    await lock.release("live")


async def test_terminal_runs_not_touched(store):
    lock = RunLockService("")
    await store.create_run(
        run_id="done",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="COMPLETED",
        budget_json={},
        model_config={},
        input_json={},
    )
    recovered = await recover_stale_runs(store, lock)
    assert recovered == []
    assert (await store.get_run("done"))["state"] == "COMPLETED"


async def test_resume_stale_runs_resumes_with_checkpoint(store, lock, deps):
    """有检查点 + 锁过期 => 启动自动续跑至终态（§8.4）。"""
    await store.create_run(
        run_id="stale-cp",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={"max_steps": 5},
        model_config={"model": "mock-model", "system_prompt": ""},
        input_json={},
    )
    await store.set_checkpoint(
        "stale-cp",
        {
            "messages": [{"role": "user", "content": "hello"}],
            "steps": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "tool_calls": 0,
        },
    )
    resumed = await resume_stale_runs(store, lock, deps)
    assert "stale-cp" in resumed
    run = await store.get_run_full("stale-cp")
    assert run["state"] == "COMPLETED"


async def test_recover_skips_runs_with_checkpoint(store, lock):
    """有检查点的僵尸 run 不标 FAILED（交给续跑）。"""
    await store.create_run(
        run_id="cp-only",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        agent_version=1,
        session_id="s",
        state="RUNNING",
        budget_json={},
        model_config={},
        input_json={},
    )
    await store.set_checkpoint("cp-only", {"messages": [{"role": "user", "content": "x"}], "steps": 0})
    recovered = await recover_stale_runs(store, lock)
    assert "cp-only" not in recovered
    assert (await store.get_run("cp-only"))["state"] == "RUNNING"  # 未被打标
