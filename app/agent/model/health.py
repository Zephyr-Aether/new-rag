"""Provider 健康（§52.3）：滑动窗口错误率/429率/延迟 → Healthy/Degraded/Unavailable + 降流量。

每次调用 record；status() 与 traffic_weight() 供路由/调度消费（Degraded 降权，Unavailable 剔除）。
"""

import time
from collections import deque


class ProviderHealth:
    def __init__(
        self, *, window_s: float = 60.0, error_threshold: float = 0.3, unavailable_threshold: float = 0.9
    ):
        self.window_s = window_s
        self.error_threshold = error_threshold
        self.unavailable_threshold = unavailable_threshold
        self._calls: deque[tuple[float, bool, bool, float]] = deque(
            maxlen=2000
        )  # (t, ok, is_429, latency_ms)

    def record(self, *, ok: bool, is_429: bool = False, latency_ms: float = 0) -> None:
        self._calls.append((time.monotonic(), ok, is_429, latency_ms))

    def _recent(self) -> list[tuple[float, bool, bool, float]]:
        now = time.monotonic()
        return [c for c in self._calls if now - c[0] < self.window_s]

    def error_rate(self) -> float:
        recent = self._recent()
        if not recent:
            return 0.0
        return sum(1 for _, ok, is_429, _ in recent if not ok and not is_429) / len(recent)

    def rate_429(self) -> float:
        recent = self._recent()
        if not recent:
            return 0.0
        return sum(1 for _, _, is_429, _ in recent if is_429) / len(recent)

    def latency_p95(self) -> float:
        recent = sorted(c[3] for c in self._recent())
        if not recent:
            return 0.0
        return recent[min(len(recent) - 1, int(len(recent) * 0.95))]

    def status(self) -> str:
        if self.error_rate() >= self.unavailable_threshold:
            return "unavailable"
        if self.error_rate() >= self.error_threshold or self.rate_429() >= 0.2:
            return "degraded"
        return "healthy"

    def traffic_weight(self) -> float:
        return {"unavailable": 0.0, "degraded": 0.3, "healthy": 1.0}[self.status()]

    def recent_count(self) -> int:
        """窗口内调用数（负载均衡用）。"""
        return len(self._recent())
