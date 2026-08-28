"""Run 取消服务（§3 请求必须可取消 / §8 Cancellation Propagation）。

有 redis_url => Redis SET 标记（跨实例可见）；无 => 进程内集合。
Runtime 每步检查；命中即 CANCELLED（协作式取消，不杀进程）。
"""

import redis.asyncio as aioredis

from app.common.cancellation import (  # noqa: F401（re-export）
    CancellationToken,
    await_cancelable,
    cancelable_sleep,
)

__all__ = ["CancelService", "CancellationToken", "cancelable_sleep", "await_cancelable"]


class CancelService:
    def __init__(self, redis_url: str = ""):
        self.redis_url = redis_url
        self._redis = None
        self._local: set[str] = set()

    async def _client(self):
        if self.redis_url and self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def _key(self, run_id: str) -> str:
        return f"run:cancel:{run_id}"

    async def cancel(self, run_id: str) -> None:
        r = await self._client()
        if r is not None:
            await r.set(self._key(run_id), "1")
            return
        self._local.add(run_id)

    async def is_cancelled(self, run_id: str) -> bool:
        r = await self._client()
        if r is not None:
            return bool(await r.get(self._key(run_id)))
        return run_id in self._local

    async def clear(self, run_id: str) -> None:
        r = await self._client()
        if r is not None:
            await r.delete(self._key(run_id))
            return
        self._local.discard(run_id)

    # §10.3 Pause：与 cancel 平行的暂停标记（进程内/Redis 同构）
    def _pause_key(self, run_id: str) -> str:
        return f"run:pause:{run_id}"

    async def pause(self, run_id: str) -> None:
        r = await self._client()
        if r is not None:
            await r.set(self._pause_key(run_id), "1")
            return
        self._local.add(f"pause:{run_id}")

    async def is_paused(self, run_id: str) -> bool:
        r = await self._client()
        if r is not None:
            return bool(await r.get(self._pause_key(run_id)))
        return f"pause:{run_id}" in self._local

    async def clear_pause(self, run_id: str) -> None:
        r = await self._client()
        if r is not None:
            await r.delete(self._pause_key(run_id))
            return
        self._local.discard(f"pause:{run_id}")
