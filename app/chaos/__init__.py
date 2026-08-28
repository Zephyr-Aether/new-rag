"""混沌工程（§80）：主动注入故障，验证降级/恢复/不悬挂。

ChaosProvider 包装真实 provider 按规则注入故障（慢/失败/限流）；
ChaosSessions 包装 DB 会话工厂按规则注入故障（慢/失败）；
run_chaos 执行场景并断言"优雅失败而非悬挂"。
"""

import asyncio
import time

from app.agent.model.gateway import BaseProvider
from app.common.cancellation import CancellationToken, cancelable_sleep
from app.common.errors import ModelError


class ChaosProvider(BaseProvider):
    """包装 provider，按规则注入故障（§80 Chaos 注入）。"""

    def __init__(
        self,
        inner: BaseProvider,
        *,
        fail_count: int = 0,  # 前 N 次调用失败（0=不失败）
        slow_s: float = 0.0,  # 每次调用延迟
        fail_with: type[ModelError] | None = None,
        fail_429: bool = False,
    ):
        self.inner = inner
        self.calls = 0
        self.fail_count = fail_count
        self.slow_s = slow_s
        self.fail_with = fail_with
        self.fail_429 = fail_429

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        token: CancellationToken | None = None,
    ):
        self.calls += 1
        if self.slow_s:
            await cancelable_sleep(token, self.slow_s)
        if self.fail_count and self.calls <= self.fail_count:
            if self.fail_429:
                from app.common.errors import ModelRateLimitError

                raise ModelRateLimitError("chaos: injected 429", detail={"chaos": True})
            exc = (self.fail_with or ModelError)("chaos: injected failure")
            raise exc
        return await self.inner.complete(messages, tools, model, token=token)


class _RaiseSession:
    """进入即抛错（模拟 DB 不可用）。"""

    def __init__(self, message: str):
        self._message = message

    async def __aenter__(self):
        raise RuntimeError(self._message)

    async def __aexit__(self, *exc):
        return False


class _SlowSession:
    """进入前延迟，然后委托真实会话（模拟 DB 慢）。"""

    def __init__(self, inner, delay_s: float):
        self._inner = inner
        self._delay = delay_s
        self._session = None

    async def __aenter__(self):
        await asyncio.sleep(self._delay)
        self._session = self._inner()
        await self._session.__aenter__()
        return self._session

    async def __aexit__(self, *exc):
        if self._session is not None:
            return await self._session.__aexit__(*exc)
        return False


class ChaosSessions:
    """包装 DB 会话工厂：按规则注入慢/失败（§30.2 DB 故障注入）。

    用法：RunStore(ChaosSessions(sessions, delay_s=0.05)) / fail_count=N（前 N 次会话失败）。
    """

    def __init__(self, inner, *, delay_s: float = 0.0, fail_count: int = 0):
        self.inner = inner
        self.delay_s = delay_s
        self.fail_count = fail_count
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.fail_count and self.calls <= self.fail_count:
            return _RaiseSession("chaos: injected db failure")
        if self.delay_s:
            return _SlowSession(self.inner, self.delay_s)
        return self.inner(*args, **kwargs)


class ChaosKnowledgeService:
    """包装知识检索：注入检索慢/失败（§30.2 Vector DB 慢/故障）。"""

    def __init__(self, inner, *, delay_s: float = 0.0, fail_every: int = 0):
        self._inner = inner
        self.delay_s = delay_s
        self.fail_every = fail_every
        self.calls = 0

    async def search(self, req):
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail_every and self.calls % self.fail_every == 0:
            raise RuntimeError("chaos: injected retrieval failure")
        return await self._inner.search(req)

    async def ingest_markdown(self, **kwargs):
        return await self._inner.ingest_markdown(**kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def run_chaos(name: str, fn) -> dict:
    """执行混沌场景。断言/异常不抛出，转为 failed 报告（§80 每轮 Chaos 出具报告）。"""
    started = time.monotonic()
    result: dict = {"name": name, "status": "passed", "error": None, "elapsed_s": 0.0}
    try:
        await fn()
    except AssertionError as exc:
        result["status"] = "failed"
        result["error"] = f"assertion: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_s"] = round(time.monotonic() - started, 3)
    return result
