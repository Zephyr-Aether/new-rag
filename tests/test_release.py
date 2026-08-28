"""灰发布 / 回滚 / Release Contract / Canary 指标 / 版本冻结（§21 §22 §57 §58）。"""

import json
from datetime import UTC

import pytest
from sqlalchemy import text

from app.agent.runtime.store import RunStore
from app.common.errors import AgentError
from app.release.service import ReleaseService
from app.settings import Settings
from app.storage.models import AgentRow, AgentVersionRow
from app.tool.registry import default_registry


def _release(sessions) -> ReleaseService:
    return ReleaseService(
        sessions,
        registry=default_registry(),
        settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"),
    )


async def _seed(sessions, agent_id: str, versions: list[tuple[int, str, str]]) -> None:
    async with sessions() as s:
        for version, status, config in versions:
            s.add(
                AgentVersionRow(
                    id=f"av-{agent_id}-{version}",
                    tenant_id="t",
                    agent_id=agent_id,
                    version=version,
                    status=status,
                    system_prompt=f"prompt-{version}",
                    config_json=config,
                )
            )
        await s.commit()


async def test_publish_and_resolve(sessions):
    svc = ReleaseService(sessions)
    await _seed(sessions, "ag1", [(1, "DRAFT", "{}"), (2, "DRAFT", "{}")])
    await svc.publish(tenant_id="t", agent_id="ag1", version=1)
    await svc.publish(tenant_id="t", agent_id="ag1", version=2)
    assert (await svc.resolve(tenant_id="t", agent_id="ag1", user_id="u"))["version"] == 2


async def test_rollback_full_flow(sessions):
    """§21 Rollback 自动切换：发布 v2 → resolve v2 → 回滚 → resolve v1 → 再切回 v2。"""
    svc = ReleaseService(sessions)
    await _seed(sessions, "agR", [(1, "DRAFT", "{}"), (2, "DRAFT", "{}")])
    await svc.publish(tenant_id="t", agent_id="agR", version=1)
    await svc.publish(tenant_id="t", agent_id="agR", version=2)
    assert (await svc.resolve(tenant_id="t", agent_id="agR", user_id="u"))["version"] == 2
    # 回滚到 v1：resolve 自动切回
    await svc.rollback(tenant_id="t", agent_id="agR", to_version=1)
    assert (await svc.resolve(tenant_id="t", agent_id="agR", user_id="u"))["version"] == 1
    # 再发布 v2：切回
    await svc.publish(tenant_id="t", agent_id="agR", version=2)
    assert (await svc.resolve(tenant_id="t", agent_id="agR", user_id="u"))["version"] == 2


async def test_rollback_from_gray(sessions):
    """§21 灰度版本出问题：回滚到上一 ACTIVE（GRAY 被降级）。"""
    svc = ReleaseService(sessions)
    await _seed(sessions, "agG", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    await svc.gray(tenant_id="t", agent_id="agG", version=2, percentage=100)
    assert (await svc.resolve(tenant_id="t", agent_id="agG", user_id="u"))["version"] == 2
    await svc.rollback(tenant_id="t", agent_id="agG", to_version=1)
    assert (await svc.resolve(tenant_id="t", agent_id="agG", user_id="u"))["version"] == 1


async def test_canary_auto_stop_on_metrics(sessions):
    """§57 Canary 自动停发布（指标驱动）：错误率超阈值 => 自动 halt 灰度，回落 ACTIVE。"""
    from app.agent.runtime.store import RunStore

    svc = ReleaseService(sessions)
    await _seed(sessions, "agC", [(1, "DRAFT", "{}"), (2, "DRAFT", "{}")])
    await svc.publish(tenant_id="t", agent_id="agC", version=1)
    await svc.gray(tenant_id="t", agent_id="agC", version=2, percentage=100)
    assert (await svc.resolve(tenant_id="t", agent_id="agC", user_id="u"))["version"] == 2

    store = RunStore(sessions)
    mc = {"model": "m", "release_status": "GRAY", "release_version": 2}
    for i in range(5):
        await store.create_run(
            run_id=f"rc{i}",
            tenant_id="t",
            user_id="u",
            agent_id="agC",
            agent_version=2,
            session_id="s",
            state="COMPLETED",
            budget_json={},
            model_config=mc,
            input_json={"text": "q"},
        )
        await store.finish_run(
            run_id=f"rc{i}",
            state="COMPLETED",
            output_json={"answer": "x"},
            error_json={"code": "MODEL_ERROR"} if i < 2 else None,
            tokens_in=1,
            tokens_out=1,
            cost=0.01,
        )

    check = await svc.canary_check(tenant_id="t", agent_id="agC", version=2, min_runs=5, error_threshold=0.1)
    assert check["action"] == "stop" and check["halted"] is True
    assert check["rolled_back_to"] == 1  # §57 自动回滚到上一 ACTIVE
    assert (await svc.resolve(tenant_id="t", agent_id="agC", user_id="u"))["version"] == 1  # 回落 ACTIVE


async def test_gray_hit(sessions):
    svc = ReleaseService(sessions)
    await _seed(sessions, "ag2", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 0}')])
    await svc.gray(tenant_id="t", agent_id="ag2", version=2, percentage=100)
    resolved = await svc.resolve(tenant_id="t", agent_id="ag2", user_id="any")
    assert resolved["version"] == 2 and resolved["status"] == "GRAY"


async def test_gray_zero_no_hit_falls_back(sessions):
    svc = ReleaseService(sessions)
    await _seed(sessions, "ag3", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 0}')])
    resolved = await svc.resolve(tenant_id="t", agent_id="ag3", user_id="any")
    assert resolved["version"] == 1  # 0% 永不命中灰度 => 回落 ACTIVE


async def test_rollback(sessions):
    svc = ReleaseService(sessions)
    await _seed(sessions, "ag4", [(1, "DISABLED", "{}"), (2, "ACTIVE", "{}")])
    await svc.rollback(tenant_id="t", agent_id="ag4", to_version=1)
    assert (await svc.resolve(tenant_id="t", agent_id="ag4", user_id="u"))["version"] == 1


async def _seed_agent(sessions, agent_id: str) -> None:
    async with sessions() as s:
        s.add(AgentRow(id=agent_id, tenant_id="t", owner_id="u", name="a", slug="a", status="ACTIVE"))
        await s.commit()


async def test_create_version_auto_increments(sessions):
    svc = ReleaseService(sessions)
    await _seed_agent(sessions, "agN")
    v1 = await svc.create_version(tenant_id="t", agent_id="agN", system_prompt="p1")
    assert v1["version"] == 1 and v1["status"] == "DRAFT"
    v2 = await svc.create_version(tenant_id="t", agent_id="agN", system_prompt="p2", model="m2")
    assert v2["version"] == 2 and v2["status"] == "DRAFT"


async def test_full_lifecycle_create_publish_gray(sessions):
    """§22 版本只增不改：create v1 → publish → create v2 → gray 100% → resolve 命中 v2。"""
    svc = ReleaseService(sessions)
    await _seed_agent(sessions, "agL")
    v1 = await svc.create_version(tenant_id="t", agent_id="agL", system_prompt="p1")
    v2 = await svc.create_version(tenant_id="t", agent_id="agL", system_prompt="p2", model="m2")
    await svc.publish(tenant_id="t", agent_id="agL", version=v1["version"])
    await svc.gray(tenant_id="t", agent_id="agL", version=v2["version"], percentage=100)
    resolved = await svc.resolve(tenant_id="t", agent_id="agL", user_id="any")
    assert resolved["version"] == 2 and resolved["status"] == "GRAY"
    assert resolved["system_prompt"] == "p2" and resolved["model"] == "m2"


async def test_list_versions_desc(sessions):
    svc = ReleaseService(sessions)
    await _seed_agent(sessions, "agV")
    await svc.create_version(tenant_id="t", agent_id="agV", system_prompt="p1")
    await svc.create_version(tenant_id="t", agent_id="agV", system_prompt="p2", config={"k": 1})
    versions = await svc.list_versions(tenant_id="t", agent_id="agV")
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["status"] == "DRAFT"
    assert versions[0]["config"] == {"k": 1}
    assert versions[0]["created_at"]  # server_default 已落库


async def test_create_version_agent_not_found(sessions):
    svc = ReleaseService(sessions)
    with pytest.raises(AgentError) as excinfo:
        await svc.create_version(tenant_id="t", agent_id="nope", system_prompt="p")
    assert excinfo.value.code == "AGENT_NOT_FOUND"


async def _make_runs(sessions, agent_id: str, count: int, errors: int = 0) -> None:
    store = RunStore(sessions)
    for i in range(count):
        run_id = f"ct-{i}"
        await store.create_run(
            run_id=run_id,
            tenant_id="t",
            user_id="u",
            agent_id=agent_id,
            agent_version=1,
            session_id="s",
            state="COMPLETED",
            budget_json={},
            model_config={},
            input_json={"text": "q"},
        )
        await store.finish_run(
            run_id=run_id,
            state="COMPLETED",
            output_json={"answer": "x"},
            error_json={"code": "MODEL_ERROR"} if i < errors else None,
            tokens_in=1,
            tokens_out=1,
            cost=0.01,
        )


async def test_contract_check_healthy_report(sessions):
    """§58 健康发布：10 项齐全、无 fail、仅平台级三项走人工签核。"""
    svc = _release(sessions)
    await _seed_agent(sessions, "agCc")
    await svc.create_version(tenant_id="t", agent_id="agCc", system_prompt="p1")
    await svc.publish(tenant_id="t", agent_id="agCc", version=1)
    await _make_runs(sessions, "agCc", count=12, errors=1)  # 错误率 8% < 20%
    report = await svc.contract_check(tenant_id="t", agent_id="agCc", version=1)
    assert len(report["checks"]) == 10
    assert report["blocked"] is False
    assert "fail" not in {c["status"] for c in report["checks"]}
    prompt = next(c for c in report["checks"] if c["id"] == "prompt")
    assert prompt["status"] == "pass"
    assert report["needs_manual"] == ["DB Compatibility", "Memory Compatibility", "Trace Compatibility"]


async def test_publish_gate_blocks_unknown_tool(sessions):
    """§58 门禁：声明未注册工具 => publish 抛 RELEASE_CONTRACT_FAILED。"""
    svc = _release(sessions)
    await _seed_agent(sessions, "agT")
    await svc.create_version(tenant_id="t", agent_id="agT", system_prompt="p1")
    await svc.create_version(
        tenant_id="t", agent_id="agT", system_prompt="p2", config={"tools": ["calc.add", "ghost.tool"]}
    )
    await svc.publish(tenant_id="t", agent_id="agT", version=1)  # v1 无 fail，warn 不阻断
    with pytest.raises(AgentError) as excinfo:
        await svc.publish(tenant_id="t", agent_id="agT", version=2)
    assert excinfo.value.code == "RELEASE_CONTRACT_FAILED"
    assert any(c["id"] == "tool" for c in excinfo.value.detail["failures"])


async def test_publish_force_bypasses_contract(sessions):
    svc = _release(sessions)
    await _seed_agent(sessions, "agF")
    await svc.create_version(tenant_id="t", agent_id="agF", system_prompt="p1")
    await svc.create_version(
        tenant_id="t", agent_id="agF", system_prompt="p2", config={"tools": ["ghost.tool"]}
    )
    await svc.publish(tenant_id="t", agent_id="agF", version=1)
    r = await svc.publish(tenant_id="t", agent_id="agF", version=2, force=True)
    assert r["status"] == "ACTIVE" and r["version"] == 2


async def test_publish_gate_blocks_config_key_removed(sessions):
    """§22 配置只增不改：键被移除 => config 检查 fail 阻断。"""
    svc = _release(sessions)
    await _seed_agent(sessions, "agCfg")
    await svc.create_version(tenant_id="t", agent_id="agCfg", system_prompt="p1", config={"a": 1, "b": 2})
    await svc.publish(tenant_id="t", agent_id="agCfg", version=1)
    await svc.create_version(tenant_id="t", agent_id="agCfg", system_prompt="p2", config={"a": 1})
    with pytest.raises(AgentError) as excinfo:
        await svc.publish(tenant_id="t", agent_id="agCfg", version=2)
    assert any(c["id"] == "config" for c in excinfo.value.detail["failures"])


async def test_contract_check_model_unknown(sessions):
    svc = _release(sessions)
    await _seed_agent(sessions, "agM")
    await svc.create_version(tenant_id="t", agent_id="agM", system_prompt="p1")
    await svc.create_version(tenant_id="t", agent_id="agM", system_prompt="p2", model="unknown-model")
    report = await svc.contract_check(tenant_id="t", agent_id="agM", version=2)
    model = next(c for c in report["checks"] if c["id"] == "model")
    assert model["status"] == "fail"
    assert report["blocked"] is True


async def _seed_gray_runs(sessions, agent_id: str, count: int) -> list[str]:
    """给灰度版本 v2 造 count 个成功 run，返回 run_ids（可再补 tool_calls/延迟）。"""
    store = RunStore(sessions)
    mc = {"model": "m", "release_status": "GRAY", "release_version": 2}
    run_ids: list[str] = []
    for i in range(count):
        run_id = f"g-{i}"
        await store.create_run(
            run_id=run_id,
            tenant_id="t",
            user_id="u",
            agent_id=agent_id,
            agent_version=2,
            session_id="s",
            state="COMPLETED",
            budget_json={},
            model_config=mc,
            input_json={"text": "q"},
        )
        await store.finish_run(
            run_id=run_id,
            state="COMPLETED",
            output_json={"answer": "x"},
            error_json=None,
            tokens_in=1,
            tokens_out=1,
            cost=0.01,
        )
        run_ids.append(run_id)
    return run_ids


async def test_canary_stop_on_latency(sessions):
    """§57.6 Latency 恶化 => 停止灰度。"""
    svc = ReleaseService(sessions)
    await _seed(sessions, "agLt", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    await _seed_gray_runs(sessions, "agLt", 5)
    # 提前 started_at 模拟高延迟（60s > 30s 阈值）
    from datetime import datetime, timedelta

    back = datetime.now(UTC) - timedelta(seconds=60)
    async with sessions() as s:
        await s.execute(
            text("UPDATE agent_runs SET started_at = :t WHERE agent_id = :a"), {"t": back, "a": "agLt"}
        )
        await s.commit()
    check = await svc.canary_check(tenant_id="t", agent_id="agLt", version=2, min_runs=5)
    assert check["action"] == "stop"
    assert check["metrics"]["avg_latency_s"] > 30


async def test_canary_stop_on_tool_failure(sessions):
    """§57.6 Tool Success 恶化（成功率 0%）=> 停止灰度。"""
    svc = ReleaseService(sessions)
    await _seed(sessions, "agTs", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    store = RunStore(sessions)
    run_ids = await _seed_gray_runs(sessions, "agTs", 5)
    for i, run_id in enumerate(run_ids):
        await store.insert_tool_call(
            call_id=f"tc-{i}", run_id=run_id, tenant_id="t", user_id="u", tool_ref="calc.add", args_json="{}"
        )
        await store.finalize_tool_call(
            call_id=f"tc-{i}", result_json={"ok": False}, status="FAILED", error_code="X", latency_ms=5
        )
    check = await svc.canary_check(tenant_id="t", agent_id="agTs", version=2, min_runs=5)
    assert check["action"] == "stop"
    assert check["metrics"]["tool_success_rate"] == 0.0


async def test_canary_stop_on_low_rag_recall(sessions):
    """§57.6 RAG Recall 恶化（kb.search 全空命中）=> 停止灰度。"""
    svc = ReleaseService(sessions)
    await _seed(sessions, "agRr", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    store = RunStore(sessions)
    run_ids = await _seed_gray_runs(sessions, "agRr", 5)
    for i, run_id in enumerate(run_ids):
        await store.insert_tool_call(
            call_id=f"kb-{i}", run_id=run_id, tenant_id="t", user_id="u", tool_ref="kb.search", args_json="{}"
        )
        await store.finalize_tool_call(
            call_id=f"kb-{i}",
            result_json={"ok": True, "data": []},
            status="SUCCEEDED",
            error_code=None,
            latency_ms=5,
        )
    check = await svc.canary_check(tenant_id="t", agent_id="agRr", version=2, min_runs=5)
    assert check["action"] == "stop"
    assert check["metrics"]["rag_recall"] == 0.0


async def test_canary_continue_when_metrics_healthy(sessions):
    svc = ReleaseService(sessions)
    await _seed(sessions, "agH", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    store = RunStore(sessions)
    run_ids = await _seed_gray_runs(sessions, "agH", 5)
    for i, run_id in enumerate(run_ids):
        await store.insert_tool_call(
            call_id=f"kb-{i}", run_id=run_id, tenant_id="t", user_id="u", tool_ref="kb.search", args_json="{}"
        )
        await store.finalize_tool_call(
            call_id=f"kb-{i}",
            result_json={"ok": True, "data": [{"chunk_id": "c1"}]},
            status="SUCCEEDED",
            error_code=None,
            latency_ms=5,
        )
    check = await svc.canary_check(tenant_id="t", agent_id="agH", version=2, min_runs=5)
    assert check["action"] == "continue"
    assert check["metrics"]["rag_recall"] == 1.0


async def test_build_frozen_snapshot(sessions):
    """§22.1 版本冻结快照：tools（registry 版本，未注册标 unknown）+ knowledge_version。"""
    from app.agent.api.runs import _build_frozen

    svc = ReleaseService(sessions)
    await _seed_agent(sessions, "agBf")
    await svc.create_version(
        tenant_id="t",
        agent_id="agBf",
        system_prompt="p1",
        config={"tools": ["calc.add", "nope.tool"], "knowledge_version": "7"},
    )

    class _State:
        def __init__(self):
            self.sessions = sessions
            self.registry = default_registry()

    frozen = await _build_frozen(_State(), "t", "agBf", 1, "GRAY")
    assert frozen["knowledge_version"] == "7"
    assert frozen["tools"] == {"calc.add": "1", "nope.tool": "unknown"}
    assert frozen["agent_version"] == 1 and frozen["release_status"] == "GRAY"


async def test_run_freezes_versions(deps):
    """§22.1 运行中绝不漂移：execute_run 把冻结版本集落 model_config。"""
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.runtime import execute_run
    from app.common.contracts import RunInput

    frozen = {
        "agent_version": 2,
        "release_status": "GRAY",
        "tools": {"calc.add": "1"},
        "knowledge_version": "7",
    }
    result = await execute_run(
        RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30"),
        deps,
        run_id="r-freeze",
        agent_version=2,
        system_prompt="p",
        budget=ExecutionBudget(max_steps=5),
        release_status="GRAY",
        frozen=frozen,
    )
    assert result.state == "COMPLETED"
    run = await deps.store.get_run_full("r-freeze")
    mc = json.loads(run["model_config"])
    assert mc["frozen_versions"] == frozen


async def test_canary_stop_on_429(sessions):
    """§57.6 LLM 429 率超阈值 => canary 停止。"""
    from app.agent.runtime.store import RunStore

    svc = ReleaseService(sessions)
    await _seed(sessions, "ag429", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    store = RunStore(sessions)
    mc = {"model": "m", "release_status": "GRAY", "release_version": 2}
    for i in range(5):
        await store.create_run(
            run_id=f"a{i}",
            tenant_id="t",
            user_id="u",
            agent_id="ag429",
            agent_version=2,
            session_id="s",
            state="COMPLETED",
            budget_json={},
            model_config=mc,
            input_json={"text": "q"},
        )
        await store.finish_run(
            run_id=f"a{i}",
            state="COMPLETED",
            output_json={"answer": "x"},
            error_json={"code": "MODEL_RATE_LIMIT"},
            tokens_in=1,
            tokens_out=1,
            cost=0.01,
        )
    check = await svc.canary_check(
        tenant_id="t", agent_id="ag429", version=2, min_runs=5, llm_429_threshold=0.1
    )
    assert check["action"] == "stop"
    assert check["metrics"]["llm_429_rate"] == 1.0


async def test_canary_stop_on_negative_feedback(sessions):
    """§57.6 用户负面反馈达阈值 => canary 停止。"""
    import uuid

    from app.agent.runtime.store import RunStore
    from app.storage.models import EventRow

    svc = ReleaseService(sessions)
    await _seed(sessions, "agFb", [(1, "ACTIVE", "{}"), (2, "GRAY", '{"gray_percentage": 100}')])
    store = RunStore(sessions)
    mc = {"model": "m", "release_status": "GRAY", "release_version": 2}
    run_ids = []
    for i in range(4):
        run_id = f"fb{i}"
        run_ids.append(run_id)
        await store.create_run(
            run_id=run_id,
            tenant_id="t",
            user_id="u",
            agent_id="agFb",
            agent_version=2,
            session_id="s",
            state="COMPLETED",
            budget_json={},
            model_config=mc,
            input_json={"text": "q"},
        )
        await store.finish_run(
            run_id=run_id,
            state="COMPLETED",
            output_json={"answer": "x"},
            error_json=None,
            tokens_in=1,
            tokens_out=1,
            cost=0.01,
        )
    async with sessions() as s:
        for rid in run_ids:
            s.add(
                EventRow(
                    id=f"ev-{uuid.uuid4().hex[:8]}",
                    event_type="feedback.bad",
                    tenant_id="t",
                    aggregate_id=rid,
                    payload_json="{}",
                )
            )
        await s.commit()
    check = await svc.canary_check(
        tenant_id="t", agent_id="agFb", version=2, min_runs=4, feedback_threshold=3
    )
    assert check["action"] == "stop"
    assert check["metrics"]["negative_feedback"] == 4
