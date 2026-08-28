"""Model Router（§8 / §35）：任务分级 → 模型；决策可落 Trace。

MVP：按 tier 映射模型（small/medium/large，空则回落默认）；
升级（escalation）与动态健康路由留接口（Phase 后接 Model Pool）。
"""

from app.settings import Settings


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._default_model = settings.llm_model

    @property
    def default_model(self) -> str:
        return self._default_model

    def set_default_model(self, model: str) -> None:
        """运行时模型配置（gateway.configure）同步到路由默认档，优先于 .env。"""
        if model:
            self._default_model = model

    def route(self, *, tier: str = "medium", model: str | None = None) -> tuple[str, dict]:
        """返回 (model, decision)。显式 model 优先；否则按 tier 映射。"""
        if model:
            return model, {"tier": tier, "reason": "explicit model"}
        tier_model = {
            "small": self.settings.llm_model_small or self.default_model,
            "medium": self.settings.llm_model_medium or self.default_model,
            "large": self.settings.llm_model_large or self.default_model,
        }.get(tier, self.default_model)
        return tier_model, {"tier": tier, "reason": f"tier={tier} -> {tier_model}"}

    def fallback_chain(self, *, tier: str = "medium", model: str | None = None) -> list[str]:
        """§8.2/§9.4 降级链：large→medium→small→默认（去重）。

        显式 model 时单元素（不降级）；否则按配置档位逐级回落。
        """
        if model:
            return [model]
        order = [
            self.settings.llm_model_large,
            self.settings.llm_model_medium,
            self.settings.llm_model_small,
            self.default_model,
        ]
        chain: list[str] = []
        for m in order:
            if m and m not in chain:
                chain.append(m)
        return chain or [self.default_model]
