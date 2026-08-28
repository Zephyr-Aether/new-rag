"""评测飞轮（§20）：发布回归运行器 + 历史对比。"""

import asyncio

from app.evaluation.service import EvaluationService


async def test_regression_pass(deps, sessions):
    """回归通过：BADCASES 含 expected terms，mock 答案命中 => pass_rate=1、regressed=False、落库。"""
    svc = EvaluationService(sessions)
    await svc.add_bad_case(tenant_id="t", query="12 + 30", expected=["42"])
    report = await svc.run_regression(tenant_id="t", agent_id="a", version=1, system_prompt="", deps=deps)
    assert report["total"] == 1 and report["passed"] == 1
    assert report["pass_rate"] == 1.0
    assert report["regressed"] is False
    latest = await svc.latest_regression(tenant_id="t", agent_id="a", version=1)
    assert latest and latest["pass_rate"] == 1.0


async def test_regression_fail_without_expected_hit(deps, sessions):
    """判定：COMPLETED 但 answer 不含 expected terms => 该条 fail。"""
    from app.agent.model.gateway import MockProvider, ModelResult

    class _WrongAnswerProvider(MockProvider):
        async def complete(self, messages, tools, model, token=None):
            await asyncio.sleep(0.01)
            return ModelResult(content="Answer: 99", tokens_in=1, tokens_out=1, cost=0, model=model)

    svc = EvaluationService(sessions)
    await svc.add_bad_case(tenant_id="t", query="12 + 30", expected=["42"])
    deps.gateway.provider = _WrongAnswerProvider()
    report = await svc.run_regression(tenant_id="t", agent_id="a", version=1, system_prompt="", deps=deps)
    assert report["total"] == 1 and report["passed"] == 0
    assert report["pass_rate"] == 0.0


async def test_regression_regressed_on_drop(deps, sessions):
    """回归回退：v1 pass_rate=1，v2=0 => regressed=True 且带 previous_pass_rate。"""
    from app.agent.model.gateway import MockProvider, ModelResult

    class _WrongAnswerProvider(MockProvider):
        async def complete(self, messages, tools, model, token=None):
            await asyncio.sleep(0.01)
            return ModelResult(content="Answer: 99", tokens_in=1, tokens_out=1, cost=0, model=model)

    svc = EvaluationService(sessions)
    await svc.add_bad_case(tenant_id="t", query="12 + 30", expected=["42"])
    await svc.run_regression(tenant_id="t", agent_id="a", version=1, system_prompt="", deps=deps)
    deps.gateway.provider = _WrongAnswerProvider()
    report = await svc.run_regression(tenant_id="t", agent_id="a", version=2, system_prompt="", deps=deps)
    assert report["passed"] == 0
    assert report["previous_pass_rate"] == 1.0
    assert report["regressed"] is True
    # regressed 标志落库
    latest = await svc.latest_regression(tenant_id="t", agent_id="a", version=2)
    assert latest["regressed"] is True


async def test_regression_empty_dataset(sessions, deps):
    """无评测集 => total=0、pass_rate=1.0（空集无质量回退风险）、regressed=False，不抛错。"""
    svc = EvaluationService(sessions)
    report = await svc.run_regression(tenant_id="t", agent_id="a", version=1, system_prompt="", deps=deps)
    assert report["total"] == 0 and report["pass_rate"] == 1.0
    assert report["regressed"] is False
