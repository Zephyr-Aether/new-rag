"""MemoryStore：记忆持久化 + 作用域隔离（§12.2）。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.storage.models import MemoryRow


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    def __init__(self, sessions):
        self.sessions = sessions

    async def add(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_id: str | None,
        scope: str,
        memory_type: str,
        content: str,
        source: str = "",
        source_trust: str = "trusted",
        confidence: float = 1.0,
        ttl_days: int | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        import json
        import uuid

        memory_id = uuid.uuid4().hex
        ttl_at = _now() + timedelta(days=ttl_days) if ttl_days else None
        async with self.sessions() as s:
            s.add(
                MemoryRow(
                    id=memory_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    scope=scope,
                    memory_type=memory_type,
                    content=content,
                    source=source,
                    source_trust=source_trust,
                    confidence=confidence,
                    ttl_at=ttl_at,
                    embedding=json.dumps(embedding) if embedding else "[]",
                )
            )
            await s.commit()
        return memory_id

    async def recall(self, *, tenant_id: str, user_id: str, agent_id: str | None, k: int) -> list[dict]:
        """§12.2 严格隔离：先钉死 tenant+user scope，再做召回。"""
        import json

        now = _now()
        async with self.sessions() as s:
            q = select(MemoryRow).where(
                MemoryRow.tenant_id == tenant_id,
                MemoryRow.user_id == user_id,
                MemoryRow.deleted_at.is_(None),
            )
            if agent_id:
                q = q.where(MemoryRow.agent_id.is_(None) | (MemoryRow.agent_id == agent_id))
            q = q.where(MemoryRow.ttl_at.is_(None) | (MemoryRow.ttl_at > now)).order_by(
                MemoryRow.updated_at.desc()
            )
            rows = (await s.scalars(q)).all()
            return [
                {
                    "memory_id": r.id,
                    "scope": r.scope,
                    "memory_type": r.memory_type,
                    "content": r.content,
                    "source": r.source,
                    "source_trust": r.source_trust,
                    "confidence": r.confidence,
                    "created_at": r.created_at,
                    "embedding": json.loads(r.embedding or "[]"),
                }
                for r in rows[:k]
            ]

    async def delete(self, *, tenant_id: str, user_id: str, memory_id: str) -> bool:
        async with self.sessions() as s:
            row = await s.get(MemoryRow, memory_id)
            if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
                return False
            row.deleted_at = _now()
            await s.commit()
            return True
