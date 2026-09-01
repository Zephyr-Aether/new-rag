"""Knowledge API（§32 MVP 子集）：

POST /knowledge/documents    ingest 一篇 Markdown 文档（解析→分块→embedding→入库）
POST /knowledge/documents/upload   上传文件（TXT/MD/PDF/DOC/DOCX/CSV/Excel）解析后入库
POST /knowledge/search       混合检索（向量 + BM25 + RRF）
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject, require_perm
from app.knowledge.importers import ImportError_, clean_document, parse_document
from app.knowledge.retrieval import RetrievalRequest, RetrievalResult
from app.knowledge.upload import UploadSessionError
from app.state import AppState

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class IngestRequest(BaseModel):
    document_id: str
    title: str
    text: str
    source_uri: str = ""
    permission: str = ""
    kb_id: str = "default"  # §15.5 归属知识库


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=20, ge=1, le=100)
    rerank_n: int = Field(default=5, ge=1, le=20)
    kb_filter: str | None = None
    kb_id: str | None = None  # §15.5 限定知识库
    permission: str | None = None  # §15.6 权限前置过滤


class BaseRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    retrieval_config: dict | None = None


class BaseConfigRequest(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=100)
    bm25_top_k: int | None = Field(default=None, ge=1, le=200)
    rerank_n: int | None = Field(default=None, ge=1, le=20)


@router.get("/bases")
async def list_bases(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.5 知识库列表（含库级检索配置）。"""
    state: AppState = request.app.state.agent
    rows = await state.knowledge_service.store.list_bases(subject.tenant_id)
    return {"bases": rows}


@router.post("/bases")
async def create_base(
    body: BaseRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    kb_id = await state.knowledge_service.store.create_base(
        tenant_id=subject.tenant_id,
        name=body.name,
        description=body.description,
        retrieval_config=body.retrieval_config,
    )
    return {"kb_id": kb_id, "name": body.name}


@router.put("/bases/{kb_id}/config")
async def update_base_config(
    kb_id: str,
    body: BaseConfigRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.5 库级检索参数配置：top_k / bm25_top_k / rerank_n。"""
    state: AppState = request.app.state.agent
    cfg = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = await state.knowledge_service.store.update_base_config(
        tenant_id=subject.tenant_id, kb_id=kb_id, config=cfg
    )
    if not ok:
        raise AgentError(f"knowledge base not found: {kb_id}", code="KB_NOT_FOUND")
    return {"kb_id": kb_id, "retrieval_config": cfg}


@router.put("/bases/{kb_id}")
async def rename_base(
    kb_id: str,
    body: BaseRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    ok = await state.knowledge_service.store.rename_base(
        tenant_id=subject.tenant_id, kb_id=kb_id, name=body.name
    )
    if not ok:
        raise AgentError(f"knowledge base not found: {kb_id}", code="KB_NOT_FOUND")
    return {"kb_id": kb_id, "name": body.name}


@router.delete("/bases/{kb_id}")
async def delete_base(
    kb_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    ok = await state.knowledge_service.store.delete_base(tenant_id=subject.tenant_id, kb_id=kb_id)
    if not ok:
        raise AgentError(f"知识库不存在或为默认库不可删: {kb_id}", code="KB_NOT_FOUND")
    return {"kb_id": kb_id, "deleted": True}


async def _extract_to_graph(state: AppState, tenant_id: str, document_id: str, title: str, text: str) -> int:
    """§16 入库自动抽取：把文档事实抽取入知识图谱（失败不影响入库主流程）。"""
    try:
        facts = await state.graph_extractor.extract(text)
        added = 0
        for f in facts:
            try:
                await state.graph_service.add_fact(
                    tenant_id=tenant_id,
                    subject=str(f["subject"]),
                    predicate=str(f["predicate"]),
                    object=str(f["object"]),
                    confidence=float(f.get("confidence") or 0.6),
                    source_doc=document_id,
                    source_chunk=f"{title}#auto",
                    extracted_by=str(f.get("extracted_by") or "auto"),
                )
                added += 1
            except Exception:  # noqa: BLE001 单条失败跳过
                continue
        return added
    except Exception:  # noqa: BLE001
        return 0


class PreviewRequest(BaseModel):
    text: str


@router.post("/preview")
async def preview_clean(
    body: PreviewRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.6 清洗预览：返回清洗后的文本与预估分块数（入库前给用户确认）。"""
    from app.knowledge.chunker import chunk_markdown

    cleaned = clean_document(body.text)
    pieces = chunk_markdown(cleaned)
    return {"cleaned": cleaned, "chunks": len(pieces), "characters": len(cleaned)}


@router.post("/documents")
async def ingest_document(
    body: IngestRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("kb:ingest", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    text = clean_document(body.text)  # §15.6 文档清洗：去噪/规范化后再分块
    if not text:
        raise AgentError("文档清洗后为空", code="EMPTY_CONTENT")
    chunks = await state.knowledge_service.ingest_markdown(
        tenant_id=subject.tenant_id,
        document_id=body.document_id,
        title=body.title,
        text=text,
        source_uri=body.source_uri,
        permission=body.permission,
        kb_id=body.kb_id,
    )
    facts = await _extract_to_graph(state, subject.tenant_id, body.document_id, body.title, text)
    return {"document_id": body.document_id, "chunks": chunks, "status": "READY", "graph_facts": facts}


@router.post("/documents/upload")
async def upload_document(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("kb:ingest", "*"))],
    file: Annotated[UploadFile, File(...)],
    title: str = Form(""),
    document_id: str = Form(""),
    kb_id: str = Form("default"),
) -> dict:
    """§15.4 上传文件解析入库：TXT/Markdown/PDF/DOC/DOCX 直接入库；CSV/Excel 按（问题,答案）转 FAQ。"""
    state: AppState = request.app.state.agent
    data = await file.read()
    if not data:
        raise AgentError("empty file", code="EMPTY_FILE")
    max_bytes = state.settings.max_upload_bytes
    if len(data) > max_bytes:
        raise AgentError(
            f"文件超过上限：{len(data)} > {max_bytes}（可调大 APP_MAX_UPLOAD_BYTES）", code="UPLOAD_TOO_LARGE"
        )
    try:
        text = parse_document(file.filename or "upload.txt", data)
    except ImportError_ as exc:
        raise AgentError(str(exc), code="IMPORT_FAILED") from exc
    if not text.strip():
        raise AgentError("未从文件提取到文本内容", code="EMPTY_CONTENT")
    doc_id = document_id.strip() or f"doc-{uuid.uuid4().hex[:8]}"
    doc_title = title.strip() or (file.filename or doc_id)
    chunks = await state.knowledge_service.ingest_markdown(
        tenant_id=subject.tenant_id,
        document_id=doc_id,
        title=doc_title,
        text=text,
        source_uri=file.filename or "",
        kb_id=kb_id,
    )
    facts = await _extract_to_graph(state, subject.tenant_id, doc_id, doc_title, text)
    return {
        "document_id": doc_id,
        "title": doc_title,
        "chunks": chunks,
        "status": "READY",
        "kb_id": kb_id,
        "graph_facts": facts,
    }


class UploadInitRequest(BaseModel):
    filename: str
    size: int = Field(ge=0)  # 上限由运行时校验（可配 APP_MAX_UPLOAD_BYTES，避免 pydantic 422 太晦涩）
    chunk_size: int = Field(default=1024 * 1024, ge=64 * 1024, le=10 * 1024 * 1024)
    title: str = ""
    kb_id: str = "default"


@router.post("/upload/init")
async def upload_init(
    body: UploadInitRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.7 分片上传初始化：创建会话，返回 upload_id / chunk_size / total_chunks。"""
    state: AppState = request.app.state.agent
    try:
        upload_id = await state.upload_manager.init(
            tenant_id=subject.tenant_id,
            filename=body.filename,
            size=body.size,
            chunk_size=body.chunk_size,
            title=body.title,
            kb_id=body.kb_id,
        )
    except UploadSessionError as exc:
        raise AgentError(str(exc), code="UPLOAD_TOO_LARGE") from exc
    total = (body.size + body.chunk_size - 1) // body.chunk_size if body.size else 0
    return {"upload_id": upload_id, "chunk_size": body.chunk_size, "total_chunks": total}


@router.post("/upload/{upload_id}/chunks/{index}")
async def upload_chunk(
    upload_id: str,
    index: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    file: Annotated[UploadFile, File(...)],
) -> dict:
    """§15.7 上传一个分片（index 从 0 开始）。"""
    state: AppState = request.app.state.agent
    data = await file.read()
    try:
        await state.upload_manager.save_chunk(upload_id, index, data, tenant_id=subject.tenant_id)
    except UploadSessionError as exc:
        raise AgentError(str(exc), code="UPLOAD_NOT_FOUND") from exc
    return {"upload_id": upload_id, "received": index}


@router.get("/upload/{upload_id}/status")
async def upload_status(
    upload_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.7 已上传分片（断点续传：客户端跳过已上传部分）。"""
    state: AppState = request.app.state.agent
    st = await state.upload_manager.status(upload_id, tenant_id=subject.tenant_id)
    if st is None:
        raise AgentError(f"upload session not found: {upload_id}", code="UPLOAD_NOT_FOUND")
    return st


@router.post("/upload/{upload_id}/complete")
async def upload_complete(
    upload_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("kb:ingest", "*"))],
) -> dict:
    """§15.7 分片拼装 + 清洗 + 入库（成功后清理会话）。"""
    state: AppState = request.app.state.agent
    try:
        buf, meta = await state.upload_manager.assemble(upload_id, tenant_id=subject.tenant_id)
    except UploadSessionError as exc:
        raise AgentError(str(exc), code="UPLOAD_INCOMPLETE") from exc
    try:
        text = parse_document(meta["filename"], buf)
    except ImportError_ as exc:
        await state.upload_manager.cleanup(upload_id, tenant_id=subject.tenant_id)
        raise AgentError(str(exc), code="IMPORT_FAILED") from exc
    if not text.strip():
        await state.upload_manager.cleanup(upload_id, tenant_id=subject.tenant_id)
        raise AgentError("未从文件提取到文本内容", code="EMPTY_CONTENT")
    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    doc_title = meta.get("title") or meta["filename"]
    chunks = await state.knowledge_service.ingest_markdown(
        tenant_id=subject.tenant_id,
        document_id=doc_id,
        title=doc_title,
        text=text,
        source_uri=meta["filename"],
        kb_id=meta.get("kb_id", "default"),
    )
    facts = await _extract_to_graph(state, subject.tenant_id, doc_id, doc_title, text)
    await state.upload_manager.cleanup(upload_id)
    return {
        "document_id": doc_id,
        "title": doc_title,
        "chunks": chunks,
        "status": "READY",
        "kb_id": meta.get("kb_id"),
        "graph_facts": facts,
    }


@router.get("/documents")
async def list_documents(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    kb_id: str | None = None,
) -> dict:
    """§15.4 文档列表（前端知识库页；可按知识库过滤）。"""
    state: AppState = request.app.state.agent
    rows = await state.knowledge_service.store.list_documents(subject.tenant_id, kb_id=kb_id)
    return {"rows": rows, "total": len(rows)}


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.4 查看文档详情 + 切分后的 chunks（前端点开文档看内容）。"""
    state: AppState = request.app.state.agent
    doc = await state.knowledge_service.store.get_document(
        tenant_id=subject.tenant_id, document_id=document_id
    )
    if doc is None:
        raise AgentError(f"document not found: {document_id}", code="DOCUMENT_NOT_FOUND")
    chunks = await state.knowledge_service.store.list_chunks(
        tenant_id=subject.tenant_id, document_id=document_id
    )
    return {**doc, "chunks": chunks}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§15.4 删除文档及其 chunks。"""
    state: AppState = request.app.state.agent
    ok = await state.knowledge_service.delete_document(tenant_id=subject.tenant_id, document_id=document_id)
    if not ok:
        raise AgentError(f"document not found: {document_id}", code="DOCUMENT_NOT_FOUND")
    return {"document_id": document_id, "deleted": True}


@router.post("/search", response_model=RetrievalResult)
async def search(
    body: SearchRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> RetrievalResult:
    state: AppState = request.app.state.agent
    return await state.knowledge_service.search(
        RetrievalRequest(
            query=body.query,
            tenant_id=subject.tenant_id,
            top_k=body.top_k,
            bm25_top_k=body.top_k,
            rerank_n=body.rerank_n,
            kb_filter=body.kb_filter,
            kb_id=body.kb_id,
            permission=body.permission,
        )
    )
