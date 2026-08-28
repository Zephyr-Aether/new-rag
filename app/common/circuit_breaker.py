"""Circuit Breaker（§9.3 / §39）：CLOSED → OPEN → HALF_OPEN。

通用：LLM Provider 与 Tool 各自一个实例。熔断开门时快速失败（不一直 Retry）。
"""

import time


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str = "breaker",
        failure_threshold: int = 5,
        window_s: float = 60.0,
        cooldown_s: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self._state = "CLOSED"  # CLOSED / OPEN / HALF_OPEN
        self._failures: list[float] = []
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        return self._state

    def allow(self) -> bool:
        """是否允许放行一次调用。"""
        if self._state == "OPEN":
            if self._opened_at is not None and time.time() - self._opened_at >= self.cooldown_s:
                self._state = "HALF_OPEN"
                return True
            return False
        return True

    def record(self, success: bool) -> None:
        now = time.time()
        if self._state == "HALF_OPEN":
            if success:
                self._state = "CLOSED"
                self._failures = []
            else:
                self._state = "OPEN"
                self._opened_at = now
                self._failures = [now]
            return
        if success:
            self._failures = []
            return
        self._failures.append(now)
        self._failures = [t for t in self._failures if now - t < self.window_s]
        if len(self._failures) >= self.failure_threshold:
            self._state = "OPEN"
            self._opened_at = now
