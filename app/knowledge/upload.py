"""知识库文件分片上传（§15.7）：分片存数据库（upload_parts），支持断点续传与进度跟踪。

- init：创建上传会话（upload_sessions），返回 upload_id 与分片数；
- save_chunk：按 (upload_id, index) upsert 一个分片；
- status：已上传分片（客户端据此续传，跳过已传部分）；
- assemble：按序拼装全量字节，调用方解析/清洗/入库后 cleanup。
"""

import uuid

from sqlalchemy import delete, select

from app.storage.models import UploadPartRow, UploadSessionRow

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB 默认总上限（可用 APP_MAX_UPLOAD_BYTES 覆盖）


class UploadSessionError(Exception):
    pass


class UploadManager:
    def __init__(self, sessions, max_bytes: int = MAX_UPLOAD_BYTES):
        self.sessions = sessions
        self.max_bytes = max_bytes

    async def init(
        self,
        *,
        tenant_id: str,
        filename: str,
        size: int,
        chunk_size: int = 1024 * 1024,
        title: str = "",
        kb_id: str = "default",
    ) -> str:
        if size > self.max_bytes:
            raise UploadSessionError(f"file too large: {size} > {self.max_bytes}")
        upload_id = uuid.uuid4().hex[:12]
        total = (int(size) + int(chunk_size) - 1) // int(chunk_size) if size else 0
        async with self.sessions() as s:
            s.add(
                UploadSessionRow(
                    id=upload_id,
                    tenant_id=tenant_id,
                    filename=filename,
                    title=title,
                    kb_id=kb_id,
                    size=int(size),
                    chunk_size=int(chunk_size),
                    total_chunks=total,
                )
            )
            await s.commit()
        return upload_id

    async def _get_owned(self, s, tenant_id: str, upload_id: str) -> UploadSessionRow | None:
        """取本租户的上传会话（跨租户 IDOR 防护，§15.7）。"""
        return await s.scalar(
            select(UploadSessionRow).where(
                UploadSessionRow.id == upload_id, UploadSessionRow.tenant_id == tenant_id
            )
        )

    async def meta(self, upload_id: str, *, tenant_id: str) -> dict | None:
        async with self.sessions() as s:
            row = await self._get_owned(s, tenant_id, upload_id)
            if row is None:
                return None
            return {
                "upload_id": row.id,
                "filename": row.filename,
                "title": row.title,
                "kb_id": row.kb_id,
                "size": row.size,
                "chunk_size": row.chunk_size,
                "total_chunks": row.total_chunks,
            }

    async def save_chunk(self, upload_id: str, index: int, data: bytes, *, tenant_id: str) -> None:
        async with self.sessions() as s:
            if await self._get_owned(s, tenant_id, upload_id) is None:
                raise UploadSessionError(f"upload session not found: {upload_id}")
            part = await s.scalar(
                select(UploadPartRow).where(UploadPartRow.upload_id == upload_id, UploadPartRow.seq == index)
            )
            if part is None:
                s.add(UploadPartRow(id=uuid.uuid4().hex[:16], upload_id=upload_id, seq=index, data=data))
            else:
                part.data = data
            await s.commit()

    async def uploaded_indices(self, upload_id: str) -> list[int]:
        async with self.sessions() as s:
            rows = await s.scalars(select(UploadPartRow.seq).where(UploadPartRow.upload_id == upload_id))
            return sorted(rows.all())

    async def status(self, upload_id: str, *, tenant_id: str) -> dict | None:
        meta = await self.meta(upload_id, tenant_id=tenant_id)
        if meta is None:
            return None
        return {"upload_id": upload_id, "uploaded": await self.uploaded_indices(upload_id), **meta}

    async def assemble(self, upload_id: str, *, tenant_id: str) -> tuple[bytes, dict]:
        meta = await self.meta(upload_id, tenant_id=tenant_id)
        if meta is None:
            raise UploadSessionError(f"upload session not found: {upload_id}")
        indices = await self.uploaded_indices(upload_id)
        if indices != list(range(meta["total_chunks"])):
            raise UploadSessionError(f"incomplete upload: {len(indices)}/{meta['total_chunks']} chunks")
        async with self.sessions() as s:
            parts = await s.scalars(
                select(UploadPartRow).where(UploadPartRow.upload_id == upload_id).order_by(UploadPartRow.seq)
            )
            buf = b"".join(p.data for p in parts)
        await self.cleanup(upload_id, tenant_id=tenant_id)
        return buf, meta

    async def cleanup(self, upload_id: str, *, tenant_id: str) -> None:
        async with self.sessions() as s:
            await s.execute(delete(UploadPartRow).where(UploadPartRow.upload_id == upload_id))
            await s.execute(
                delete(UploadSessionRow).where(
                    UploadSessionRow.id == upload_id, UploadSessionRow.tenant_id == tenant_id
                )
            )
            await s.commit()
