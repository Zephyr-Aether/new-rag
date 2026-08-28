"""可靠性三件套（§8/§37/§39）：ModelRouter / CircuitBreaker / LLM 限流。"""

import time

import pytest

from app.agent.model.gateway import BaseProvider, ModelGateway, ModelResult
from app.agent.model.router import ModelRouter
from app.common.circuit_breaker import CircuitBreaker
from app.common.errors import ModelError, ModelRateLimitError
from app.settings import Settings


# ---------- Model Router ----------
def test_router_tier_mapping():
    settings = Settings(
        llm_model="m", llm_model_small="small-m", llm_model_medium="medium-m", llm_model_large="large-m"
    )
    router = ModelRouter(settings)
    assert router.route(tier="small")[0] == "small-m"
    assert router.route(tier="medium")[0] == "medium-m"
    assert router.route(tier="large")[0] == "large-m"
    assert router.route(tier="large", model="explicit")[0] == "explicit"


def test_router_falls_back_to_default():
    settings = Settings(llm_model="m")
    router = ModelRouter(settings)
    assert router.route(tier="small")[0] == "m"


# ---------- Circuit Breaker ----------
def test_circuit_breaker_opens_and_rejects():
    cb = CircuitBreaker(failure_threshold=3, window_s=60, cooldown_s=60)
    for _ in range(3):
        cb.record(False)
    assert cb.state == "OPEN"
    assert not cb.allow()  # 冷却期内拒绝


def test_circuit_breaker_recovery_half_open():
    cb = CircuitBreaker(failure_threshold=2, window_s=60, cooldown_s=0.01)
    for _ in range(2):
        cb.record(False)
    assert cb.state == "OPEN"
    time.sleep(0.02)
    assert cb.allow()  # HALF_OPEN 放试探
    cb.record(True)
    assert cb.state == "CLOSED"


def test_circuit_breaker_success_resets_failures():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record(False)
    cb.record(True)
    assert cb._failures == []  # noqa: SLF001


# ---------- ModelGateway 限流 / 熔断 ----------
async def test_gateway_rate_limited():
    settings = Settings(database_url="sqlite+aiosqlite://", llm_provider="mock", llm_rate_limit=1)
    gw = ModelGateway(settings)
    await gw.complete(messages=[{"role": "user", "content": "hi"}], tools=[], tenant_id="t")
    with pytest.raises(ModelRateLimitError):
        await gw.complete(messages=[{"role": "user", "content": "hi"}], tools=[], tenant_id="t")


async def test_gateway_breaker_opens():
    class _FailingProvider(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            raise ModelError("boom")

    settings = Settings(database_url="sqlite+aiosqlite://", llm_provider="mock", llm_breaker_threshold=2)
    gw = ModelGateway(settings)
    gw.provider = _FailingProvider()
    for _ in range(2):
        with pytest.raises(ModelError):
            await gw.complete(messages=[{"role": "user", "content": "x"}], tools=[], tenant_id="t")
    assert gw.breaker.state == "OPEN"
    # 熔断开门：快速失败（MODEL_BREAKER_OPEN）
    with pytest.raises(ModelError) as excinfo:
        await gw.complete(messages=[{"role": "user", "content": "x"}], tools=[], tenant_id="t")
    assert excinfo.value.code == "MODEL_BREAKER_OPEN"


async def test_gateway_routes_by_tier():
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        llm_provider="mock",
        llm_model="m",
        llm_model_small="small-m",
    )
    gw = ModelGateway(settings)
    captured: dict = {}

    class _CaptureProvider(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            captured["model"] = model
            return ModelResult(content="ok", tokens_in=1, tokens_out=1, cost=0, model=model)

    gw.provider = _CaptureProvider()
    await gw.complete(messages=[{"role": "user", "content": "x"}], tools=[], tier="small", tenant_id="t")
    assert captured["model"] == "small-m"


def test_provider_health_degrades():
    """§52.3 Provider 健康：错误率/429率 → Healthy/Degraded/Unavailable + 降流量权重。"""
    from app.agent.model.health import ProviderHealth

    h = ProviderHealth(error_threshold=0.3, unavailable_threshold=0.9)
    assert h.status() == "healthy" and h.traffic_weight() == 1.0
    for _ in range(4):
        h.record(ok=False)
    h.record(ok=True)  # 40% 错误 -> degraded
    assert h.status() == "degraded"
    assert h.traffic_weight() == 0.3
    for _ in range(10):
        h.record(ok=False)  # >90% -> unavailable
    assert h.status() == "unavailable"
    assert h.traffic_weight() == 0.0


async def test_gateway_health_endpoint():
    from starlette.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        r = c.get("/model/health")
        assert r.status_code == 200
        m = r.json()["models"][0]
        assert m["status"] in ("healthy", "degraded", "unavailable")
        assert m["traffic_weight"] in (0.0, 0.3, 1.0)


async def test_model_pool_routes_by_health():
    """§52.1 多 Provider 按健康切流：坏 provider 被跳过，好 provider 被选中。"""
    from app.agent.model.gateway import MockProvider

    captured = {"model": None}

    class _CapProvider(MockProvider):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag
            self.calls = 0

        async def complete(self, messages, tools, model, token=None):
            captured["model"] = self.tag
            self.calls += 1
            return await super().complete(messages, tools, model, token=token)

    p1 = _CapProvider("p1")
    p2 = _CapProvider("p2")
    gw = ModelGateway(Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"), providers=[p1, p2])
    for _ in range(10):
        gw.pool.entries[0].health.record(ok=False)  # p1 变 unavailable
    await gw.complete(messages=[{"role": "user", "content": "hi"}], tools=[], tenant_id="t")
    assert captured["model"] == "p2"  # 切到健康 provider
    await gw.complete(messages=[{"role": "user", "content": "hi"}], tools=[], tenant_id="t")
    assert captured["model"] == "p2"
    assert p2.calls >= 2 and p1.calls == 0
    assert gw.pool.entries[0].health.status() == "unavailable"
    assert gw.pool.entries[1].health.status() == "healthy"


async def test_schedule_decision_differs_on_replay(sessions, policy, audit, rate_limiter, store):
    """§52 调度决策 Replay 对比：健康状态变化 => 调度决策不同（落 llm_calls 可对比）。"""
    from app.agent.model.gateway import MockProvider
    from app.agent.runtime.budget import ExecutionBudget
    from app.agent.runtime.cancel import CancelService
    from app.agent.runtime.runtime import RuntimeDeps, execute_run
    from app.common.contracts import RunInput
    from app.storage.lock import RunLockService
    from app.tool.registry import default_registry
    from app.tool.runtime import ToolRuntime

    class _CapProvider(MockProvider):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag

    p1 = _CapProvider("p1")
    p2 = _CapProvider("p2")
    gw = ModelGateway(Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"), providers=[p1, p2])
    reg = default_registry()
    rt = ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store)
    deps = RuntimeDeps(
        store=store,
        registry=reg,
        gateway=gw,
        lock=RunLockService(""),
        cancel=CancelService(""),
        tool_runtime=rt,
    )
    req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
    await execute_run(
        req, deps, run_id="r-sch1", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    d1 = [c["scheduler_reason"] for c in await store.list_llm_calls("r-sch1")]
    assert d1 and all("2/2 pass" in d for d in d1)  # 初始两个 provider 都健康

    for _ in range(10):
        gw.pool.entries[0].health.record(ok=False)  # p1 变 unavailable
    await execute_run(
        req, deps, run_id="r-sch2", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
    )
    d2 = [c["scheduler_reason"] for c in await store.list_llm_calls("r-sch2")]
    assert d2 and any("1/2 pass" in d for d in d2)  # 健康过滤只剩 p2
    assert d1 != d2  # §52 决策随健康变化，Replay 可对比
