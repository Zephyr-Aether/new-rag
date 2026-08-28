"""Graph API（§16 MVP 子集）：

POST /graph/facts             写一条事实（含 provenance）
POST /graph/query             子图检索（从查询检测实体）
GET  /graph/entity/{name}     实体详情（出/入边事实）
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common.contracts import Subject
from app.gateway.deps import get_subject, require_perm
from app.state import AppState

router = APIRouter(prefix="/graph", tags=["graph"])


class FactRequest(BaseModel):
    subject: str
    predicate: str
    object: str
    aliases: list[str] | None = None
    confidence: float = Field(default=0.9, ge=0, le=1)
    source_doc: str = ""
    source_chunk: str = ""
    source_version: str = ""


class GraphQueryRequest(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=20)


class ExtractRequest(BaseModel):
    document_id: str
    text: str


class MergeEntityRequest(BaseModel):
    into: str  # 规范化实体名


@router.post("/entities/{name}/merge")
async def merge_entity(
    name: str,
    body: MergeEntityRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("graph:write", "*"))],
) -> dict:
    """§16 实体消歧：把 name 合并进 into（事实重指向 + 别名归属）。"""
    state: AppState = request.app.state.agent
    return await state.graph_service.merge_entity(
        tenant_id=subject.tenant_id, from_name=name, to_name=body.into
    )


@router.post("/extract")
async def extract_facts(
    body: ExtractRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§16 抽取管线：LLM（或规则）从文档抽事实并入库（跨文档去重/合并 + provenance）。"""
    state: AppState = request.app.state.agent
    facts = await state.graph_extractor.extract(body.text)
    for f in facts:
        f.setdefault("source_doc", body.document_id)
    result = await state.graph_service.add_facts_merged(tenant_id=subject.tenant_id, facts=facts)
    return {"document_id": body.document_id, **result}


@router.post("/facts")
async def add_fact(
    body: FactRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("graph:write", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    fact_id = await state.graph_service.add_fact(
        tenant_id=subject.tenant_id,
        subject=body.subject,
        predicate=body.predicate,
        object=body.object,
        aliases=body.aliases,
        confidence=body.confidence,
        source_doc=body.source_doc,
        source_chunk=body.source_chunk,
        source_version=body.source_version,
    )
    return {"fact_id": fact_id}


@router.post("/query")
async def query_graph(
    body: GraphQueryRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    facts = await state.graph_service.retrieve(query=body.query, tenant_id=subject.tenant_id, k=body.k)
    return {"facts": facts}


@router.get("/entity/{name}")
async def entity_detail(
    name: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    canonical = await state.graph_service.store.resolve(tenant_id=subject.tenant_id, name=name)
    if canonical is None:
        return {"entity": name, "canonical": None, "facts": []}
    facts = await state.graph_service.store.query_entity(tenant_id=subject.tenant_id, entity=canonical, k=50)
    return {"entity": name, "canonical": canonical, "facts": facts}
