"""Release API（§21 / §57 MVP 子集）：

POST /agents/{agent_id}/versions                      创建新版本（DRAFT，version 自增）
GET  /agents/{agent_id}/versions                      列出版本
POST /agents/{agent_id}/versions/{version}/publish        发布为 ACTIVE（过 §58 门禁）
POST /agents/{agent_id}/versions/{version}/contract-check 发布前 10 项兼容性检查报告
POST /agents/{agent_id}/versions/{version}/gray           灰度（percentage）
POST /agents/{agent_id}/rollback                          回滚
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.api.runs import _deps
from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.deps import get_subject, require_perm
from app.state import AppState
from app.storage.models import AgentVersionRow

router = APIRouter(prefix="/agents", tags=["release"])


class GrayRequest(BaseModel):
    percentage: int = Field(ge=0, le=100)


class VersionCreateRequest(BaseModel):
    system_prompt: str = Field(min_length=1)
    model: str = ""
    config: dict = Field(default_factory=dict)


class PublishRequest(BaseModel):
    force: bool = False  # True 跳过 §58 门禁（紧急发布逃生口）
    evaluate: bool = False  # True 发布前跑 §20 回归，回退则阻断


class RollbackRequest(BaseModel):
    to_version: int | None = None


@router.post("/{agent_id}/versions")
async def create_version(
    agent_id: str,
    body: VersionCreateRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("release:version:create", "*"))],
) -> dict:
    """§22 创建新版本（DRAFT，version 自增）。"""
    state: AppState = request.app.state.agent
    return await state.release.create_version(
        tenant_id=subject.tenant_id,
        agent_id=agent_id,
        system_prompt=body.system_prompt,
        model=body.model,
        config=body.config,
        created_by=subject.user_id,
    )


@router.get("/{agent_id}/versions")
async def list_versions(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """列出 Agent 全部版本（按 version 降序）。"""
    state: AppState = request.app.state.agent
    versions = await state.release.list_versions(tenant_id=subject.tenant_id, agent_id=agent_id)
    return {"agent_id": agent_id, "versions": versions}


@router.post("/{agent_id}/versions/{version}/publish")
async def publish_version(
    agent_id: str,
    version: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("release:publish", "*"))],  # 权限 AOP
    body: PublishRequest | None = None,
) -> dict:
    state: AppState = request.app.state.agent
    force = body.force if body else False
    explicit_eval = body.evaluate if body else False
    # §20 发布自动回归：租户有评测集即自动跑，回退阻断；force 只跳过 §58 契约，质量回归仍门禁
    if explicit_eval or await state.evaluation_service.has_cases(tenant_id=subject.tenant_id):
        async with state.sessions() as s:
            row = await s.scalar(
                select(AgentVersionRow).where(
                    AgentVersionRow.tenant_id == subject.tenant_id,
                    AgentVersionRow.agent_id == agent_id,
                    AgentVersionRow.version == version,
                )
            )
        if row is None:
            raise AgentError(
                f"agent version not found: {agent_id} v{version}", code="AGENT_VERSION_NOT_FOUND"
            )
        regression = await state.evaluation_service.run_regression(
            tenant_id=subject.tenant_id,
            agent_id=agent_id,
            version=version,
            system_prompt=row.system_prompt,
            deps=_deps(state),
        )
        if regression["regressed"]:
            prev = regression.get("previous_pass_rate")
            rate = regression.get("pass_rate", 0)
            prev_txt = f"{prev:.0%}" if prev is not None else "—"
            raise AgentError(
                f"回归未通过：通过率 {rate:.0%}，低于上一版本 {prev_txt}，"
                "已阻止发布（可在发布引导中勾选「强制发布」跳过回归门禁）",
                code="RELEASE_REGRESSION_FAILED",
                detail={"regression": regression},
            )
        result = await state.release.publish(
            tenant_id=subject.tenant_id, agent_id=agent_id, version=version, force=force
        )
        result["regression"] = regression
        return result
    return await state.release.publish(
        tenant_id=subject.tenant_id, agent_id=agent_id, version=version, force=force
    )


@router.post("/{agent_id}/versions/{version}/contract-check")
async def contract_check_version(
    agent_id: str,
    version: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§58 发布前 10 项兼容性检查报告（fail 阻断 / warn 人工签核）。"""
    state: AppState = request.app.state.agent
    return await state.release.contract_check(tenant_id=subject.tenant_id, agent_id=agent_id, version=version)


@router.post("/{agent_id}/versions/{version}/gray")
async def gray_version(
    agent_id: str,
    version: int,
    body: GrayRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("release:ops", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    return await state.release.gray(
        tenant_id=subject.tenant_id, agent_id=agent_id, version=version, percentage=body.percentage
    )


@router.post("/{agent_id}/rollback")
async def rollback_agent(
    agent_id: str,
    body: RollbackRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("release:ops", "*"))],
) -> dict:
    state: AppState = request.app.state.agent
    return await state.release.rollback(
        tenant_id=subject.tenant_id, agent_id=agent_id, to_version=body.to_version
    )


@router.post("/{agent_id}/versions/{version}/halt")
async def halt_version(
    agent_id: str,
    version: int,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("release:ops", "*"))],
) -> dict:
    """§57 Canary 自动停：手动停掉灰度版本（新流量回落 ACTIVE）。"""
    state: AppState = request.app.state.agent
    return await state.release.halt(tenant_id=subject.tenant_id, agent_id=agent_id, version=version)


@router.post("/{agent_id}/canary/check")
async def canary_check(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§57 Canary 自动停发布（指标驱动）：错误率/成本超阈值 => 自动 halt + 自动回滚。"""
    state: AppState = request.app.state.agent
    return await state.release.canary_check(tenant_id=subject.tenant_id, agent_id=agent_id, version=1)


@router.post("/{agent_id}/canary/evaluate")
async def canary_evaluate(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§57 Canary 全自动：对当前 GRAY 版本评估并自动停/回滚（指标驱动）。"""
    state: AppState = request.app.state.agent
    # 找当前 GRAY 版本
    async with state.sessions() as s:
        gray = await s.scalar(
            select(AgentVersionRow).where(
                AgentVersionRow.tenant_id == subject.tenant_id,
                AgentVersionRow.agent_id == agent_id,
                AgentVersionRow.status == "GRAY",
            )
        )
    if gray is None:
        return {"action": "no-gray", "reason": "no GRAY version running"}
    return await state.release.canary_check(
        tenant_id=subject.tenant_id, agent_id=agent_id, version=gray.version
    )


@router.get("/{agent_id}/release-metrics")
async def release_metrics(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """§21 灰度指标：按 release_version + release_status 聚合运行量/成本/错误率（决策已落 run）。"""
    import json

    from sqlalchemy import text

    state: AppState = request.app.state.agent
    async with state.sessions() as s:
        rows = await s.execute(
            text(
                "SELECT agent_version, model_config, tokens_in, tokens_out, cost, error_json "
                "FROM agent_runs WHERE agent_id = :a AND tenant_id = :t"
            ),
            {"a": agent_id, "t": subject.tenant_id},
        )
        runs = [dict(r._mapping) for r in rows]
    groups: dict[tuple, dict] = {}
    for r in runs:
        mc = json.loads(r["model_config"] or "{}")
        status = mc.get("release_status", "ACTIVE")
        version = mc.get("release_version", r["agent_version"])
        g = groups.setdefault(
            (version, status), {"runs": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "errors": 0}
        )
        g["runs"] += 1
        g["tokens_in"] += r["tokens_in"] or 0
        g["tokens_out"] += r["tokens_out"] or 0
        g["cost"] += r["cost"] or 0
        if r["error_json"]:
            g["errors"] += 1
    metrics = []
    for (version, status), g in sorted(groups.items()):
        metrics.append(
            {
                "version": version,
                "release_status": status,
                **g,
                "error_rate": round(g["errors"] / g["runs"], 3) if g["runs"] else 0.0,
            }
        )
    return {"agent_id": agent_id, "metrics": metrics}


class FlowHistoryRequest(BaseModel):
    version: int = 0
    step: str
    summary: str = ""
    ok: bool = True
    detail: str | None = None


@router.get("/{agent_id}/flow-history")
async def list_flow_history(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    step: str | None = None,
    limit: int = 200,
) -> dict:
    """发布流程执行历史（留痕），可选按 step 过滤。"""
    state: AppState = request.app.state.agent
    records = await state.release.list_flow_history(
        tenant_id=subject.tenant_id,
        agent_id=agent_id,
        step=step,
        limit=limit,
    )
    return {"agent_id": agent_id, "records": records}


@router.post("/{agent_id}/flow-history")
async def add_flow_history(
    agent_id: str,
    body: FlowHistoryRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """记录一步发布流程执行（operator 取当前用户）。"""
    state: AppState = request.app.state.agent
    return await state.release.add_flow_history(
        tenant_id=subject.tenant_id,
        agent_id=agent_id,
        version=body.version,
        step=body.step,
        operator=subject.user_id,
        summary=body.summary,
        ok=body.ok,
        detail=body.detail,
    )


class NodeConfigRequest(BaseModel):
    config: dict = Field(default_factory=dict)
    status: str | None = None  # 可选：同步更新当前阶段标识


@router.get("/{agent_id}/release-flow")
async def get_release_flow(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """发布流配置：5 节点（code/name/config）+ 当前阶段 status + 是否终止。"""
    state: AppState = request.app.state.agent
    return await state.release.get_flow_config(tenant_id=subject.tenant_id, agent_id=agent_id)


@router.post("/{agent_id}/release-flow/start")
async def start_release_flow(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """开启新的发布流：清空节点 config、重置阶段并解除终止。"""
    state: AppState = request.app.state.agent
    return await state.release.start_flow(tenant_id=subject.tenant_id, agent_id=agent_id)


@router.post("/{agent_id}/release-flow/terminate")
async def terminate_release_flow(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """随时终止发布流。"""
    state: AppState = request.app.state.agent
    return await state.release.terminate_flow(tenant_id=subject.tenant_id, agent_id=agent_id)


@router.post("/{agent_id}/release-flow/{node_code}")
async def save_release_flow_node(
    agent_id: str,
    node_code: str,
    body: NodeConfigRequest,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """保存某节点的 config（前端回显）；可选同步当前阶段标识。"""
    state: AppState = request.app.state.agent
    if body.status:
        await state.release.save_flow_status(
            tenant_id=subject.tenant_id, agent_id=agent_id, status=body.status
        )
    return await state.release.save_node_config(
        tenant_id=subject.tenant_id, agent_id=agent_id, node_code=node_code, config=body.config
    )


@router.post("/{agent_id}/release-orders")
async def create_release_order(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
    _: Annotated[Subject, Depends(require_perm("release:version:create", "*"))],
) -> dict:
    """创建发布单：终止旧的进行中单、重置发布流到草稿步，进入新的发布单流程。"""
    state: AppState = request.app.state.agent
    return await state.release.create_order(
        tenant_id=subject.tenant_id, agent_id=agent_id, created_by=subject.user_id
    )


@router.get("/{agent_id}/release-orders")
async def list_release_orders(
    agent_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """列出全部发布单（新→旧）。"""
    state: AppState = request.app.state.agent
    orders = await state.release.list_orders(tenant_id=subject.tenant_id, agent_id=agent_id)
    return {"agent_id": agent_id, "orders": orders}


@router.get("/{agent_id}/release-orders/{order_id}")
async def get_release_order(
    agent_id: str,
    order_id: str,
    request: Request,
    subject: Annotated[Subject, Depends(get_subject)],
) -> dict:
    """发布单详情：元信息 + 节点快照 + 该单留痕。"""
    state: AppState = request.app.state.agent
    return await state.release.get_order(
        tenant_id=subject.tenant_id, agent_id=agent_id, order_id=order_id
    )
