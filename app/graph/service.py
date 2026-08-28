"""GraphService（§16）：add_fact / retrieve（子图检索） + graph.query 工具。"""

from app.common.contracts import Subject
from app.graph.store import GraphStore
from app.tool.registry import ToolDefinition, ToolRegistry


class GraphService:
    def __init__(self, store: GraphStore):
        self.store = store

    async def add_fact(
        self,
        *,
        tenant_id: str,
        subject: str,
        predicate: str,
        object: str,
        aliases: list[str] | None = None,
        confidence: float = 0.9,
        source_doc: str = "",
        source_chunk: str = "",
        source_version: str = "",
        extracted_by: str = "",
    ) -> str:
        # 先规范化实体（别名入实体）
        await self.store.upsert_entity(tenant_id=tenant_id, name=subject, aliases=aliases)
        await self.store.upsert_entity(tenant_id=tenant_id, name=object)
        return await self.store.add_fact(
            tenant_id=tenant_id,
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            source_doc=source_doc,
            source_chunk=source_chunk,
            source_version=source_version,
            extracted_by=extracted_by,
        )

    async def merge_entity(self, *, tenant_id: str, from_name: str, to_name: str) -> dict:
        """§16 实体消歧：合并别名到规范化实体（事实重指向 + 别名归属）。"""
        await self.store.merge_entity(tenant_id=tenant_id, from_name=from_name, to_name=to_name)
        return {"from": from_name, "into": to_name}

    async def retrieve(self, *, query: str, tenant_id: str, k: int = 5) -> list[dict]:
        """§16.8 图检索：从查询文本检测实体，返回其子图事实（provenance 可回源）。"""
        entities = await self.store.entities(tenant_id=tenant_id)
        detected: list[str] = []
        for e in entities:
            if e["name"] in query or any(a in query for a in e["aliases"]):
                detected.append(e["name"])
        if not detected:
            return []
        facts: list[dict] = []
        seen: set[str] = set()
        for entity in detected:
            for f in await self.store.query_entity(tenant_id=tenant_id, entity=entity, k=k):
                if f["fact_id"] not in seen:
                    seen.add(f["fact_id"])
                    facts.append(f)
        facts.sort(key=lambda f: f["confidence"], reverse=True)
        return facts[:k]

    async def add_facts_merged(self, *, tenant_id: str, facts: list[dict]) -> dict:
        """§16 跨文档去重/合并：
        - 同 (subject,predicate,object) 已 ACTIVE => 去重（保留原事实，不重复建链）
        - 同 (subject,predicate) 不同 object => 冲突，新值胜出（旧值 SUPERSEDED）
        """
        added = deduped = 0
        for f in facts:
            subject, predicate = f["subject"], f["predicate"]
            existing = await self.store.find_active_fact(
                tenant_id=tenant_id, subject=subject, predicate=predicate
            )
            if existing is not None and existing["object"] == f["object"]:
                # §16 跨文档去重：不重复建链，但合并来源（provenance 多源保留）
                deduped += 1
                if f.get("source_doc"):
                    await self.store.add_source(existing["fact_id"], f["source_doc"])
                continue
            await self.add_fact(
                tenant_id=tenant_id,
                subject=subject,
                predicate=predicate,
                object=f["object"],
                confidence=f.get("confidence", 0.85),
                source_doc=f.get("source_doc", ""),
                source_chunk=f.get("source_chunk", ""),
                source_version=f.get("source_version", ""),
                extracted_by=f.get("extracted_by", "llm"),
            )
            added += 1
        return {"added": added, "deduped": deduped}


def register_graph_tool(registry: ToolRegistry, service: GraphService) -> None:
    """图检索工具（§16.8 Agentic Graph：查询 → 子图 → Context）。"""

    async def _graph_query(subject: Subject, query: str, k: int = 5) -> list[dict]:
        return await service.retrieve(query=query, tenant_id=subject.tenant_id, k=k)

    registry.register(
        ToolDefinition(
            ref="graph.query",
            description=(
                "查询知识图谱中实体（人物/组织/产品/流程等）的关系事实，如谁负责某流程、某流程依赖什么、"
                "某人的角色/归属。当用户问这类关系/归属问题、且可能来自内部文档时，必须调用本工具检索；"
                "无结果再结合其它知识回答。返回带来源与置信度的事实。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "含实体名的查询"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["query"],
            },
            fn=_graph_query,
            permission="graph:query",
            context_aware=True,
        )
    )
