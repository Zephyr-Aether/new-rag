"""JobStore：任务持久化 + 状态机（§9.2 CREATED→QUEUED→RUNNING→SUCCEEDED/FAILED/DEAD_LETTER）。"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.storage.models import JobRow, QueueSampleRow


def _now() -> datetime:
    return datetime.now(UTC)


class JobStore:
    def __init__(self, sessions):
        self.sessions = sessions

    async def create(
        self,
        *,
        tenant_id: str,
        job_type: str,
        payload: dict,
        priority: int,
        max_attempts: int,
        dedupe_key: str | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        async with self.sessions() as s:
            s.add(
                JobRow(
                    job_id=job_id,
                    tenant_id=tenant_id,
                    job_type=job_type,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    priority=priority,
                    max_attempts=max_attempts,
                    dedupe_key=dedupe_key,
                )
            )
            await s.commit()
        return job_id

    async def find_active(self, *, tenant_id: str, job_type: str, dedupe_key: str) -> str | None:
        """§11 单飞：同键且未终态（CREATED/QUEUED/RUNNING）的任务存在则返回其 job_id。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(JobRow).where(
                    JobRow.tenant_id == tenant_id,
                    JobRow.job_type == job_type,
                    JobRow.dedupe_key == dedupe_key,
                    JobRow.state.in_(["CREATED", "QUEUED", "RUNNING"]),
                )
            )
        return row.job_id if row else None

    async def claim(self, job_id: str, lease_s: int = 30) -> bool:
        """CAS：CREATED/QUEUED -> RUNNING（attempts+1）+ 租约（§55 Zombie 检测）。"""
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row is None or row.state not in ("CREATED", "QUEUED"):
                return False
            row.state = "RUNNING"
            row.attempts += 1
            row.started_at = _now()
            row.lease_until = _now() + timedelta(seconds=lease_s)
            await s.commit()
            return True

    async def claim_queued(self, job_type: str | None = None, lease_s: int = 30) -> str | None:
        """跨实例认领：从共享库抓取最高优先级待处理任务并原子 claim（§55 HA 多实例）。

        多实例 worker 无本地堆时轮询共享库，靠 claim 的 CAS + 租约互斥，避免双跑。
        """
        async with self.sessions() as s:
            q = select(JobRow).where(JobRow.state.in_(["CREATED", "QUEUED"]))
            if job_type:
                q = q.where(JobRow.job_type == job_type)
            q = q.order_by(JobRow.priority.asc(), JobRow.created_at.asc()).limit(10)
            rows = (await s.scalars(q)).all()
        for row in rows:
            if await self.claim(row.job_id, lease_s):
                return row.job_id
        return None

    async def heartbeat(self, job_id: str, lease_s: int = 30) -> None:
        """§55 续租：Worker 存活期延长租约（Zombie 检测的存活信号）。"""
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row and row.state == "RUNNING":
                row.lease_until = _now() + timedelta(seconds=lease_s)
                await s.commit()

    async def recover_zombies(self, *, now=None) -> list[str]:
        """§55 Zombie 检测：租约过期仍 RUNNING => 重新入队（QUEUED），交其他 Worker。"""
        now = now or _now()
        async with self.sessions() as s:
            rows = await s.scalars(select(JobRow).where(JobRow.state == "RUNNING"))
            expired: list[str] = []
            for r in rows:
                lease = r.lease_until
                if lease is None:
                    continue
                if lease.tzinfo is None:  # SQLite 返回 naive，统一按 aware 比较
                    lease = lease.replace(tzinfo=UTC)
                if lease < now:
                    r.state = "QUEUED"
                    expired.append(r.job_id)
            await s.commit()
            return expired

    async def succeed(self, job_id: str) -> None:
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row:
                row.state = "SUCCEEDED"
                row.finished_at = _now()
                await s.commit()

    async def fail(self, job_id: str, error: str) -> str:
        """RUNNING -> attempts>=max ? DEAD_LETTER : QUEUED（重试）。返回新状态。"""
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                return "FAILED"
            row.error = error
            if row.attempts >= row.max_attempts:
                row.state = "DEAD_LETTER"
                row.finished_at = _now()
            else:
                row.state = "QUEUED"  # 重试：可再次被认领
            await s.commit()
            return row.state

    async def get(self, job_id: str) -> dict | None:
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                return None
            return {
                "job_id": row.job_id,
                "tenant_id": row.tenant_id,
                "job_type": row.job_type,
                "payload": json.loads(row.payload_json),
                "priority": row.priority,
                "state": row.state,
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
                "error": row.error,
                "dedupe_key": row.dedupe_key,
                "lease_until": row.lease_until,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            }

    async def stats(self, *, tenant_id: str | None = None) -> dict:
        """队列统计：按状态/类型计数 + 近 24h 每小时创建量（趋势）。"""
        async with self.sessions() as s:
            q = select(JobRow)
            if tenant_id:
                q = q.where(JobRow.tenant_id == tenant_id)
            rows = (await s.scalars(q)).all()
        now = _now()
        by_state: dict[str, int] = {}
        by_type: dict[str, int] = {}
        buckets: dict[int, int] = {}
        for r in rows:
            by_state[r.state] = by_state.get(r.state, 0) + 1
            by_type[r.job_type] = by_type.get(r.job_type, 0) + 1
            created = r.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                hours_ago = int((now - created).total_seconds() // 3600)
                if 0 <= hours_ago < 24:
                    buckets[hours_ago] = buckets.get(hours_ago, 0) + 1
        trend = [{"hours_ago": h, "count": buckets.get(h, 0)} for h in range(23, -1, -1)]
        return {"by_state": by_state, "by_type": by_type, "trend": trend, "total": len(rows)}

    # ---------- 队列深度采样（§11 监控） ----------
    async def save_sample(self, stats: dict) -> None:
        """落一次队列深度采样（按状态计数），并只保留近 24h。"""
        import uuid

        async with self.sessions() as s:
            s.add(
                QueueSampleRow(
                    id=uuid.uuid4().hex[:16],
                    tenant_id="",
                    sampled_at=_now(),
                    by_state=json.dumps(stats.get("by_state") or {}, ensure_ascii=False),
                    total=int(stats.get("total") or 0),
                )
            )
            cutoff = _now() - timedelta(hours=24)
            await s.execute(delete(QueueSampleRow).where(QueueSampleRow.sampled_at < cutoff))
            await s.commit()

    async def depth_trend(self, hours: int = 24) -> list[dict]:
        """队列深度趋势（真实采样）：每小时取该小时最后一刻的 total。"""
        async with self.sessions() as s:
            rows = await s.scalars(select(QueueSampleRow).order_by(QueueSampleRow.sampled_at))
            samples = [(r.sampled_at, r.total) for r in rows]
        now = _now()
        hourly: dict[int, int] = {}
        for ts, total in samples:
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            hours_ago = int((now - ts).total_seconds() // 3600)
            if 0 <= hours_ago < hours:
                hourly[hours_ago] = total  # 同一小时取最新样本
        return [{"hours_ago": h, "count": hourly.get(h, 0)} for h in range(hours - 1, -1, -1)]

    async def list_in_state(self, state: str) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(select(JobRow).where(JobRow.state == state))
            return [r.job_id for r in rows]

    async def cancel(self, job_id: str) -> str:
        """§11.2 取消：CREATED/QUEUED -> CANCELLED（RUNNING 交由 Worker 自行退出）。返回新状态。"""
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                return "NOT_FOUND"
            if row.state in ("CREATED", "QUEUED"):
                row.state = "CANCELLED"
                row.finished_at = _now()
            await s.commit()
            return row.state

    async def expire_old(self, ttl_s: int = 3600) -> list[str]:
        """§11.2 EXPIRED：QUEUED 超龄（TTL）=> EXPIRED（清理堆积僵尸任务）。"""
        cutoff = _now() - timedelta(seconds=ttl_s)
        async with self.sessions() as s:
            rows = await s.scalars(
                select(JobRow).where(JobRow.state.in_(["CREATED", "QUEUED"]))  # 待处理状态都可过期
            )
            expired: list[str] = []
            for r in rows:
                created = r.created_at
                if created.tzinfo is None:  # SQLite 返回 naive，统一按 aware 比较
                    created = created.replace(tzinfo=UTC)
                if created <= cutoff:  # SQLite 秒精度，`<=` 保证 ttl=0 也生效
                    r.state = "EXPIRED"
                    expired.append(r.job_id)
            await s.commit()
            return expired

    async def requeue(self, job_id: str) -> dict:
        """DLQ 重放：DEAD_LETTER -> CREATED，清空 attempts/error（可再次被认领）。"""
        async with self.sessions() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                return {"job_id": job_id, "state": "NOT_FOUND"}
            if row.state != "DEAD_LETTER":
                return {"job_id": job_id, "state": row.state, "skipped": True}
            row.state = "CREATED"
            row.attempts = 0
            row.error = None
            row.lease_until = None
            await s.commit()
            return {"job_id": job_id, "state": "CREATED", "skipped": False}
