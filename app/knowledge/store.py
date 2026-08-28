"""KnowledgeStore：文档/块持久化 + 检索原语（§15.4 / §24 租户分区）。

MVP：SQLite 用 JSON 向量 + 暴力 cosine；
Postgres 用 pgvector：`embedding::vector(64)` 表达式 + HNSW 索引 + SQL 距离检索（§8.3.3 / §23）。
§24 分片：`shard = hash(tenant_id) % shard_count`，每个租户落在单一分区，检索只扫该分区。
"""

import hashlib
import json

from sqlalchemy import delete, func, select, text

from app.knowledge.embedding import cosine
from app.storage.models import ChunkRow, DocumentRow, KnowledgeBaseRow


class KnowledgeStore:
    def __init__(self, sessions, *, shard_count: int = 1):
        self.sessions = sessions
        self.shard_count = max(1, shard_count)
        self._is_pg: bool | None = None

    def shard_for(self, tenant_id: str) -> int:
        """§24 租户分区：同一租户稳定落在同一 shard。"""
        return int(hashlib.md5(tenant_id.encode()).hexdigest(), 16) % self.shard_count

    async def is_postgres(self) -> bool:
        if self._is_pg is None:
            async with self.sessions() as s:
                self._is_pg = s.bind is not None and s.bind.dialect.name == "postgresql"
        return self._is_pg

    async def setup_pgvector(self) -> None:
        """§8.3.3/§23：建 vector 扩展 + HNSW 索引（幂等，仅 Postgres 生效）。"""
        if not await self.is_postgres():
            return
        async with self.sessions() as s:
            await s.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await s.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_chunks_hnsw "
                    "ON chunks USING hnsw ((embedding::vector(64)) vector_cosine_ops)"
                )
            )
            await s.commit()

    async def vector_search(
        self,
        tenant_id: str,
        qvec: list[float],
        top_k: int,
        permission: str | None = None,
        shard: int | None = None,
        kb_id: str | None = None,
    ) -> list[dict]:
        """向量检索：Postgres 走 pgvector SQL（含权限/分区过滤）；SQLite 暴力余弦。"""
        if await self.is_postgres():
            vec_literal = "[" + ",".join(str(x) for x in qvec) + "]"
            shard_clause = " AND shard = :shard " if shard is not None else ""
            kb_clause = " AND kb_id = :kb " if kb_id is not None else ""
            sql = (
                "SELECT chunk_id, document_id, seq, section, source, text, token_count, permission, "
                "(1 - (embedding::vector(64) <=> CAST(:vec AS vector(64)))) AS vector_score "
                "FROM chunks "
                "WHERE tenant_id = :tenant "
                + shard_clause
                + kb_clause
                + "AND (CAST(:perm AS text) IS NULL OR permission = '' OR permission = CAST(:perm AS text)) "
                "ORDER BY embedding::vector(64) <=> CAST(:vec AS vector(64)) LIMIT :k"
            )
            params: dict = {"tenant": tenant_id, "vec": vec_literal, "perm": permission, "k": top_k}
            if shard is not None:
                params["shard"] = shard
            if kb_id is not None:
                params["kb"] = kb_id
            async with self.sessions() as s:
                rows = await s.execute(text(sql), params)
                return [
                    {
                        "chunk_id": r.chunk_id,
                        "document_id": r.document_id,
                        "seq": r.seq,
                        "section": r.section or "",
                        "source": r.source or "",
                        "text": r.text,
                        "token_count": r.token_count,
                        "permission": r.permission or "",
                        "vector_score": float(r.vector_score),
                    }
                    for r in rows
                ]
        chunks = await self.all_chunks(tenant_id, shard=shard, kb_id=kb_id)
        if permission:
            chunks = [c for c in chunks if not c["permission"] or c["permission"] == permission]
        for c in chunks:
            c["vector_score"] = cosine(qvec, c["embedding"])
        chunks.sort(key=lambda c: c["vector_score"], reverse=True)
        return chunks[:top_k]

    # ---------- knowledge bases（§15.5 多库） ----------
    async def list_bases(self, tenant_id: str) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(
                select(KnowledgeBaseRow)
                .where(KnowledgeBaseRow.tenant_id == tenant_id)
                .order_by(KnowledgeBaseRow.created_at)
            )
            doc_rows = await s.execute(
                select(DocumentRow.kb_id, func.count())
                .where(DocumentRow.tenant_id == tenant_id)
                .group_by(DocumentRow.kb_id)
            )
            doc_counts = dict(doc_rows.all())
            return [
                {
                    "kb_id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "retrieval_config": json.loads(r.retrieval_config or "{}"),
                    "doc_count": doc_counts.get(r.id, 0),
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    async def create_base(
        self, *, tenant_id: str, name: str, description: str = "", retrieval_config: dict | None = None
    ) -> str:
        import uuid

        kb_id = uuid.uuid4().hex[:8]
        async with self.sessions() as s:
            s.add(
                KnowledgeBaseRow(
                    id=kb_id,
                    tenant_id=tenant_id,
                    name=name,
                    description=description,
                    retrieval_config=json.dumps(retrieval_config or {}, ensure_ascii=False),
                )
            )
            await s.commit()
        return kb_id

    async def get_base_config(self, *, tenant_id: str, kb_id: str) -> dict:
        async with self.sessions() as s:
            row = await s.get(KnowledgeBaseRow, kb_id)
            if row is None or row.tenant_id != tenant_id:
                return {}
            return json.loads(row.retrieval_config or "{}")

    async def update_base_config(self, *, tenant_id: str, kb_id: str, config: dict) -> bool:
        async with self.sessions() as s:
            row = await s.get(KnowledgeBaseRow, kb_id)
            if row is None or row.tenant_id != tenant_id:
                return False
            merged = json.loads(row.retrieval_config or "{}")
            merged.update(config)
            row.retrieval_config = json.dumps(merged, ensure_ascii=False)
            await s.commit()
            return True

    async def ensure_default_base(self, tenant_id: str) -> None:
        """确保 `default` 知识库行存在（id 全局唯一，被占用则跳过）。"""
        async with self.sessions() as s:
            row = await s.get(KnowledgeBaseRow, "default")
            if row is None:
                s.add(KnowledgeBaseRow(id="default", tenant_id=tenant_id, name="默认知识库", description=""))
                await s.commit()

    async def rename_base(self, *, tenant_id: str, kb_id: str, name: str) -> bool:
        async with self.sessions() as s:
            row = await s.get(KnowledgeBaseRow, kb_id)
            if row is None or row.tenant_id != tenant_id:
                return False
            row.name = name
            await s.commit()
            return True

    async def delete_base(self, *, tenant_id: str, kb_id: str) -> bool:
        """删除知识库及其全部文档/chunks；默认库（default）不可删。"""
        async with self.sessions() as s:
            row = await s.get(KnowledgeBaseRow, kb_id)
            if row is None or row.tenant_id != tenant_id or kb_id == "default":
                return False
            await s.execute(delete(ChunkRow).where(ChunkRow.tenant_id == tenant_id, ChunkRow.kb_id == kb_id))
            await s.execute(
                delete(DocumentRow).where(DocumentRow.tenant_id == tenant_id, DocumentRow.kb_id == kb_id)
            )
            await s.delete(row)
            await s.commit()
            return True

    # ---------- document ----------
    async def upsert_document(
        self,
        *,
        document_id: str,
        tenant_id: str,
        kb_id: str,
        owner_id: str,
        title: str,
        source_uri: str,
        hash: str,
    ) -> None:
        async with self.sessions() as s:
            row = await s.get(DocumentRow, document_id)
            if row is None:
                s.add(
                    DocumentRow(
                        id=document_id,
                        tenant_id=tenant_id,
                        kb_id=kb_id,
                        owner_id=owner_id,
                        title=title,
                        source_uri=source_uri,
                        hash=hash,
                        status="READY",
                    )
                )
            else:
                row.status = "READY"
                row.hash = hash
                row.kb_id = kb_id
            await s.commit()

    async def delete_document_chunks(self, *, tenant_id: str, document_id: str) -> None:
        async with self.sessions() as s:
            await s.execute(
                delete(ChunkRow).where(ChunkRow.tenant_id == tenant_id, ChunkRow.document_id == document_id)
            )
            await s.commit()

    # ---------- chunk ----------
    async def add_chunks(self, *, tenant_id: str, chunks: list[dict]) -> None:
        shard = self.shard_for(tenant_id)
        async with self.sessions() as s:
            for c in chunks:
                s.add(
                    ChunkRow(
                        chunk_id=c["chunk_id"],
                        tenant_id=tenant_id,
                        kb_id=c.get("kb_id", "default"),
                        document_id=c["document_id"],
                        seq=c["seq"],
                        section=c.get("section", ""),
                        source=c.get("source", ""),
                        text=c["text"],
                        token_count=c.get("token_count", 0),
                        embedding=json.dumps(c["embedding"]),
                        permission=c.get("permission", ""),
                        meta_json=json.dumps(c.get("meta", {}), ensure_ascii=False),
                        hash=c.get("hash", ""),
                        shard=shard,
                    )
                )
            await s.commit()

    async def all_chunks(
        self, tenant_id: str, shard: int | None = None, kb_id: str | None = None
    ) -> list[dict]:
        q = select(ChunkRow).where(ChunkRow.tenant_id == tenant_id)
        if shard is not None:
            q = q.where(ChunkRow.shard == shard)
        if kb_id is not None:
            q = q.where(ChunkRow.kb_id == kb_id)
        async with self.sessions() as s:
            rows = await s.scalars(q)
            return [
                {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "kb_id": r.kb_id,
                    "seq": r.seq,
                    "section": r.section,
                    "source": r.source,
                    "text": r.text,
                    "token_count": r.token_count,
                    "embedding": json.loads(r.embedding),
                    "permission": r.permission,
                    "shard": r.shard,
                }
                for r in rows
            ]

    async def list_documents(self, tenant_id: str, kb_id: str | None = None) -> list[dict]:
        """§15.4 文档列表（前端知识库页；可按知识库过滤，含分块数）。"""
        q = select(DocumentRow).where(DocumentRow.tenant_id == tenant_id)
        if kb_id is not None:
            q = q.where(DocumentRow.kb_id == kb_id)
        async with self.sessions() as s:
            rows = await s.scalars(q.order_by(DocumentRow.created_at.desc()))
            docs = list(rows)
            # 每个文档的分块数
            count_rows = await s.execute(
                select(ChunkRow.document_id, func.count())
                .where(ChunkRow.tenant_id == tenant_id)
                .group_by(ChunkRow.document_id)
            )
            chunk_counts = dict(count_rows.all())
            return [
                {
                    "document_id": r.id,
                    "title": r.title,
                    "source_uri": r.source_uri,
                    "status": r.status,
                    "created_at": r.created_at,
                    "chunk_count": chunk_counts.get(r.id, 0),
                }
                for r in docs
            ]

    async def get_document(self, *, tenant_id: str, document_id: str) -> dict | None:
        async with self.sessions() as s:
            row = await s.get(DocumentRow, document_id)
            if row is None or row.tenant_id != tenant_id:
                return None
            return {
                "document_id": row.id,
                "title": row.title,
                "source_uri": row.source_uri,
                "status": row.status,
                "created_at": row.created_at,
            }

    async def list_chunks(self, *, tenant_id: str, document_id: str) -> list[dict]:
        """§15.4 文档 chunks（按 seq 排序，前端查看文档内容）。"""
        async with self.sessions() as s:
            rows = await s.scalars(
                select(ChunkRow)
                .where(ChunkRow.tenant_id == tenant_id, ChunkRow.document_id == document_id)
                .order_by(ChunkRow.seq)
            )
            return [
                {
                    "chunk_id": r.chunk_id,
                    "seq": r.seq,
                    "section": r.section,
                    "text": r.text,
                    "token_count": r.token_count,
                }
                for r in rows
            ]

    async def delete_document(self, *, tenant_id: str, document_id: str) -> bool:
        """删除文档及其全部 chunks（§15.4 整体删除）。"""
        async with self.sessions() as s:
            row = await s.get(DocumentRow, document_id)
            if row is None or row.tenant_id != tenant_id:
                return False
            await s.execute(
                delete(ChunkRow).where(ChunkRow.tenant_id == tenant_id, ChunkRow.document_id == document_id)
            )
            await s.delete(row)
            await s.commit()
            return True
