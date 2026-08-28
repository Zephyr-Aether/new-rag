"""Model Provider Pool（§52.1）：多 Provider 端点，按健康权重切流（§52.3）。

每个 Provider 一个健康跟踪器；pick() 选健康权重最高者；全不可用 => MODEL_UNAVAILABLE。
"""

from app.agent.model.health import ProviderHealth
from app.common.errors import ModelError


class ProviderEntry:
    def __init__(self, provider):
        self.provider = provider
        self.health = ProviderHealth()


class ModelProviderPool:
    def __init__(self, providers: list):
        self.entries = [ProviderEntry(p) for p in providers]

    def healthy_entries(self) -> list[ProviderEntry]:
        return [e for e in self.entries if e.health.traffic_weight() > 0]

    def pick(self) -> ProviderEntry:
        healthy = self.healthy_entries()
        if not healthy:
            raise ModelError("all model providers unavailable", code="MODEL_UNAVAILABLE")
        return max(healthy, key=lambda e: e.health.traffic_weight())
