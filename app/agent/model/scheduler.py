"""模型调度器（§52.2）：Capability → Health → Quota → Cost → Latency → Load Balance 过滤管线。

每级淘汰不合格 Provider，最终做负载均衡；决策 reasons 落 Trace（§52.4）。
MVP：health 用健康权重（§52.3）；latency 用观测 p95；cost 档预留（真实计价后接）。
"""

from app.agent.model.pool import ModelProviderPool, ProviderEntry
from app.common.errors import ModelError


class ModelScheduler:
    def __init__(self, *, default_latency_budget_ms: float = 10_000.0):
        self.default_latency_budget_ms = default_latency_budget_ms

    def pick(
        self,
        pool: ModelProviderPool,
        *,
        tier: str = "medium",
        latency_budget_ms: float | None = None,
    ) -> tuple[ProviderEntry, dict]:
        """过滤管线：返回 (entry, decision)；全不可用 => MODEL_UNAVAILABLE。"""
        budget = self.default_latency_budget_ms if latency_budget_ms is None else latency_budget_ms
        reasons: list[str] = []

        # Capability Filter：tier 已由 Router 解析为模型名，池内 provider 都可服务；记录
        reasons.append(f"capability: tier={tier}")
        candidates = list(pool.entries)

        # Health Filter（§52.3 健康权重，Degraded 降权 / Unavailable 剔除）
        healthy = [e for e in candidates if e.health.traffic_weight() > 0]
        reasons.append(f"health: {len(healthy)}/{len(candidates)} pass")
        if not healthy:
            raise ModelError("all model providers unavailable", code="MODEL_UNAVAILABLE")

        # Quota Filter（网关限流已前置，MVP 记录）
        reasons.append("quota: ok (gateway pre-checked)")

        # Cost Filter（成本档预留：真实计价后按档位淘汰）
        reasons.append("cost: pass (tier resolved)")

        # Latency Filter（用观测 p95；全超预算则保留原集）
        latency_ok = [e for e in healthy if e.health.latency_p95() <= budget]
        if latency_ok:
            healthy = latency_ok
        reasons.append(f"latency: {len(healthy)} pass (p95<={budget:.0f}ms)")

        # Load Balance：健康权重高者优先，其次调用少者（Least Load）
        best = max(healthy, key=lambda e: (e.health.traffic_weight(), -e.health.recent_count()))
        reasons.append("load-balance: picked (highest weight, least load)")
        return best, {"model": tier, "passed_filters": reasons}
