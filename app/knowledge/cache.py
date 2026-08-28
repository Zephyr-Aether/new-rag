"""版本化检索缓存 + Singleflight（§49.5 / §49.7）。

Cache Key 含隔离维度：tenant / permission scope / kb_version / embed_version / query_hash
——权限窄化后命中即越权的问题从 key 设计上杜绝。
Singleflight：同 key 并发 Miss 只加载一次（防 Cache Stampede）。
MVP 进程内实现（生产可换 Redis，接口不变）。
"""

import asyncio
import hashlib
import json
import time


class RetrievalCache:
    def __init__(self, *, ttl_s: float = 300.0, max_size: int = 1024):
        self.ttl_s = ttl_s
        self.max_size = max_size
        self._store: dict[str, tuple[float, dict]] = {}
        self._inflight: dict[str, asyncio.Task] = {}

    @staticmethod
    def key(
        *, tenant_id: str, query: str, permission: str = "", kb_version: str = "0", embed_version: str = ""
    ) -> str:
        raw = f"{tenant_id}|{permission}|{kb_version}|{embed_version}|{query}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get_or_load(self, cache_key: str, loader) -> dict:
        task = self._inflight.get(cache_key)
        if task is not None:
            return await task  # §49.7 单飞：并发 Miss 合并
        entry = self._store.get(cache_key)
        if entry is not None and time.monotonic() - entry[0] < self.ttl_s:
            return entry[1]
        task = asyncio.create_task(self._load(cache_key, loader))
        self._inflight[cache_key] = task
        try:
            return await task
        finally:
            self._inflight.pop(cache_key, None)

    async def clear(self) -> None:
        """知识库变更（入库/删除）后清空缓存：避免新内容被旧检索结果遮蔽。"""
        self._store.clear()

    def warm(self, loader, *keys: str) -> None:
        """§49.7 预热：热点 key 后台加载，首个真实请求即命中（防冷启动打穿）。"""
        for k in keys:
            if k not in self._store:
                asyncio.create_task(self._load(k, loader))

    async def _load(self, cache_key: str, loader) -> dict:
        value = await loader()
        self._store[cache_key] = (time.monotonic(), value)
        if len(self._store) > 2 * self.max_size:
            now = time.monotonic()
            self._store = {k: v for k, v in self._store.items() if now - v[0] < self.ttl_s}
        return value


class RedisRetrievalCache:
    """§49.6 跨实例缓存：Redis GET/SET（TTL）+ 进程内单飞。

    与 RetrievalCache 接口一致（key 同构）；值序列化为 JSON（TTL 过期自动失效）。
    """

    def __init__(self, redis_url: str, ttl_s: float = 300.0):
        self.redis_url = redis_url
        self.ttl_s = ttl_s
        self._redis = None
        self._inflight: dict[str, asyncio.Task] = {}
        self._keys: set[str] = set()  # 本进程写过的 key，供 clear() 精确删除

    key = RetrievalCache.key

    async def _client(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def get_or_load(self, cache_key: str, loader) -> dict:
        task = self._inflight.get(cache_key)
        if task is not None:
            return await task
        r = await self._client()
        cached = await r.get(cache_key)
        if cached is not None:
            return json.loads(cached)
        task = asyncio.create_task(self._load(cache_key, loader))
        self._inflight[cache_key] = task
        try:
            return await task
        finally:
            self._inflight.pop(cache_key, None)

    async def clear(self) -> None:
        """知识库变更后清空：删除本进程写过的所有检索缓存 key。"""
        if self._keys and self._redis is not None:
            r = await self._client()
            await r.delete(*self._keys)
            self._keys.clear()

    def warm(self, loader, *keys: str) -> None:
        """§49.7 预热：热点 key 后台加载到 Redis。"""
        for k in keys:
            asyncio.create_task(self._load(k, loader))

    async def _load(self, cache_key: str, loader) -> dict:
        value = await loader()
        r = await self._client()
        payload = value.model_dump() if hasattr(value, "model_dump") else value
        await r.set(cache_key, json.dumps(payload, ensure_ascii=False), ex=self.ttl_s)
        self._keys.add(cache_key)
        return payload


def make_retrieval_cache(redis_url: str = "") -> RetrievalCache:
    """§49.6：有 Redis 走跨实例缓存；否则进程内（接口一致）。"""
    if redis_url:
        return RedisRetrievalCache(redis_url)
    return RetrievalCache()
