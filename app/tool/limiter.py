"""RateLimiter（§29 的 MVP 形态）：滑动窗口限流。

- 有 redis_url => Redis ZSET 滑动窗口（跨实例一致）；
- 无 redis_url => 进程内 deque（单实例开发/测试）。
按 key（如 tenant:user:tool）限流，默认 100 次 / 60s。
"""

import time
from collections import deque


class RateLimiter:
    def __init__(self, redis_url: str = "", default_limit: int = 100, default_window_s: float = 60.0):
        self.redis_url = redis_url
        self.default_limit = default_limit
        self.default_window_s = default_window_s
        self._redis = None
        self._local: dict[str, deque] = {}

    async def _client(self):
        if self.redis_url and self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def acquire(self, key: str, *, limit: int | None = None, window_s: float | None = None) -> bool:
        limit = limit if limit is not None else self.default_limit
        window_s = window_s if window_s is not None else self.default_window_s
        now = time.monotonic()

        r = await self._client()
        if r is not None:
            zkey = f"rl:{key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(zkey, "-inf", now - window_s)
            pipe.zadd(zkey, {str(now): now})
            pipe.zcard(zkey)
            pipe.expire(zkey, int(window_s * 2))
            results = await pipe.execute()
            return int(results[2]) <= limit

        dq = self._local.setdefault(key, deque())
        while dq and dq[0] <= now - window_s:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True
