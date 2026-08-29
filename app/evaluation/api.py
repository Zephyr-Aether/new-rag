"""Evaluation API（§20 数据飞轮）：
POST /evaluations/bad-cases   手动录入 Bad-Case 进评测集
GET  /evaluations/cases       列出评测样例（kind=BADCASES 默认）
POST /runs/{id}/feedback      用户反馈；bad => 自动进评测集
POST /agents/{id}/versions/{v}/regression  发布回归（BADCASES 跑该版本）
GET  /agents/{id}/versions/{v}/regression  最近一次回归结果
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.api.runs import _deps
from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject, require_perm
from app.state import AppState
from app.storage.models import AgentVersionRow

router = APIRouter(prefix="", tags=["evaluation"])

# 评测种子配置存配置中心（页面可编辑的评测用例清单，导入时 upsert 到评测集）
_EVAL_SEED_SCOPE = {"tenant_id": "", "scope": "EVAL", "scope_id": "default", "key": "seed_cases"}


class BadCaseRequest(BaseModel):
    query: str
    run_id: str = ""
    reason: str = ""
    category: str = ""
    expected: list[str] | None = None  # 期望答案关键词（回归判定用）


class FeedbackRequest(BaseModel):
    feedback: str = Field(pattern="^(good|bad)$")
    reason: str = ""


@router.post("/evaluations/bad-cases")
async def add_bad_case(
    body: BadCaseRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    return await state.evaluation_service.add_bad_case(
        tenant_id=subject.tenant_id,
        query=body.query,
        run_id=body.run_id,
        reason=body.reason,
        category=body.category,
        expected=body.expected,
    )


@router.get("/evaluations/cases")
async def list_cases(request: Request, kind: str = "BADCASES", limit: int = 100) -> dict:
    state: AppState = request.app.state.agent
    rows = await state.evaluation_service.list_cases(kind=kind, limit=limit)
    return {"rows": rows, "total": len(rows)}


class EvalCaseRequest(BaseModel):
    query: str
    kind: str = "BADCASES"  # BADCASES / GOLDEN / ADVERSARIAL / REGRESSION
    reason: str = ""
    category: str = ""
    expected: list[str] | None = None
    expected_tool_calls: list[str] | None = None
    must_not_call: list[str] | None = None
    judge_type: str = "keyword"  # keyword 关键词 / llm LLM-as-judge


@router.post("/evaluations/cases")
async def add_eval_case(
    body: EvalCaseRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("eval:write", "*"))],
) -> dict:
    """§21 评测样例录入（可按 kind 建 GOLDEN/ADVERSARIAL/BADCASES 等数据集）。"""
    state: AppState = request.app.state.agent
    return await state.evaluation_service.add_case(
        tenant_id=subject.tenant_id,
        query=body.query,
        kind=body.kind,
        reason=body.reason,
        category=body.category,
        expected=body.expected,
        expected_tool_calls=body.expected_tool_calls,
        must_not_call=body.must_not_call,
        judge_type=body.judge_type,
    )


@router.get("/evaluations/seed-config")
async def get_seed_config(request: Request) -> dict:
    """读取评测种子配置（页面可编辑的用例清单，存配置中心）。"""
    state: AppState = request.app.state.agent
    saved = await state.config_service.get(**_EVAL_SEED_SCOPE)
    if saved and saved.get("value"):
        return {"cases": saved["value"], "source": "config"}
    return {"cases": [], "source": "none"}


class SeedConfigRequest(BaseModel):
    cases: list[dict] = Field(default_factory=list)


@router.put("/evaluations/seed-config")
async def set_seed_config(body: SeedConfigRequest, request: Request) -> dict:
    """保存评测种子配置到配置中心。"""
    state: AppState = request.app.state.agent
    await state.config_service.set(**_EVAL_SEED_SCOPE, value=body.cases)
    return {"ok": True, "count": len(body.cases)}


@router.post("/evaluations/cases/seed")
async def seed_eval_cases(
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("eval:write", "*"))],
) -> dict:
    """从页面配置导入评测样例（按 query+kind upsert）。返回 {added, updated, skipped}。"""
    state: AppState = request.app.state.agent
    saved = await state.config_service.get(**_EVAL_SEED_SCOPE)
    items = (saved or {}).get("value") or []
    return await state.evaluation_service.seed_cases(tenant_id=subject.tenant_id, items=items)


@router.post("/agents/runs/{run_id}/feedback")
async def run_feedback(
    run_id: str,
    body: FeedbackRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§20 在线质量闭环：用户 bad 反馈 => 自动进 BADCASES 评测集。"""
    state: AppState = request.app.state.agent
    run = await state.store.get_run(run_id)
    if run is None:
        raise AgentError(f"run not found: {run_id}", code="RUN_NOT_FOUND")
    if body.feedback == "bad":
        # 从 run 取原始问题作为 query
        import json

        query = json.loads(run["input_json"] or "{}").get("text", "")
        case = await state.evaluation_service.add_bad_case(
            tenant_id=subject.tenant_id, query=query, run_id=run_id, reason=body.reason
        )
        if state.event_outbox is not None:  # §28.2 事件 Outbox：bad 反馈入飞轮事件流
            await state.event_outbox.publish(
                event_type="feedback.bad",
                tenant_id=subject.tenant_id,
                aggregate_id=run_id,
                payload={"query": query, "case_id": case["case_id"], "reason": body.reason},
                dedupe_key=f"feedback.bad:{run_id}",
            )
        return {"feedback": "bad", "case_id": case["case_id"], "recorded": True}
    return {"feedback": "good", "recorded": False}


async def _get_version_row(state: AppState, tenant_id: str, agent_id: str, version: int) -> AgentVersionRow:
    async with state.sessions() as s:
        row = await s.scalar(
            select(AgentVersionRow).where(
                AgentVersionRow.tenant_id == tenant_id,
                AgentVersionRow.agent_id == agent_id,
                AgentVersionRow.version == version,
            )
        )
    if row is None:
        raise AgentError(f"agent version not found: {agent_id} v{version}", code="AGENT_VERSION_NOT_FOUND")
    return row


@router.post("/agents/{agent_id}/versions/{version}/regression")
async def run_version_regression(
    agent_id: str,
    version: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    kind: str = Query(default="BADCASES"),
) -> dict:
    """§20 发布回归：对指定 kind 评测集（BADCASES/GOLDEN/ADVERSARIAL...）跑该版本。"""
    state: AppState = request.app.state.agent
    row = await _get_version_row(state, subject.tenant_id, agent_id, version)
    return await state.evaluation_service.run_regression(
        tenant_id=subject.tenant_id,
        agent_id=agent_id,
        version=version,
        system_prompt=row.system_prompt,
        deps=_deps(state),
        dataset_kind=kind,
    )


@router.post("/agents/{agent_id}/versions/{version}/security-eval")
async def run_security_eval(
    agent_id: str,
    version: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§21.1 Security 评测：跑 ADVERSARIAL 注入用例，判定是否被利用（无外呼/无泄露）。"""
    state: AppState = request.app.state.agent
    row = await _get_version_row(state, subject.tenant_id, agent_id, version)
    return await state.evaluation_service.run_security_eval(
        tenant_id=subject.tenant_id,
        agent_id=agent_id,
        version=version,
        system_prompt=row.system_prompt,
        deps=_deps(state),
    )


@router.get("/agents/{agent_id}/versions/{version}/regression")
async def get_version_regression(
    agent_id: str,
    version: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    state: AppState = request.app.state.agent
    latest = await state.evaluation_service.latest_regression(
        tenant_id=subject.tenant_id, agent_id=agent_id, version=version
    )
    if latest is None:
        raise AgentError(f"no regression for {agent_id} v{version}", code="REGRESSION_NOT_FOUND")
    return latest


@router.get("/agents/{agent_id}/regression-runs")
async def list_regression_runs(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    """评测运行历史：最近 N 次回归，含与上一次的通过率差值。"""
    state: AppState = request.app.state.agent
    runs = await state.evaluation_service.list_regressions(
        tenant_id=subject.tenant_id, agent_id=agent_id, limit=limit
    )
    return {"agent_id": agent_id, "runs": runs}
