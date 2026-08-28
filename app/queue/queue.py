"""JobQueue（§9 / §11 / §55）：按任务类型分 Worker Pool + 优先级 + 重试/DLQ + 水位限流/背压。

- 每类任务独立优先级堆（§55 隔离：ingest 洪峰不饿死 agent_run）
- 水位限流（§9.3）：<70% 正常 / 70-85% 限低优 / 85-95% 仅高优 / >95% 拒绝
- 重试（attempts<max => QUEUED 重新入堆）；耗尽 => DEAD_LETTER
- 单飞/租约等生产形态后置；MVP 进程内实现
"""

import asyncio
import heapq
import time

from app.common.errors import QueueFullError
from app.queue.store import JobStore


class JobQueue:
    def __init__(
        self,
        store: JobStore,
        handlers: dict[str, callable] | None = None,
        *,
        capacity: int = 100,
        lease_s: int = 30,
    ):
        self.store = store
        self.handlers = handlers or {}
        self._heaps: dict[str, list[tuple[int, int, str]]] = {}  # job_type -> (priority, seq, job_id)
        self._seq = 0
        self.capacity = capacity
        self.lease_s = lease_s  # §55 租约时长（Zombie 检测）
        self._stop: asyncio.Event | None = None
        self._workers: list[asyncio.Task] = []

    def register(self, job_type: str, handler) -> None:
        self.handlers[job_type] = handler

    def pending(self) -> int:
        return sum(len(h) for h in self._heaps.values())

    def watermark(self) -> float:
        return self.pending() / self.capacity if self.capacity else 0.0

    def admission_allowed(self, priority: int) -> bool:
        """§9.3 水位限流（Admission Control）。"""
        w = self.watermark()
        if w < 0.70:
            return True
        if w < 0.85:
            return priority <= 1
        if w < 0.95:
            return priority == 0
        return False

    def is_backpressured(self) -> bool:
        """§9.3 背压：水位 > 85%，上游应限产。"""
        return self.watermark() > 0.85

    async def enqueue(
        self,
        *,
        tenant_id: str,
        job_type: str,
        payload: dict,
        priority: int = 2,
        max_attempts: int = 3,
        dedupe_key: str | None = None,
    ) -> str:
        if not self.admission_allowed(priority):
            raise QueueFullError(
                "queue capacity exceeded",
                detail={"priority": priority, "watermark": round(self.watermark(), 3)},
            )
        if dedupe_key:
            existing = await self.store.find_active(
                tenant_id=tenant_id, job_type=job_type, dedupe_key=dedupe_key
            )
            if existing is not None:
                return existing  # §11 单飞：合并并发重复任务
        job_id = await self.store.create(
            tenant_id=tenant_id,
            job_type=job_type,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts,
            dedupe_key=dedupe_key,
        )
        heapq.heappush(self._heaps.setdefault(job_type, []), (priority, self._seq, job_id))
        self._seq += 1
        return job_id

    async def _next(self, job_type: str) -> str | None:
        heap = self._heaps.get(job_type)
        if not heap:
            return None
        while heap:
            _prio, _seq, job_id = heapq.heappop(heap)
            if await self.store.claim(job_id, self.lease_s):
                return job_id
        return None

    async def _heartbeat(self, job_id: str) -> None:
        """§55 租约续期：Worker 存活期心跳；Worker 崩溃则租约过期被 Zombie 检测重入队。"""
        try:
            while True:
                await asyncio.sleep(min(self.lease_s / 3, 5))
                await self.store.heartbeat(job_id, self.lease_s)
        except asyncio.CancelledError:
            pass

    async def _process_job(self, job_id: str) -> str | None:
        """处理一个已认领的任务（心跳 + handler + 成功/失败重试）。"""
        row = await self.store.get(job_id)
        if row is None:
            return None
        hb = asyncio.create_task(self._heartbeat(job_id))  # §55 租约心跳
        try:
            handler = self.handlers.get(row["job_type"])
            if handler is None:
                raise RuntimeError(f"no handler for job_type={row['job_type']}")
            await handler(row["payload"])
            await self.store.succeed(job_id)
        except Exception as exc:
            state = await self.store.fail(job_id, str(exc))
            if state == "QUEUED":  # 重试：重新入堆（同优先级）
                heapq.heappush(
                    self._heaps.setdefault(row["job_type"], []), (row["priority"], self._seq, job_id)
                )
                self._seq += 1
        finally:
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)
        return job_id

    async def _process(self, job_type: str) -> str | None:
        job_id = await self._next(job_type)
        if job_id is None:
            return None
        return await self._process_job(job_id)

    async def recover_zombies(self) -> int:
        """§55 Zombie 检测：租约过期仍 RUNNING 的任务重新入队。"""
        expired = await self.store.recover_zombies()
        for job_id in expired:
            row = await self.store.get(job_id)
            if row and row["state"] == "QUEUED":
                heapq.heappush(
                    self._heaps.setdefault(row["job_type"], []), (row["priority"], self._seq, job_id)
                )
                self._seq += 1
        return len(expired)

    async def requeue(self, job_id: str) -> dict:
        """DLQ 重放：重置死信任务并重新入堆（可再次被认领执行）。"""
        res = await self.store.requeue(job_id)
        if res.get("state") == "CREATED" and not res.get("skipped"):
            row = await self.store.get(job_id)
            if row:
                heapq.heappush(
                    self._heaps.setdefault(row["job_type"], []), (row["priority"], self._seq, job_id)
                )
                self._seq += 1
        return res

    async def cancel(self, job_id: str) -> dict:
        """§11.2 取消排队任务（并从堆中移除）。"""
        state = await self.store.cancel(job_id)
        if state == "CANCELLED":
            for job_type, heap in list(self._heaps.items()):
                self._heaps[job_type] = [item for item in heap if item[2] != job_id]
                heapq.heapify(self._heaps[job_type])
        return {"job_id": job_id, "state": state}

    async def expire_old(self, ttl_s: int = 3600) -> dict:
        """§11.2 清理超龄 QUEUED 任务（EXPIRED）。"""
        expired = await self.store.expire_old(ttl_s)
        for job_id in expired:
            for job_type, heap in list(self._heaps.items()):
                self._heaps[job_type] = [item for item in heap if item[2] != job_id]
                heapq.heapify(self._heaps[job_type])
        return {"expired": expired, "count": len(expired)}

    async def process_once(self, job_type: str | None = None) -> str | None:
        """处理一个任务（§55：可指定类型；None 时选最高优先级类型）。"""
        if job_type is not None:
            return await self._process(job_type)
        best, best_prio = None, float("inf")
        for t, heap in self._heaps.items():
            if heap and heap[0][0] < best_prio:
                best, best_prio = t, heap[0][0]
        if best is None:
            return None
        return await self._process(best)

    def start(self, workers_by_type: dict[str, int] | None = None) -> None:
        """§55 按任务类型分 Worker Pool：{"agent_run": 2, "ingest": 1}。"""
        self._stop = asyncio.Event()
        self._workers = []
        for t, n in (workers_by_type or {}).items():
            for _ in range(n):
                self._workers.append(asyncio.create_task(self._worker(t)))
        if not workers_by_type:  # 兼容：通用 worker 处理任意类型
            self._workers.append(asyncio.create_task(self._worker(None)))

    async def _worker(self, job_type: str | None) -> None:
        while self._stop is not None and not self._stop.is_set():
            processed = await self.process_once(job_type)
            if processed is None:
                # 本地堆空：从共享库跨实例认领（§55 HA 多实例，DB 租约互斥）
                remote = await self.store.claim_queued(job_type, self.lease_s)
                if remote is not None:
                    await self._process_job(remote)
                else:
                    await asyncio.sleep(0.05)

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        workers = self._workers
        for task in workers:
            task.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self._workers = []

    async def drain(self, timeout_s: float = 5.0) -> int:
        processed = 0
        deadline = time.monotonic() + timeout_s
        while self.pending() > 0 and time.monotonic() < deadline:
            if await self.process_once() is None:
                break
            processed += 1
        return processed
