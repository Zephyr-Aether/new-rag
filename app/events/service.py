"""EventOutbox（§28.2）：幂等事件发布 / 查询 / 重放。

- publish：同 dedupe_key 已存在则返回既有事件（幂等，可追踪）。
- list_events：按租户/类型查询。
- replay：按 aggregate 取回事件集（供重新投递）。
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.storage.models import EventRow


class EventOutbox:
    def __init__(self, sessions):
        self.sessions = sessions

    async def publish(
        self,
        *,
        event_type: str,
        tenant_id: str,
        aggregate_id: str = "",
        payload: dict | None = None,
        dedupe_key: str | None = None,
    ) -> dict:
        """幂等发布：同 dedupe_key 已存在则返回既有事件，不重复落。"""
        if dedupe_key:
            async with self.sessions() as s:
                existing = await s.scalar(select(EventRow).where(EventRow.dedupe_key == dedupe_key))
                if existing is not None:
                    return {"event_id": existing.id, "duplicated": True}
        event_id = uuid.uuid4().hex
        async with self.sessions() as s:
            s.add(
                EventRow(
                    id=event_id,
                    event_type=event_type,
                    tenant_id=tenant_id,
                    aggregate_id=aggregate_id,
                    payload_json=json.dumps(payload or {}, ensure_ascii=False),
                    dedupe_key=dedupe_key,
                )
            )
            await s.commit()
        return {"event_id": event_id, "duplicated": False}

    async def list_events(
        self, *, tenant_id: str | None = None, event_type: str | None = None, limit: int = 100
    ) -> list[dict]:
        async with self.sessions() as s:
            q = select(EventRow)
            if tenant_id:
                q = q.where(EventRow.tenant_id == tenant_id)
            if event_type:
                q = q.where(EventRow.event_type == event_type)
            rows = (await s.scalars(q.order_by(EventRow.created_at.desc()).limit(limit))).all()
            return [
                {
                    "event_id": r.id,
                    "event_type": r.event_type,
                    "tenant_id": r.tenant_id,
                    "aggregate_id": r.aggregate_id,
                    "payload": json.loads(r.payload_json or "{}"),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    async def stats(self, *, tenant_id: str | None = None, hours: int = 24) -> dict:
        """事件统计：按类型计数 + 近 N 小时每小时发布量（监控图用）。"""
        async with self.sessions() as s:
            q = select(EventRow)
            if tenant_id:
                q = q.where(EventRow.tenant_id == tenant_id)
            rows = (await s.scalars(q)).all()
        now = datetime.now(UTC)
        by_type: dict[str, int] = {}
        buckets: dict[int, int] = {}
        for r in rows:
            by_type[r.event_type] = by_type.get(r.event_type, 0) + 1
            created = r.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                hours_ago = int((now - created).total_seconds() // 3600)
                if 0 <= hours_ago < hours:
                    buckets[hours_ago] = buckets.get(hours_ago, 0) + 1
        trend = [{"hours_ago": h, "count": buckets.get(h, 0)} for h in range(hours - 1, -1, -1)]
        return {"by_type": by_type, "trend": trend, "total": len(rows)}

    async def replay(self, *, tenant_id: str, aggregate_id: str) -> list[dict]:
        """§28.2 可重放：按 aggregate 取回全部事件（供重新投递）。"""
        async with self.sessions() as s:
            rows = await s.scalars(
                select(EventRow).where(EventRow.tenant_id == tenant_id, EventRow.aggregate_id == aggregate_id)
            )
            return [
                {
                    "event_id": r.id,
                    "event_type": r.event_type,
                    "aggregate_id": r.aggregate_id,
                    "payload": json.loads(r.payload_json or "{}"),
                }
                for r in rows
            ]
