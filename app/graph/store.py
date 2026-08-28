"""GraphStore：实体 / 事实持久化（§16）。"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.storage.models import EntityRow, KnowledgeFactRow


def _now() -> datetime:
    return datetime.now(UTC)


class GraphStore:
    def __init__(self, sessions):
        self.sessions = sessions

    async def upsert_entity(self, *, tenant_id: str, name: str, aliases: list[str] | None = None) -> str:
        """规范化实体（存在则合并别名）。返回实体名。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(EntityRow).where(EntityRow.tenant_id == tenant_id, EntityRow.name == name)
            )
            if row is None:
                s.add(
                    EntityRow(
                        id=uuid.uuid4().hex,
                        tenant_id=tenant_id,
                        name=name,
                        aliases_json=json.dumps(aliases or [], ensure_ascii=False),
                    )
                )
            else:
                existing = set(json.loads(row.aliases_json))
                existing.update(aliases or [])
                row.aliases_json = json.dumps(sorted(existing), ensure_ascii=False)
            await s.commit()
        return name

    async def resolve(self, *, tenant_id: str, name: str) -> str | None:
        """实体消歧：规范化名或别名命中 => 返回规范化名。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(EntityRow).where(EntityRow.tenant_id == tenant_id, EntityRow.name == name)
            )
            if row is not None:
                return row.name
            rows = await s.scalars(select(EntityRow).where(EntityRow.tenant_id == tenant_id))
            for e in rows:
                if name in json.loads(e.aliases_json):
                    return e.name
        return None

    async def entities(self, *, tenant_id: str) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(select(EntityRow).where(EntityRow.tenant_id == tenant_id))
            return [{"name": r.name, "aliases": json.loads(r.aliases_json)} for r in rows]

    async def add_fact(self, *, tenant_id: str, subject: str, predicate: str, object: str, **meta) -> str:
        """插入事实（ACTIVE）。同 (subject,predicate) 旧值 SUPERSEDED（§16.5 冲突）。"""
        fact_id = uuid.uuid4().hex
        async with self.sessions() as s:
            old = await s.scalar(
                select(KnowledgeFactRow).where(
                    KnowledgeFactRow.tenant_id == tenant_id,
                    KnowledgeFactRow.subject_entity == subject,
                    KnowledgeFactRow.predicate == predicate,
                    KnowledgeFactRow.status == "ACTIVE",
                )
            )
            if old is not None:
                old.status = "SUPERSEDED"
            s.add(
                KnowledgeFactRow(
                    fact_id=fact_id,
                    tenant_id=tenant_id,
                    subject_entity=subject,
                    predicate=predicate,
                    object=object,
                    confidence=meta.get("confidence", 0.9),
                    source_doc=meta.get("source_doc", ""),
                    source_chunk=meta.get("source_chunk", ""),
                    source_version=meta.get("source_version", ""),
                    extracted_by=meta.get("extracted_by", ""),
                    sources_json=json.dumps([meta["source_doc"]] if meta.get("source_doc") else []),
                    valid_from=meta.get("valid_from") or _now(),
                    valid_to=meta.get("valid_to"),
                )
            )
            await s.commit()
        return fact_id

    async def add_source(self, fact_id: str, source_doc: str) -> None:
        """§16 跨文档多源：向已存在事实追加来源。"""
        async with self.sessions() as s:
            row = await s.get(KnowledgeFactRow, fact_id)
            if row is not None and source_doc:
                sources = json.loads(row.sources_json)
                if source_doc not in sources:
                    sources.append(source_doc)
                    row.sources_json = json.dumps(sources)
                    await s.commit()

    async def find_active_fact(self, *, tenant_id: str, subject: str, predicate: str) -> dict | None:
        """查同 (subject,predicate) 的当前 ACTIVE 事实（§16.5 冲突/去重用）。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(KnowledgeFactRow).where(
                    KnowledgeFactRow.tenant_id == tenant_id,
                    KnowledgeFactRow.subject_entity == subject,
                    KnowledgeFactRow.predicate == predicate,
                    KnowledgeFactRow.status == "ACTIVE",
                )
            )
        if row is None:
            return None
        return {
            "fact_id": row.fact_id,
            "subject": row.subject_entity,
            "predicate": row.predicate,
            "object": row.object,
            "confidence": row.confidence,
            "source_doc": row.source_doc,
            "sources": json.loads(row.sources_json),
        }

    async def merge_entity(self, *, tenant_id: str, from_name: str, to_name: str) -> None:
        """§16 实体消歧：把 from_name 重定向到 to_name（事实 subject/object 重指向），from_name 归为别名。"""
        async with self.sessions() as s:
            subj = (
                await s.scalars(
                    select(KnowledgeFactRow).where(
                        KnowledgeFactRow.tenant_id == tenant_id, KnowledgeFactRow.subject_entity == from_name
                    )
                )
            ).all()
            obj = (
                await s.scalars(
                    select(KnowledgeFactRow).where(
                        KnowledgeFactRow.tenant_id == tenant_id, KnowledgeFactRow.object == from_name
                    )
                )
            ).all()
            for f in subj:
                f.subject_entity = to_name
            for f in obj:
                f.object = to_name
            await s.commit()
        await self.upsert_entity(tenant_id=tenant_id, name=to_name, aliases=[from_name])

    async def query_entity(self, *, tenant_id: str, entity: str, k: int) -> list[dict]:
        """出边 + 入边事实（ACTIVE + 当前有效）。"""
        now = _now()
        async with self.sessions() as s:
            rows = (
                await s.scalars(
                    select(KnowledgeFactRow)
                    .where(
                        KnowledgeFactRow.tenant_id == tenant_id,
                        KnowledgeFactRow.status == "ACTIVE",
                        KnowledgeFactRow.valid_to.is_(None) | (KnowledgeFactRow.valid_to > now),
                        or_(
                            KnowledgeFactRow.subject_entity == entity,
                            KnowledgeFactRow.object == entity,
                        ),
                    )
                    .order_by(KnowledgeFactRow.confidence.desc())
                )
            ).all()
            return [
                {
                    "fact_id": r.fact_id,
                    "subject": r.subject_entity,
                    "predicate": r.predicate,
                    "object": r.object,
                    "confidence": r.confidence,
                    "source_doc": r.source_doc,
                    "source_chunk": r.source_chunk,
                    "source_version": r.source_version,
                    "sources": json.loads(r.sources_json),
                }
                for r in rows[:k]
            ]
