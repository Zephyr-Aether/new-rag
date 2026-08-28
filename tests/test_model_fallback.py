"""模型降级链（§8.2/§9.4）：large→medium→small→默认 逐级回落。"""

import pytest

from app.agent.model.gateway import BaseProvider, ModelGateway, ModelResult
from app.agent.model.router import ModelRouter
from app.common.errors import ModelError
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        llm_model_large="L",
        llm_model_medium="M",
        llm_model_small="S",
        llm_model="D",
        llm_provider="mock",
    )


def test_fallback_chain_order():
    r = ModelRouter(_settings())
    assert r.fallback_chain(tier="large") == ["L", "M", "S", "D"]
    assert r.fallback_chain(tier="medium") == ["L", "M", "S", "D"]
    assert r.fallback_chain(model="X") == ["X"]  # 显式 model 不降级


async def test_gateway_escalates_on_model_failure():
    """大模型抛错 => 降级到 medium 返回结果。"""
    gw = ModelGateway(_settings())
    used: list[str] = []

    class _FailLarge(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            used.append(model)
            if model == "L":
                raise ModelError("large down")
            return ModelResult(content=f"ok:{model}", tokens_in=1, tokens_out=1, cost=0, model=model)

    gw.provider = _FailLarge()
    res = await gw.complete(messages=[], tools=[], tier="large")
    assert res.content == "ok:M"
    assert used == ["L", "M"]


async def test_gateway_escalation_exhausted():
    """全部模型失败 => 抛最后一个 ModelError（优雅失败）。"""
    gw = ModelGateway(_settings())

    class _AlwaysFail(BaseProvider):
        async def complete(self, messages, tools, model, token=None):
            raise ModelError(f"{model} down")

    gw.provider = _AlwaysFail()
    with pytest.raises(ModelError):
        await gw.complete(messages=[], tools=[], tier="large")
