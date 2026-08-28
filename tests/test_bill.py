"""账单对账上游（§50.1）：BillProvider 注入 reconcile。"""

from app.agent.runtime.store import RunStore
from app.cost.providers import StaticBillProvider
from app.cost.service import CostService


async def test_reconcile_with_static_bill(sessions):
    store = RunStore(sessions)
    await store.create_run(
        run_id="bill-r",
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
    await store.record_llm_call(
        run_id="bill-r",
        step_id="1",
        model="m",
        tokens_in=100,
        tokens_out=50,
        estimated_cost=0.01,
        latency_ms=10,
    )
    bill = StaticBillProvider([{"run_id": "bill-r", "step_id": "1", "cost": 0.42}])
    res = await CostService(sessions).reconcile(bill_provider=bill)
    assert res["reconciled"] >= 1
    assert res["total_actual"] >= 0.42  # 账单价生效
