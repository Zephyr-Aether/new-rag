"""Run 执行锁（§3.4 并发模型 + §55.8 Zombie）。

- 有 redis_url => Redis SET NX PX 分布式锁；
- 无 redis_url => 进程内锁（单实例开发/测试）。
锁 TTL 即 Lease；崩溃后锁过期，recovery 可接管（§3.6）。
"""

import asyncio
import time


class RunLockService:
    """统一接口：acquire / release / is_expired / touch。"""

    def __init__(self, redis_url: str, lock_ttl_s: float = 600.0):
        self.redis_url = redis_url
        self.lock_ttl_s = lock_ttl_s
        self._redis = None
        self._local: dict[str, float] = {}  # run_id -> 过期时间戳（进程内实现）
        self._local_locks: dict[str, asyncio.Lock] = {}

    async def _get_redis(self):
        if self.redis_url and self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def key(self, run_id: str) -> str:
        return f"run:lock:{run_id}"

    async def acquire(self, run_id: str) -> bool:
        if self._redis is not None or (self.redis_url and await self._get_redis() is not None):
            r = self._redis
            return bool(await r.set(self.key(run_id), "1", nx=True, px=int(self.lock_ttl_s * 1000)))
        # 进程内
        self._local_locks.setdefault(run_id, asyncio.Lock())
        lock = self._local_locks[run_id]
        if lock.locked():
            return False
        await lock.acquire()
        self._local[run_id] = time.time() + self.lock_ttl_s
        return True

    async def release(self, run_id: str) -> None:
        if self._redis is not None:
            await self._redis.delete(self.key(run_id))
            return
        self._local.pop(run_id, None)
        lock = self._local_locks.get(run_id)
        if lock and lock.locked():
            lock.release()

    async def touch(self, run_id: str) -> None:
        """续租：每步刷新锁 TTL，防止长任务执行中被误判为僵尸（§55.8）。"""
        if self._redis is not None:
            await self._redis.expire(self.key(run_id), int(self.lock_ttl_s))
            return
        if run_id in self._local:
            self._local[run_id] = time.time() + self.lock_ttl_s

    async def is_expired(self, run_id: str, now: float) -> bool:
        """锁是否已过期/缺失（供 recovery 判定僵尸 Run）。"""
        if self._redis is not None:
            return await self._redis.get(self.key(run_id)) is None
        expires = self._local.get(run_id)
        return expires is None or now > expires

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
