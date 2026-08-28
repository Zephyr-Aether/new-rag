"""账单对账（§50.1）：reconcile 按权威价重算 actual_cost 并校正 run.cost。"""

import pytest

from app.agent.runtime.store import RunStore
from app.cost.service import CostService
from app.settings import Settings


async def _seed_run_with_call(
    sessions, run_id: str, tokens_in: int, tokens_out: int, estimated: float
) -> None:
    store = RunStore(sessions)
    await store.create_run(
        run_id=run_id,
        tenant_id="t",
        user_id="u",
        agent_id="a",
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
        error_json=None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=estimated,
    )
    await store.record_llm_call(
        run_id=run_id,
        step_id="s1",
        model="m",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost=estimated,
        latency_ms=5,
    )


async def test_reconcile_with_prices_override(sessions):
    svc = CostService(sessions, settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    await _seed_run_with_call(sessions, "r1", tokens_in=1000, tokens_out=2000, estimated=0.01)
    report = await svc.reconcile(prices={"m": (1.0, 3.0)})
    assert report["reconciled"] == 1 and report["runs_updated"] == 1
    assert report["total_actual"] == pytest.approx(0.007)  # 1000/1e6*1 + 2000/1e6*3
    assert report["diff"] == pytest.approx(-0.003)
    run = await RunStore(sessions).get_run("r1")
    assert run["cost"] == pytest.approx(0.007)  # run.cost 被校正
    # 二次对账幂等：无未对账记录
    again = await svc.reconcile(prices={"m": (1.0, 3.0)})
    assert again["reconciled"] == 0


async def test_reconcile_default_settings_prices(sessions):
    svc = CostService(sessions, settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    await _seed_run_with_call(sessions, "r2", tokens_in=1_000_000, tokens_out=0, estimated=0.5)
    report = await svc.reconcile()  # settings 默认单价 in=1.0/out=3.0
    assert report["reconciled"] == 1
    assert report["total_actual"] == pytest.approx(1.0)  # 1M/1e6*1.0


async def test_reconcile_run_filter(sessions):
    svc = CostService(sessions, settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    await _seed_run_with_call(sessions, "ra", tokens_in=1000, tokens_out=0, estimated=0.01)
    await _seed_run_with_call(sessions, "rb", tokens_in=2000, tokens_out=0, estimated=0.01)
    report = await svc.reconcile(run_id="rb", prices={"m": (1.0, 3.0)})
    assert report["reconciled"] == 1
    assert report["runs_updated"] == 1


async def test_reconcile_with_bill_matching(sessions):
    """§50.1 对账上游：账单命中 run+step 用账单价校正 actual_cost 与 run.cost。"""
    svc = CostService(sessions, settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    await _seed_run_with_call(sessions, "r1", tokens_in=1000, tokens_out=2000, estimated=0.01)
    report = await svc.reconcile(
        prices={"m": (1.0, 3.0)}, bill=[{"run_id": "r1", "step_id": "s1", "cost": 0.005}]
    )
    assert report["matched_bill"] == 1 and report["fallback_priced"] == 0
    assert report["total_actual"] == pytest.approx(0.005)  # 账单价优先于价格计算
    run = await RunStore(sessions).get_run("r1")
    assert run["cost"] == pytest.approx(0.005)


async def test_reconcile_bill_mixed(sessions):
    """账单命中一部分，未命中的回落价格计算。"""
    svc = CostService(sessions, settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    await _seed_run_with_call(sessions, "ra", tokens_in=1000, tokens_out=0, estimated=0.01)
    await _seed_run_with_call(sessions, "rb", tokens_in=1000, tokens_out=0, estimated=0.01)
    report = await svc.reconcile(
        prices={"m": (1.0, 3.0)}, bill=[{"run_id": "ra", "step_id": "s1", "cost": 0.004}]
    )
    assert report["matched_bill"] == 1 and report["fallback_priced"] == 1
    assert report["total_actual"] == pytest.approx(0.005)  # 0.004 + 1000/1e6*1.0


async def test_reconcile_with_bill_provider(sessions):
    """§50.1 对账上游：经 BillProvider 拉取账单校正 actual_cost。"""
    from app.cost.billing import StaticBillProvider

    svc = CostService(sessions, settings=Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))
    await _seed_run_with_call(sessions, "r1", tokens_in=1000, tokens_out=2000, estimated=0.01)
    report = await svc.reconcile(
        bill_provider=StaticBillProvider([{"tenant_id": "t", "run_id": "r1", "step_id": "s1", "cost": 0.009}])
    )
    assert report["matched_bill"] == 1 and report["fallback_priced"] == 0
    assert report["total_actual"] == pytest.approx(0.009)
